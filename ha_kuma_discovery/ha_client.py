"""Shared Home Assistant Supervisor and WebSocket access."""

import json
import logging
import os
from typing import Any, Dict
from urllib.parse import urljoin

import websocket


SUPERVISOR = "http://supervisor/"
HA_WS = "ws://supervisor/core/websocket"
LOG = logging.getLogger("ha-kuma-discovery")


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
