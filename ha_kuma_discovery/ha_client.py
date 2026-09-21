"""Shared Home Assistant Supervisor and WebSocket access."""

import json
import ipaddress
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urljoin, urlparse

import websocket


SUPERVISOR = "http://supervisor/"
HA_WS = "ws://supervisor/core/websocket"
LOG = logging.getLogger("ha-kuma-discovery")


def entity_domain(entity_id: str) -> str:
    return str(entity_id).split(".", 1)[0] if "." in str(entity_id) else ""


def state_ip(attributes: Dict[str, Any]) -> str | None:
    """Try common Home Assistant attributes used for network addresses."""
    for key in ("ip", "ip_address", "host", "address"):
        value = attributes.get(key)
        if not value:
            continue
        value = str(value).strip()

        if "://" in value:
            try:
                parsed = urlparse(value)
                value = parsed.hostname or ""
            except Exception:
                pass

        if value and not re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", value):
            return value
    return None


def normalize_mac(value: str) -> str:
    return re.sub(r"[^0-9a-f]", "", str(value).lower())


def device_mac_from_registry(device: Dict[str, Any]) -> str | None:
    for connection in device.get("connections") or []:
        if not isinstance(connection, (list, tuple)) or len(connection) != 2:
            continue
        connection_type, value = connection
        if str(connection_type).lower() == "mac" and value:
            return normalize_mac(str(value))
    return None


def looks_like_mac_name(value: str) -> bool:
    value = str(value or "").strip()
    if not value:
        return False
    return bool(
        re.fullmatch(r"(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}", value)
        or re.fullmatch(r"[0-9A-Fa-f]{12}", value)
    )


def is_private_or_local_host(host: str) -> bool:
    """Accept hostnames and local IP addresses, but reject public IPs."""
    host = str(host or "").strip()
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local)


def config_entry_hosts_from_storage(
    domain: str,
    allowed_entry_ids: set[str],
    config_entries_path: Path,
    log,
) -> Dict[str, str]:
    """Return config-entry data.host values for a specific HA integration."""
    hosts: Dict[str, str] = {}
    if not allowed_entry_ids:
        return hosts

    if not config_entries_path.exists():
        log.warning(
            "Home Assistant config-entry storage is not mounted at %s; "
            "%s host discovery is unavailable.",
            config_entries_path,
            domain,
        )
        return hosts

    try:
        raw = json.loads(config_entries_path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("Could not read Home Assistant config-entry storage: %s", exc)
        return hosts

    for entry in (raw.get("data") or {}).get("entries") or []:
        if str(entry.get("domain") or "") != domain:
            continue

        entry_id = str(entry.get("entry_id") or "")
        if not entry_id or entry_id not in allowed_entry_ids:
            continue

        host = str((entry.get("data") or {}).get("host") or "").strip()
        if host:
            hosts[entry_id] = host

    return hosts


def device_has_identifier(device: Dict[str, Any], identifier_type: str) -> bool:
    for identifier in device.get("identifiers") or []:
        if (
            isinstance(identifier, (list, tuple))
            and len(identifier) >= 2
            and str(identifier[0]).lower() == identifier_type.lower()
        ):
            return True
    return False


def supervisor_get(path: str, session, supervisor_url: str = SUPERVISOR) -> Any:
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise RuntimeError("SUPERVISOR_TOKEN is unavailable.")

    response = session.get(
        urljoin(supervisor_url, path.lstrip("/")),
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("result") != "ok":
        raise RuntimeError(f"Supervisor API error for {path}: {payload}")
    return payload.get("data")


class HAWebSocket:
    """
    Home Assistant WebSocket helper with a shared connection and request cache
    for one complete discovery cycle.
    """

    _cycle_active = False
    _shared_ws = None
    _shared_next_id = 1
    _shared_cache: Dict[str, Any] = {}
    _network_calls = 0
    _cache_hits = 0

    def __init__(self):
        self.ws = None
        self.next_id = 1
        self._using_shared = False

    @classmethod
    def _open_socket(cls):
        token = os.environ.get("SUPERVISOR_TOKEN")
        if not token:
            raise RuntimeError("SUPERVISOR_TOKEN is unavailable.")

        ws = websocket.create_connection(HA_WS, timeout=20)
        hello = json.loads(ws.recv())
        if hello.get("type") != "auth_required":
            try:
                ws.close()
            except Exception:
                pass
            raise RuntimeError(f"Unexpected HA WebSocket greeting: {hello}")

        ws.send(json.dumps({"type": "auth", "access_token": token}))
        auth = json.loads(ws.recv())
        if auth.get("type") != "auth_ok":
            try:
                ws.close()
            except Exception:
                pass
            raise RuntimeError(f"Home Assistant WebSocket authentication failed: {auth}")
        return ws

    @classmethod
    def begin_cycle(cls):
        cls.end_cycle(log_stats=False)
        cls._shared_ws = cls._open_socket()
        cls._shared_next_id = 1
        cls._shared_cache = {}
        cls._network_calls = 0
        cls._cache_hits = 0
        cls._cycle_active = True

    @classmethod
    def end_cycle(cls, log_stats=True):
        if log_stats and cls._cycle_active:
            LOG.info(
                "HA WebSocket cycle: %d network request(s), %d cached request(s)",
                cls._network_calls,
                cls._cache_hits,
            )
        if cls._shared_ws is not None:
            try:
                cls._shared_ws.close()
            except Exception:
                pass
        cls._shared_ws = None
        cls._shared_cache = {}
        cls._cycle_active = False

    def __enter__(self):
        if self.__class__._cycle_active:
            if self.__class__._shared_ws is None:
                self.__class__._shared_ws = self.__class__._open_socket()
            self.ws = self.__class__._shared_ws
            self._using_shared = True
            return self

        self.ws = self.__class__._open_socket()
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._using_shared:
            return
        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:
                pass

    def call(self, command: Dict[str, Any]):
        cache_key = json.dumps(command, sort_keys=True, separators=(",", ":"))

        if self.__class__._cycle_active and cache_key in self.__class__._shared_cache:
            self.__class__._cache_hits += 1
            return self.__class__._shared_cache[cache_key]

        if self.__class__._cycle_active:
            msg_id = self.__class__._shared_next_id
            self.__class__._shared_next_id += 1
        else:
            msg_id = self.next_id
            self.next_id += 1

        payload = dict(command)
        payload["id"] = msg_id
        try:
            self.ws.send(json.dumps(payload))

            while True:
                response = json.loads(self.ws.recv())
                if response.get("id") != msg_id:
                    continue
                if response.get("type") != "result":
                    continue
                if not response.get("success"):
                    raise RuntimeError(
                        f"HA WebSocket command failed: {payload.get('type')}: "
                        f"{response.get('error')}"
                    )

                result = response.get("result")
                if self.__class__._cycle_active:
                    self.__class__._shared_cache[cache_key] = result
                    self.__class__._network_calls += 1
                return result
        except (websocket.WebSocketException, OSError, ValueError):
            try:
                self.ws.close()
            except Exception:
                pass
            if self._using_shared:
                self.__class__._shared_ws = None
            raise
