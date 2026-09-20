#!/usr/bin/env python3

import json
import logging
import os
import re
import time
import ipaddress
from contextlib import contextmanager, ExitStack
from pathlib import Path
from typing import Dict, Any
from urllib.parse import urlparse

import requests
import websocket
from uptime_kuma_api import UptimeKumaApi, MonitorType

import ha_client
import state_store


OPTIONS = Path("/data/options.json")
STATE = Path("/data/state.json")
SUPERVISOR = "http://supervisor/"
HA_WS = "ws://supervisor/core/websocket"
HA_CONFIG_ENTRIES = Path("/homeassistant/.storage/core.config_entries")
LOG = logging.getLogger("ha-kuma-discovery")
# Headers (especially SUPERVISOR_TOKEN) remain request-local.
HTTP = requests.Session()


def read_options() -> Dict[str, Any]:
    with OPTIONS.open("r", encoding="utf-8") as f:
        data = json.load(f)

    required = ("kuma_url", "kuma_username", "kuma_password")
    missing = [k for k in required if not str(data.get(k, "")).strip()]
    if missing:
        raise RuntimeError("Missing required option(s): " + ", ".join(missing))

    data["kuma_url"] = str(data["kuma_url"]).rstrip("/")
    data["sync_interval"] = max(20, int(data.get("sync_interval", 60)))
    data["heartbeat_interval"] = max(
        data["sync_interval"] + 30,
        int(data.get("heartbeat_interval", 180)),
    )
    data["shelly_ping_interval"] = max(20, int(data.get("shelly_ping_interval", 60)))
    data["shelly_max_retries"] = max(0, int(data.get("shelly_max_retries", 2)))
    data["unifi_ping_interval"] = max(20, int(data.get("unifi_ping_interval", 60)))
    data["unifi_max_retries"] = max(0, int(data.get("unifi_max_retries", 2)))
    data["fritz_ping_interval"] = max(20, int(data.get("fritz_ping_interval", 60)))
    data["fritz_max_retries"] = max(0, int(data.get("fritz_max_retries", 2)))
    data["fully_kiosk_ping_interval"] = max(20, int(data.get("fully_kiosk_ping_interval", 60)))
    data["fully_kiosk_max_retries"] = max(0, int(data.get("fully_kiosk_max_retries", 2)))
    data["homematic_ip_ping_interval"] = max(20, int(data.get("homematic_ip_ping_interval", 60)))
    data["homematic_ip_max_retries"] = max(0, int(data.get("homematic_ip_max_retries", 2)))
    data["e3dc_ping_interval"] = max(20, int(data.get("e3dc_ping_interval", 60)))
    data["e3dc_max_retries"] = max(0, int(data.get("e3dc_max_retries", 2)))
    data["overkiz_ping_interval"] = max(20, int(data.get("overkiz_ping_interval", 60)))
    data["overkiz_max_retries"] = max(0, int(data.get("overkiz_max_retries", 2)))
    data["hue_ping_interval"] = max(20, int(data.get("hue_ping_interval", 60)))
    data["hue_max_retries"] = max(0, int(data.get("hue_max_retries", 2)))
    data["smlight_ping_interval"] = max(20, int(data.get("smlight_ping_interval", 60)))
    data["smlight_max_retries"] = max(0, int(data.get("smlight_max_retries", 2)))
    data["stiebel_eltron_ping_interval"] = max(20, int(data.get("stiebel_eltron_ping_interval", 60)))
    data["stiebel_eltron_max_retries"] = max(0, int(data.get("stiebel_eltron_max_retries", 2)))
    data["synology_ping_interval"] = max(20, int(data.get("synology_ping_interval", 60)))
    data["synology_max_retries"] = max(0, int(data.get("synology_max_retries", 2)))
    data["airgradient_ping_interval"] = max(20, int(data.get("airgradient_ping_interval", 60)))
    data["airgradient_max_retries"] = max(0, int(data.get("airgradient_max_retries", 2)))
    data["airgradient_monitor_prefix"] = str(data.get("airgradient_monitor_prefix", "AirGradient: "))
    data["discover_airgradient_devices"] = bool(data.get("discover_airgradient_devices", True))
    data["esphome_ping_interval"] = max(20, int(data.get("esphome_ping_interval", 60)))
    data["esphome_max_retries"] = max(0, int(data.get("esphome_max_retries", 2)))

    data["monitor_prefix"] = str(data.get("monitor_prefix", "HA Add-on: "))
    data["shelly_monitor_prefix"] = str(data.get("shelly_monitor_prefix", "Shelly: "))
    data["unifi_monitor_prefix"] = str(data.get("unifi_monitor_prefix", "UniFi: "))
    data["fritz_monitor_prefix"] = str(data.get("fritz_monitor_prefix", "FRITZ!: "))
    data["fully_kiosk_monitor_prefix"] = str(data.get("fully_kiosk_monitor_prefix", "Fully Kiosk: "))
    data["homematic_ip_monitor_prefix"] = str(data.get("homematic_ip_monitor_prefix", "Homematic IP: "))
    data["matter_monitor_prefix"] = str(data.get("matter_monitor_prefix", "Matter: "))
    data["e3dc_monitor_prefix"] = str(data.get("e3dc_monitor_prefix", "E3DC: "))
    data["overkiz_monitor_prefix"] = str(data.get("overkiz_monitor_prefix", "Somfy: "))
    data["hue_monitor_prefix"] = str(data.get("hue_monitor_prefix", "Hue: "))
    data["smlight_monitor_prefix"] = str(data.get("smlight_monitor_prefix", "SMLIGHT: "))
    data["stiebel_eltron_monitor_prefix"] = str(data.get("stiebel_eltron_monitor_prefix", "Stiebel Eltron: "))
    data["synology_monitor_prefix"] = str(data.get("synology_monitor_prefix", "Synology: "))
    data["esphome_monitor_prefix"] = str(data.get("esphome_monitor_prefix", "ESPHome: "))
    data["zigbee2mqtt_monitor_prefix"] = str(data.get("zigbee2mqtt_monitor_prefix", "Zigbee2MQTT: "))
    data["mqtt_monitor_prefix"] = str(data.get("mqtt_monitor_prefix", "MQTT: "))
    data["push_down_grace_cycles"] = max(1, int(data.get("push_down_grace_cycles", 3)))
    data["verify_ssl"] = bool(data.get("verify_ssl", True))
    data["discover_addons"] = bool(data.get("discover_addons", True))
    data["discover_shelly"] = bool(data.get("discover_shelly", True))
    data["discover_unifi_network_devices"] = bool(
        data.get("discover_unifi_network_devices", True)
    )
    data["discover_fritz_network_devices"] = bool(
        data.get("discover_fritz_network_devices", True)
    )
    data["discover_fully_kiosk_devices"] = bool(
        data.get("discover_fully_kiosk_devices", True)
    )
    data["discover_homematic_ip_infrastructure"] = bool(
        data.get("discover_homematic_ip_infrastructure", True)
    )
    data["discover_matter_devices"] = bool(data.get("discover_matter_devices", True))
    data["discover_e3dc_devices"] = bool(data.get("discover_e3dc_devices", True))
    data["discover_overkiz_devices"] = bool(data.get("discover_overkiz_devices", True))
    data["discover_hue_bridge"] = bool(data.get("discover_hue_bridge", True))
    data["discover_hue_devices"] = bool(data.get("discover_hue_devices", False))
    data["discover_smlight_devices"] = bool(data.get("discover_smlight_devices", True))
    data["discover_stiebel_eltron"] = bool(data.get("discover_stiebel_eltron", True))
    data["discover_synology_dsm"] = bool(data.get("discover_synology_dsm", True))
    data["discover_esphome_devices"] = bool(data.get("discover_esphome_devices", True))
    data["discover_zigbee2mqtt_devices"] = bool(data.get("discover_zigbee2mqtt_devices", True))
    data["discover_mqtt_devices"] = bool(data.get("discover_mqtt_devices", True))
    data["ignore_slugs_set"] = {
        x.strip() for x in str(data.get("ignore_slugs", "")).split(",") if x.strip()
    }
    return data


def load_state() -> Dict[str, Any]:
    return state_store.load_state(STATE, LOG)


def save_state(state: Dict[str, Any]) -> None:
    state_store.save_state(state, STATE, LOG)


def supervisor_get(path: str) -> Any:
    return ha_client.supervisor_get(path, HTTP, SUPERVISOR)


HAWebSocket = ha_client.HAWebSocket



def normalize_items(raw):
    if isinstance(raw, dict):
        return list(raw.values())
    if isinstance(raw, list):
        return raw
    return []


def find_monitor(monitors, name: str, monitor_type: str):
    for monitor in monitors:
        if monitor.get("name") == name and monitor.get("type") == monitor_type:
            return monitor
    return None


def find_managed_monitor(monitors, name, monitor_type, state=None, identity=None):
    """Resolve a managed monitor by its persisted source identity before name."""
    if state is not None and identity:
        record = state.get("_monitor_identities", {}).get(identity, {})
        monitor_id = record.get("monitor_id")
        if monitor_id is not None:
            for monitor in monitors:
                if (str(monitor.get("id")) == str(monitor_id)
                        and monitor.get("type") == monitor_type):
                    return monitor

        previous_name = str(record.get("name") or "")
        if previous_name:
            previous = find_monitor(monitors, previous_name, monitor_type)
            if previous:
                return previous

    return find_monitor(monitors, name, monitor_type)


def remember_monitor_identity(state, identity, monitor, name, monitor_type):
    if state is None or not identity or not monitor or monitor.get("id") is None:
        return
    state.setdefault("_monitor_identities", {})[identity] = {
        "monitor_id": monitor["id"],
        "name": name,
        "type": monitor_type,
    }


def notification_is_default(notification: Dict[str, Any]) -> bool:
    if bool(notification.get("isDefault")):
        return True

    raw_config = notification.get("config")
    if isinstance(raw_config, str):
        try:
            return bool(json.loads(raw_config).get("isDefault"))
        except Exception:
            return False
    if isinstance(raw_config, dict):
        return bool(raw_config.get("isDefault"))
    return False


def notification_is_active(notification: Dict[str, Any]) -> bool:
    return notification.get("active", True) is not False


@contextmanager
def kuma_operation(stage, log_duration=False):
    """Report only our fixed stage and exception class, never request payloads."""
    started = time.monotonic()
    try:
        yield
    except Exception as exc:
        LOG.error("Kuma operation failed: %s (%s)", stage, type(exc).__name__)
        raise
    else:
        if log_duration:
            LOG.info("Kuma operation completed: %s in %.1fs",
                     stage, time.monotonic() - started)


def kuma_call(stage, operation, *args, _log_duration=False, **kwargs):
    with kuma_operation(stage, log_duration=_log_duration):
        return operation(*args, **kwargs)


@contextmanager
def kuma_session(opts):
    with ExitStack() as stack:
        with kuma_operation("opening Kuma API session", log_duration=True):
            api = stack.enter_context(UptimeKumaApi(
                opts["kuma_url"], timeout=30, ssl_verify=opts["verify_ssl"],
            ))
        yield api


def get_default_notification_ids(api) -> list[int]:
    notifications = normalize_items(kuma_call(
        "fetching notifications", api.get_notifications, _log_duration=True,
    ))
    ids = []
    for n in notifications:
        if notification_is_active(n) and notification_is_default(n):
            try:
                ids.append(int(n["id"]))
            except (KeyError, TypeError, ValueError):
                pass
    ids = sorted(set(ids))
    if ids:
        LOG.info("Using default Uptime Kuma notification(s): %s", ids)
    else:
        LOG.warning("No active default Uptime Kuma notification found")
    return ids


def monitor_notification_ids(monitor: Dict[str, Any]) -> list[int]:
    raw = monitor.get("notificationIDList")
    if isinstance(raw, dict):
        out = []
        for key, enabled in raw.items():
            if enabled:
                try:
                    out.append(int(key))
                except (TypeError, ValueError):
                    pass
        return sorted(set(out))
    if isinstance(raw, list):
        out = []
        for item in raw:
            try:
                out.append(int(item))
            except (TypeError, ValueError):
                pass
        return sorted(set(out))
    return []


def ensure_push_monitor(
    api, monitors, name, heartbeat_interval, default_notification_ids,
    state=None, identity=None,
):
    monitor = find_managed_monitor(monitors, name, "push", state, identity)

    if not monitor:
        LOG.info("Creating Uptime Kuma push monitor: %s", name)
        kwargs = {
            "type": MonitorType.PUSH,
            "name": name,
            "interval": heartbeat_interval,
            "retryInterval": heartbeat_interval,
            "maxretries": 0,
        }
        if default_notification_ids:
            kwargs["notificationIDList"] = default_notification_ids
        kuma_call("monitor creation", api.add_monitor, **kwargs)
        time.sleep(0.4)
        monitors[:] = normalize_items(kuma_call("fetching monitors", api.get_monitors))
        monitor = find_monitor(monitors, name, "push")
        if not monitor:
            raise RuntimeError(f"Could not retrieve created monitor '{name}'")
        remember_monitor_identity(state, identity, monitor, name, "push")
        return monitor

    edit = {}
    if str(monitor.get("name") or "") != name:
        edit["name"] = name
    current_interval = int(monitor.get("interval") or 0)
    if (
        current_interval != heartbeat_interval
        or int(monitor.get("retryInterval") or 0) != heartbeat_interval
        or int(monitor.get("maxretries") or 0) != 0
    ):
        edit.update(
            interval=heartbeat_interval,
            retryInterval=heartbeat_interval,
            maxretries=0,
        )

    current_notifications = monitor_notification_ids(monitor)
    if default_notification_ids and current_notifications != default_notification_ids:
        edit["notificationIDList"] = default_notification_ids

    if edit:
        LOG.info("Updating %s: %s", name, edit)
        kuma_call("monitor update", api.edit_monitor, int(monitor["id"]), **edit)
        time.sleep(0.2)
        monitors[:] = normalize_items(kuma_call("fetching monitors", api.get_monitors))
        monitor = find_managed_monitor(monitors, name, "push", state, identity)

    remember_monitor_identity(state, identity, monitor, name, "push")
    return monitor


def ensure_ping_monitor(
    api,
    monitors,
    name,
    host,
    interval,
    max_retries,
    default_notification_ids,
    state=None,
    identity=None,
):
    monitor = find_managed_monitor(monitors, name, "ping", state, identity)

    if not monitor:
        LOG.info("Creating ping monitor: %s -> %s", name, host)
        kwargs = {
            "type": MonitorType.PING,
            "name": name,
            "hostname": host,
            "interval": interval,
            "retryInterval": interval,
            "maxretries": max_retries,
        }
        if default_notification_ids:
            kwargs["notificationIDList"] = default_notification_ids
        kuma_call("monitor creation", api.add_monitor, **kwargs)
        time.sleep(0.4)
        monitors[:] = normalize_items(kuma_call("fetching monitors", api.get_monitors))
        monitor = find_monitor(monitors, name, "ping")
        if not monitor:
            raise RuntimeError(f"Could not retrieve created ping monitor '{name}'")
        remember_monitor_identity(state, identity, monitor, name, "ping")
        return monitor

    edit = {}
    if str(monitor.get("name") or "") != name:
        edit["name"] = name
    if str(monitor.get("hostname") or "") != host:
        edit["hostname"] = host
    if int(monitor.get("interval") or 0) != interval:
        edit["interval"] = interval
    if int(monitor.get("retryInterval") or 0) != interval:
        edit["retryInterval"] = interval
    if int(monitor.get("maxretries") or 0) != max_retries:
        edit["maxretries"] = max_retries

    current_notifications = monitor_notification_ids(monitor)
    if default_notification_ids and current_notifications != default_notification_ids:
        edit["notificationIDList"] = default_notification_ids

    if edit:
        LOG.info("Updating ping monitor %s: %s", name, edit)
        kuma_call("monitor update", api.edit_monitor, int(monitor["id"]), **edit)
        time.sleep(0.2)
        monitors[:] = normalize_items(kuma_call("fetching monitors", api.get_monitors))
        monitor = find_managed_monitor(monitors, name, "ping", state, identity)

    remember_monitor_identity(state, identity, monitor, name, "ping")
    return monitor


def push_status(kuma_url, monitor, up, message, verify_ssl):
    with kuma_operation("Push heartbeat HTTP call"):
        token = monitor.get("pushToken") or monitor.get("push_token")
        if not token:
            raise RuntimeError(f"Monitor '{monitor.get('name')}' has no push token")

        r = HTTP.get(
            f"{kuma_url}/api/push/{token}",
            params={"status": "up" if up else "down", "msg": message[:250]},
            timeout=20,
            verify=verify_ssl,
        )
        r.raise_for_status()
        payload = r.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Push failed for '{monitor.get('name')}': {payload}")


def push_status_if_needed(
    kuma_url,
    monitor,
    up,
    message,
    verify_ssl,
    state,
    heartbeat_interval,
    sync_interval,
):
    """Send every evaluated state; commit the successful heartbeat only after I/O.

    Keep the existing call signature and persisted cache format compatible.
    Callers must obtain a real observation before invoking this helper.
    """
    name = str(monitor.get("name") or monitor.get("id") or "unknown")
    push_status(kuma_url, monitor, up, message, verify_ssl)
    state.setdefault("_push_status_cache", {})[name] = {
        "up": bool(up), "last_push": time.time(),
    }
    return True



def _clean_shelly_name(name: str) -> str:
    """
    Collapse Home Assistant child/channel names to a physical-device name.

    Examples:
      "Schuppen Output 0" -> "Schuppen"
      "Shelly_Verdichter Energy Meter 1" -> "Shelly_Verdichter"
    """
    cleaned = str(name).strip()

    # Remove common channel/subdevice suffixes emitted by HA/Shelly.
    patterns = [
        r"\s+Energy Meter\s+\d+$",
        r"\s+Output\s+\d+$",
        r"\s+Channel\s+\d+$",
        r"\s+Switch\s+\d+$",
        r"\s+Input\s+\d+$",
        r"\s+Relay\s+\d+$",
        r"\s+Light\s+\d+$",
        r"\s+Cover\s+\d+$",
    ]
    changed = True
    while changed:
        changed = False
        for pattern in patterns:
            new = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()
            if new != cleaned:
                cleaned = new
                changed = True

    return cleaned or str(name).strip()


def _best_shelly_group_name(names: list[str]) -> str:
    """
    Pick a stable human-friendly name for one physical Shelly.

    Prefer a cleaned name that already exists as a device name, then the
    shortest cleaned name. This makes:
      Shelly_Verdichter
      Shelly_Verdichter Energy Meter 0
      Shelly_Verdichter Energy Meter 1
    become:
      Shelly_Verdichter
    """
    original = [str(n).strip() for n in names if str(n).strip()]
    if not original:
        return "Unknown Shelly"

    cleaned = [_clean_shelly_name(n) for n in original]

    # Prefer a cleaned value that is also present verbatim among the HA names.
    verbatim = [c for c in cleaned if c in original]
    if verbatim:
        return sorted(verbatim, key=lambda x: (len(x), x.lower()))[0]

    # Otherwise prefer the shortest cleaned name.
    return sorted(cleaned, key=lambda x: (len(x), x.lower()))[0]


def discover_shelly_devices() -> list[Dict[str, str]]:
    with HAWebSocket() as ha:
        entries = ha.call({"type": "config_entries/get", "domain": "shelly"}) or []
        shelly_entry_ids = {
            str(e.get("entry_id"))
            for e in entries
            if e.get("entry_id")
        }

        devices = ha.call({"type": "config/device_registry/list"}) or []

    # Group by network host/IP, not by Home Assistant device_id.
    # A multi-channel Shelly may expose several HA Device Registry entries
    # (Output 0, Output 1, Energy Meter 0, ...), but they are one physical host.
    groups: Dict[str, Dict[str, Any]] = {}

    for device in devices:
        entry_id = device.get("config_entry_id")
        legacy_entries = set(device.get("config_entries") or [])
        if entry_id not in shelly_entry_ids and not (legacy_entries & shelly_entry_ids):
            continue

        config_url = str(device.get("configuration_url") or "")
        if not config_url:
            # Child devices often lack an address. They do not need their own
            # ping monitor and are intentionally skipped here.
            continue

        parsed = urlparse(config_url)
        host = parsed.hostname
        if not host:
            LOG.warning(
                "Shelly device '%s' has unusable configuration_url: %s",
                device.get("name_by_user") or device.get("name") or device.get("id"),
                config_url,
            )
            continue

        host_key = str(host).strip().lower()
        if not host_key:
            continue

        raw_name = (
            device.get("name_by_user")
            or device.get("name")
            or device.get("model")
            or device.get("id")
            or host
        )

        group = groups.setdefault(
            host_key,
            {
                "host": str(host),
                "names": [],
                "device_ids": [],
                "configuration_urls": [],
            },
        )

        group["names"].append(str(raw_name))
        if device.get("id"):
            group["device_ids"].append(str(device["id"]))
        if config_url:
            group["configuration_urls"].append(config_url)

    result = []
    for host_key, group in sorted(groups.items()):
        name = _best_shelly_group_name(group["names"])
        device_ids = sorted(set(group["device_ids"]))

        if len(set(group["names"])) > 1:
            LOG.info(
                "Collapsed %d Shelly registry entries on %s into one monitor '%s': %s",
                len(set(group["names"])),
                group["host"],
                name,
                ", ".join(sorted(set(group["names"]))),
            )

        result.append({
            # Use host as the physical-device identity for ping monitoring.
            "device_id": f"host:{host_key}",
            "source_device_ids": ",".join(device_ids),
            "name": name,
            "host": group["host"],
            "configuration_url": (
                sorted(set(group["configuration_urls"]))[0]
                if group["configuration_urls"]
                else ""
            ),
        })

    return result

def sync_addons(opts, api, monitors, default_notification_ids, state):
    addons = supervisor_get("/addons") or {}
    addon_list = addons.get("addons", addons if isinstance(addons, list) else [])

    discovered = []
    for addon in addon_list:
        slug = str(addon.get("slug", ""))
        name = str(addon.get("name", slug))
        if not slug:
            continue
        if slug in opts["ignore_slugs_set"]:
            LOG.info("Ignoring %s (%s)", name, slug)
            continue
        if slug.endswith("_ha_kuma_discovery") or name == "HA Kuma Discovery":
            continue
        discovered.append(addon)

    LOG.info("Supervisor returned %d monitored add-ons", len(discovered))

    for addon in discovered:
        slug = addon["slug"]
        name = addon.get("name") or slug
        status = str(addon.get("state") or "unknown").lower()
        monitor_name = f'{opts["monitor_prefix"]}{name}'

        monitor = ensure_push_monitor(
            api, monitors, monitor_name,
            opts["heartbeat_interval"], default_notification_ids,
            state=state, identity=f'addon:{slug}',
        )

        up = status == "started"
        push_status_if_needed(
            opts["kuma_url"], monitor, up,
            f"Supervisor state: {status} | slug: {slug}",
            opts["verify_ssl"],
            state,
            opts["heartbeat_interval"],
            opts["sync_interval"],
        )
        LOG.info("%s (%s) -> %s", monitor_name, slug, "UP" if up else "DOWN")

    state["known_slugs"] = sorted(a["slug"] for a in discovered)
    state["names"] = {a["slug"]: (a.get("name") or a["slug"]) for a in discovered}


def sync_shelly(opts, api, monitors, default_notification_ids, state):
    shellys = discover_shelly_devices()
    LOG.info("Home Assistant returned %d Shelly device(s) with an address", len(shellys))

    for device in shellys:
        monitor_name = f'{opts["shelly_monitor_prefix"]}{device["name"]}'
        ensure_ping_monitor(
            api,
            monitors,
            monitor_name,
            device["host"],
            opts["shelly_ping_interval"],
            opts["shelly_max_retries"],
            default_notification_ids,
            state=state,
            identity=f'shelly:{device["device_id"]}',
        )
        LOG.info(
            "%s -> PING %s (device_id=%s)",
            monitor_name,
            device["host"],
            device["device_id"],
        )

    state["known_shelly_device_ids"] = sorted(d["device_id"] for d in shellys)
    state["shelly_devices"] = {
        d["device_id"]: {
            "name": d["name"],
            "host": d["host"],
        }
        for d in shellys
    }



def _entity_domain(entity_id: str) -> str:
    return str(entity_id).split(".", 1)[0] if "." in str(entity_id) else ""


def _state_ip(attributes: Dict[str, Any]) -> str | None:
    """
    Try common Home Assistant attributes used for network-device addresses.
    """
    for key in ("ip", "ip_address", "host", "address"):
        value = attributes.get(key)
        if not value:
            continue
        value = str(value).strip()

        # Strip URL/port if a host-like attribute happens to contain one.
        if "://" in value:
            try:
                parsed = urlparse(value)
                value = parsed.hostname or ""
            except Exception:
                pass

        # A normal IPv4/IPv6/hostname is fine; ignore obvious MAC addresses.
        if value and not re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", value):
            return value
    return None


def _normalize_mac(value: str) -> str:
    return re.sub(r"[^0-9a-f]", "", str(value).lower())


def _device_mac_from_registry(device: Dict[str, Any]) -> str | None:
    for connection in device.get("connections") or []:
        if not isinstance(connection, (list, tuple)) or len(connection) != 2:
            continue
        connection_type, value = connection
        if str(connection_type).lower() == "mac" and value:
            return _normalize_mac(str(value))
    return None


def _looks_like_mac_name(value: str) -> bool:
    value = str(value or "").strip()
    if not value:
        return False
    return bool(
        re.fullmatch(r"(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}", value)
        or re.fullmatch(r"[0-9A-Fa-f]{12}", value)
    )


def _generic_unifi_name(value: str) -> bool:
    value = str(value or "").strip().lower()
    return value in {
        "",
        "firmware",
        "firmware update",
        "update",
        "device update",
        "unifi device update",
        "network device",
    }


def _clean_unifi_friendly_name(value: str) -> str:
    value = str(value or "").strip()
    value = re.sub(
        r"\s+(?:Firmware|Firmware Update|Update|State|Zustand)$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    return value


def _strip_unifi_entity_suffix(value: str) -> str:
    value = str(value or "").strip()

    # Only strip suffixes from infrastructure status sensors we explicitly use
    # as a fallback. Do not use action-button names such as "Neu starten".
    suffixes = [
        r"\s+State$",
        r"\s+Zustand$",
        r"\s+Uptime$",
        r"\s+Betriebszeit$",
        r"\s+Clients$",
        r"\s+CPU Utilization$",
        r"\s+CPU Auslastung$",
        r"\s+Memory Utilization$",
        r"\s+Speicherauslastung$",
        r"\s+Temperature$",
        r"\s+Temperatur$",
    ]
    changed = True
    while changed:
        changed = False
        for pattern in suffixes:
            new = re.sub(pattern, "", value, flags=re.IGNORECASE).strip()
            if new != value:
                value = new
                changed = True
    return value


def _best_unifi_device_name(
    device: Dict[str, Any],
    device_entities: list[Dict[str, Any]],
    state_by_entity: Dict[str, Dict[str, Any]],
) -> str:
    """
    Choose the managed UniFi device's actual HA name.

    Priority:
      1. HA device-registry user name / device name
      2. friendly_name from infrastructure status sensors only
      3. model

    Button/action friendly names (e.g. '<MAC> Neu starten') and generic update
    labels are never used as monitor names.
    """
    # 1) Device registry is authoritative and gave the correct names in the
    #    UniFi discovery logs (Core, USW-Flex-..., U6-Pro-..., UCG Fiber, ...).
    for key in ("name_by_user", "name"):
        candidate = str(device.get(key) or "").strip()
        if not candidate:
            continue
        candidate = _clean_unifi_friendly_name(candidate)
        if candidate and not _looks_like_mac_name(candidate) and not _generic_unifi_name(candidate):
            return candidate

    # 2) Only use stable status/sensor entities as fallback. Never buttons,
    #    update entities, lights or port switches.
    preferred_sensor_suffixes = (
        "_state", "_zustand", "_uptime", "_betriebszeit",
        "_clients", "_cpu_utilization", "_cpu_auslastung",
        "_memory_utilization", "_speicherauslastung",
    )

    for entity in device_entities:
        entity_id = str(entity.get("entity_id") or "")
        if not entity_id.startswith("sensor."):
            continue
        if not entity_id.endswith(preferred_sensor_suffixes):
            continue

        state = state_by_entity.get(entity_id)
        if not state:
            continue
        friendly = str((state.get("attributes") or {}).get("friendly_name") or "").strip()
        if not friendly:
            continue

        candidate = _strip_unifi_entity_suffix(friendly)
        candidate = _clean_unifi_friendly_name(candidate)
        if candidate and not _looks_like_mac_name(candidate) and not _generic_unifi_name(candidate):
            return candidate

    # 3) Stable final fallback.
    return str(device.get("model") or device.get("id") or "UniFi Device")

def _is_private_or_local_host(host: str) -> bool:
    """
    UniFi infrastructure management addresses should normally be LAN addresses.
    Hostnames are accepted. Literal public IP addresses are rejected so a
    gateway's WAN IP is not accidentally monitored instead of its management IP.
    """
    host = str(host or "").strip()
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local)


def _unifi_config_entry_hosts_from_storage(
    allowed_entry_ids: set[str],
) -> Dict[str, str]:
    """
    Read only the UniFi config-entry host from Home Assistant's local storage.

    The WebSocket config_entries/get response intentionally does not expose the
    integration's private `data` mapping, so the controller host is not present
    there. The add-on mounts Home Assistant's config read-only at /homeassistant
    and reads only data.host for matching UniFi entries.
    """
    hosts: Dict[str, str] = {}
    if not allowed_entry_ids:
        return hosts

    if not HA_CONFIG_ENTRIES.exists():
        LOG.warning(
            "Home Assistant config-entry storage is not mounted at %s; "
            "Cloud Gateway local-host fallback is unavailable.",
            HA_CONFIG_ENTRIES,
        )
        return hosts

    try:
        raw = json.loads(HA_CONFIG_ENTRIES.read_text(encoding="utf-8"))
    except Exception as exc:
        LOG.warning(
            "Could not read Home Assistant config-entry storage for UniFi host lookup: %s",
            exc,
        )
        return hosts

    for entry in (raw.get("data") or {}).get("entries") or []:
        if str(entry.get("domain") or "") != "unifi":
            continue

        entry_id = str(entry.get("entry_id") or "")
        if not entry_id or entry_id not in allowed_entry_ids:
            continue

        host = str((entry.get("data") or {}).get("host") or "").strip()
        if host:
            hosts[entry_id] = host

    if hosts:
        LOG.info(
            "Loaded local UniFi config-entry host(s) for %d integration entr%s",
            len(hosts),
            "y" if len(hosts) == 1 else "ies",
        )

    return hosts


def discover_unifi_network_devices() -> list[Dict[str, str]]:
    """
    Discover only UniFi infrastructure devices (gateway, switches, APs), not clients.

    Home Assistant's UniFi integration can create dedicated Device Tracker entities
    for UniFi network devices when "Track network devices" is enabled. Those
    trackers expose the device IP address, but they are intentionally not linked
    to the normal HA device-registry entry. Their unique_id is the UniFi device MAC.

    We therefore:
      1. identify infrastructure devices by their firmware update entity;
      2. read the physical device MAC from the HA device registry;
      3. map that MAC to the UniFi Device Tracker entity;
      4. read the tracker's live `ip` attribute.
    """
    with HAWebSocket() as ha:
        entries = ha.call({"type": "config_entries/get", "domain": "unifi"}) or []
        unifi_entry_ids = {
            str(e.get("entry_id"))
            for e in entries
            if e.get("entry_id")
        }

        # The WebSocket entry list normally omits private config-entry data such
        # as the UniFi host. Read the matching host from HA storage instead.
        unifi_entry_hosts = _unifi_config_entry_hosts_from_storage(unifi_entry_ids)

        # Keep compatibility in case a future HA version exposes data.host here.
        for entry in entries:
            entry_id = str(entry.get("entry_id") or "")
            data = entry.get("data") or {}
            host = str(data.get("host") or "").strip()
            if entry_id and host:
                unifi_entry_hosts.setdefault(entry_id, host)

        devices = ha.call({"type": "config/device_registry/list"}) or []
        entities = ha.call({"type": "config/entity_registry/list"}) or []
        states = ha.call({"type": "get_states"}) or []

    if not unifi_entry_ids:
        LOG.info("No UniFi Network config entry found")
        return []

    state_by_entity = {
        str(s.get("entity_id")): s
        for s in states
        if s.get("entity_id")
    }

    entities_by_device: Dict[str, list[Dict[str, Any]]] = {}
    tracker_by_mac: Dict[str, Dict[str, Any]] = {}

    for entity in entities:
        entry_id = entity.get("config_entry_id")
        legacy_entries = set(entity.get("config_entry_ids") or [])
        if entry_id not in unifi_entry_ids and not (legacy_entries & unifi_entry_ids):
            continue

        device_id = entity.get("device_id")
        if device_id:
            entities_by_device.setdefault(str(device_id), []).append(entity)

        entity_id = str(entity.get("entity_id") or "")
        if _entity_domain(entity_id) != "device_tracker":
            continue

        unique_id = str(entity.get("unique_id") or "")
        mac_key = _normalize_mac(unique_id)
        if len(mac_key) != 12:
            continue

        state = state_by_entity.get(entity_id)
        if not state:
            continue

        attrs = state.get("attributes") or {}
        host = _state_ip(attrs)
        if not host:
            continue

        tracker_by_mac[mac_key] = {
            "entity_id": entity_id,
            "host": host,
            "state": str(state.get("state") or ""),
            "friendly_name": str(
                entity.get("name")
                or entity.get("original_name")
                or ""
            ).strip(),
        }

    result = []

    for device in devices:
        device_id = str(device.get("id") or "")
        if not device_id:
            continue

        entry_id = device.get("config_entry_id")
        legacy_entries = set(device.get("config_entries") or [])
        if entry_id not in unifi_entry_ids and not (legacy_entries & unifi_entry_ids):
            if device_id not in entities_by_device:
                continue

        device_entities = entities_by_device.get(device_id, [])

        # Managed UniFi infrastructure has firmware-update entities; ordinary
        # network clients do not.
        update_entities = [
            e for e in device_entities
            if _entity_domain(e.get("entity_id", "")) == "update"
        ]
        if not update_entities:
            continue

        host = None
        source = None

        # First use any IP attributes directly exposed by a device entity.
        for entity in device_entities:
            state = state_by_entity.get(str(entity.get("entity_id") or ""))
            if not state:
                continue
            host = _state_ip(state.get("attributes") or {})
            if host:
                source = str(entity.get("entity_id") or "")
                break

        # Normal case for UniFi infrastructure: resolve MAC -> UniFi Device Tracker.
        if not host:
            mac_key = _device_mac_from_registry(device)
            tracker = tracker_by_mac.get(mac_key or "")
            if tracker:
                host = tracker["host"]
                source = tracker["entity_id"]

        tracker_name = ""
        mac_key = _device_mac_from_registry(device)
        if mac_key:
            tracker = tracker_by_mac.get(mac_key)
            if tracker:
                tracker_name = str(tracker.get("friendly_name") or "").strip()

        if tracker_name and not _looks_like_mac_name(tracker_name) and not _generic_unifi_name(tracker_name):
            name = tracker_name
        else:
            name = _best_unifi_device_name(device, device_entities, state_by_entity)

        if not host:
            mac_key = _device_mac_from_registry(device)
            LOG.warning(
                "UniFi infrastructure device '%s' (%s) has no usable IP. "
                "MAC=%s. Enable 'Track network devices' in the Home Assistant "
                "UniFi Network integration so HA creates device_tracker entities.",
                name,
                device.get("model") or "unknown model",
                mac_key or "unknown",
            )
            continue

        if not _is_private_or_local_host(host):
            # Cloud Gateways may expose their WAN IP through the UniFi device
            # tracker. In that case, use the Home Assistant UniFi config-entry
            # host, which is the controller/gateway's local management address.
            entry_candidates = []
            primary_entry = str(
                device.get("primary_config_entry")
                or device.get("config_entry_id")
                or ""
            )
            if primary_entry:
                entry_candidates.append(primary_entry)
            for eid in device.get("config_entries") or []:
                if str(eid) not in entry_candidates:
                    entry_candidates.append(str(eid))

            fallback_host = None
            for eid in entry_candidates:
                candidate = str(unifi_entry_hosts.get(eid) or "").strip()
                if candidate and _is_private_or_local_host(candidate):
                    fallback_host = candidate
                    break

            if fallback_host:
                LOG.info(
                    "UniFi infrastructure device '%s' (%s) exposed public tracker IP %s; "
                    "using local UniFi config-entry host %s instead.",
                    name,
                    device.get("model") or "unknown model",
                    host,
                    fallback_host,
                )
                host = fallback_host
                source = "unifi_config_entry.host"
            else:
                LOG.warning(
                    "UniFi infrastructure device '%s' (%s) resolved to public IP %s "
                    "via %s and no private/local UniFi config-entry host was available; skipping.",
                    name,
                    device.get("model") or "unknown model",
                    host,
                    source or "unknown source",
                )
                continue

        result.append({
            "device_id": device_id,
            "name": str(name),
            "host": str(host),
            "model": str(device.get("model") or ""),
            "manufacturer": str(device.get("manufacturer") or ""),
            "ip_source": source or "",
        })

    # Dedupe by host in case HA exposes multiple registry representations for
    # one physical UniFi device.
    grouped: Dict[str, Dict[str, str]] = {}
    for device in result:
        key = device["host"].strip().lower()
        if key not in grouped:
            grouped[key] = device
            continue

        current = grouped[key]
        if len(device["name"]) < len(current["name"]):
            grouped[key] = device

    devices_out = sorted(grouped.values(), key=lambda d: d["name"].lower())

    # Ensure different physical devices never collapse into the same Kuma monitor
    # merely because HA returned the same generic/friendly name.
    name_counts = {}
    for item in devices_out:
        name_counts[item["name"]] = name_counts.get(item["name"], 0) + 1

    for item in devices_out:
        if name_counts.get(item["name"], 0) > 1:
            item["name"] = f'{item["name"]} ({item["host"]})'

    return devices_out


def _config_entry_hosts_from_storage(
    domain: str,
    allowed_entry_ids: set[str],
) -> Dict[str, str]:
    """Return config-entry data.host values for a specific HA integration."""
    hosts: Dict[str, str] = {}
    if not allowed_entry_ids:
        return hosts

    if not HA_CONFIG_ENTRIES.exists():
        LOG.warning(
            "Home Assistant config-entry storage is not mounted at %s; "
            "%s host discovery is unavailable.",
            HA_CONFIG_ENTRIES,
            domain,
        )
        return hosts

    try:
        raw = json.loads(HA_CONFIG_ENTRIES.read_text(encoding="utf-8"))
    except Exception as exc:
        LOG.warning("Could not read Home Assistant config-entry storage: %s", exc)
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


def _device_has_identifier(device: Dict[str, Any], identifier_type: str) -> bool:
    for identifier in device.get("identifiers") or []:
        if (
            isinstance(identifier, (list, tuple))
            and len(identifier) >= 2
            and str(identifier[0]).lower() == identifier_type.lower()
        ):
            return True
    return False


def discover_fritz_network_devices() -> list[Dict[str, str]]:
    """
    Discover only AVM FRITZ! network infrastructure from the FRITZ!Box Tools
    (`fritz`) integration.

    Intentionally included:
      - FRITZ!Box
      - FRITZ!Repeater
      - FRITZ!Powerline

    Intentionally excluded:
      - FRITZ!DECT / FRITZ!Smart Energy
      - client devices learned by the router
      - call monitor devices
      - UPnP duplicates
      - groups / smart-home devices

    FRITZ!Box Tools does not create device_tracker entities for the router
    itself in this installation, so the integration's config-entry host is used
    as the ping address.
    """
    with HAWebSocket() as ha:
        entries = ha.call({"type": "config_entries/get", "domain": "fritz"}) or []
        fritz_entry_ids = {
            str(e.get("entry_id"))
            for e in entries
            if e.get("entry_id")
        }
        devices = ha.call({"type": "config/device_registry/list"}) or []

    if not fritz_entry_ids:
        LOG.info("No FRITZ!Box Tools config entry found")
        return []

    fritz_entry_hosts = _config_entry_hosts_from_storage("fritz", fritz_entry_ids)

    # Compatibility with a future HA version that might expose data.host here.
    for entry in entries:
        entry_id = str(entry.get("entry_id") or "")
        host = str((entry.get("data") or {}).get("host") or "").strip()
        if entry_id and host:
            fritz_entry_hosts.setdefault(entry_id, host)

    allowed_model_prefixes = (
        "fritz!box",
        "fritz!repeater",
        "fritz!powerline",
    )

    candidates = []
    for device in devices:
        entry_id = str(device.get("config_entry_id") or "")
        legacy_entries = {str(x) for x in (device.get("config_entries") or [])}

        matching_entries = []
        if entry_id in fritz_entry_ids:
            matching_entries.append(entry_id)
        matching_entries.extend(
            sorted((legacy_entries & fritz_entry_ids) - set(matching_entries))
        )
        if not matching_entries:
            continue

        model = str(device.get("model") or "").strip()
        if not model.lower().startswith(allowed_model_prefixes):
            continue

        # Prefer the native FRITZ integration representation. This excludes
        # UPnP-only duplicates and other representations of the same router.
        if not _device_has_identifier(device, "fritz"):
            continue

        host = None
        source_entry = None
        for eid in matching_entries:
            candidate = str(fritz_entry_hosts.get(eid) or "").strip()
            if candidate and _is_private_or_local_host(candidate):
                host = candidate
                source_entry = eid
                break

        if not host:
            LOG.warning(
                "FRITZ! network device '%s' (%s) has no private/local host in "
                "its FRITZ!Box Tools config entry; skipping.",
                device.get("name_by_user") or device.get("name") or model,
                model or "unknown model",
            )
            continue

        name = str(
            device.get("name_by_user")
            or device.get("name")
            or model
            or "FRITZ! network device"
        ).strip()

        mac = _device_mac_from_registry(device) or ""
        candidates.append({
            "device_id": str(device.get("id") or ""),
            "name": name,
            "host": host,
            "model": model,
            "mac": mac,
            "source": f"fritz_config_entry.host:{source_entry}",
        })

    # Deduplicate physical infrastructure. Prefer MAC where available; otherwise
    # host+model. This prevents duplicate FRITZ!Box registry representations.
    deduped: Dict[str, Dict[str, str]] = {}
    for item in candidates:
        key = (
            f"mac:{item['mac']}"
            if item.get("mac")
            else f"host:{item['host']}|model:{item['model'].lower()}"
        )
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = item
            continue

        # Prefer the more explicit/human-friendly name.
        old_name = existing.get("name", "")
        new_name = item.get("name", "")
        if new_name.lower().startswith("fritz!") and not old_name.lower().startswith("fritz!"):
            deduped[key] = item

    return sorted(deduped.values(), key=lambda d: d["name"].lower())



def _clean_fully_name(value: str) -> str:
    value = str(value or "").strip().replace("_", " ")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def discover_fully_kiosk_devices() -> list[Dict[str, str]]:
    """
    Discover only devices belonging to the Home Assistant Fully Kiosk Browser
    integration and create one ping target per configured Fully host.

    The config entry is the source of truth for the device IP/host. Device
    registry metadata and HA areas are used only to build a friendly unique name.
    """
    with HAWebSocket() as ha:
        entries = ha.call({"type": "config_entries/get", "domain": "fully_kiosk"}) or []
        devices = ha.call({"type": "config/device_registry/list"}) or []
        try:
            areas = ha.call({"type": "config/area_registry/list"}) or []
        except Exception:
            areas = []

    if not entries:
        LOG.info("No Fully Kiosk Browser config entry found")
        return []

    entry_ids = {str(e.get("entry_id")) for e in entries if e.get("entry_id")}
    entry_hosts = _config_entry_hosts_from_storage("fully_kiosk", entry_ids)

    # Compatibility if HA ever exposes the host via the WS config-entry result.
    for entry in entries:
        eid = str(entry.get("entry_id") or "")
        host = str((entry.get("data") or {}).get("host") or "").strip()
        if eid and host:
            entry_hosts.setdefault(eid, host)

    area_names = {
        str(a.get("area_id")): str(a.get("name") or "").strip()
        for a in areas
        if a.get("area_id")
    }

    device_by_entry: Dict[str, Dict[str, Any]] = {}
    for device in devices:
        eid = str(device.get("config_entry_id") or "")
        if eid in entry_ids:
            device_by_entry[eid] = device
            continue

        legacy = {str(x) for x in (device.get("config_entries") or [])}
        for match in sorted(legacy & entry_ids):
            device_by_entry.setdefault(match, device)

    result = []
    for entry in entries:
        eid = str(entry.get("entry_id") or "")
        if not eid:
            continue

        host = str(entry_hosts.get(eid) or "").strip()
        if not host:
            LOG.warning(
                "Fully Kiosk config entry '%s' has no usable host; skipping.",
                entry.get("title") or eid,
            )
            continue

        device = device_by_entry.get(eid) or {}
        entry_title = _clean_fully_name(entry.get("title") or "")
        device_name = _clean_fully_name(
            device.get("name_by_user")
            or device.get("name")
            or ""
        )
        model = _clean_fully_name(device.get("model") or "")
        area_name = _clean_fully_name(area_names.get(str(device.get("area_id") or ""), ""))

        # Prefer the HA device name because users often rename Fully devices
        # there (e.g. "Tablet Arbeitszimmer"). Otherwise use the config-entry title.
        name = device_name or entry_title or model or host

        # When the visible device name is generic or duplicated, area names give
        # useful stable differentiation such as "Fire Tablet Wohnzimmer/Flur".
        if area_name and area_name.lower() not in name.lower():
            name = f"{name} {area_name}"

        result.append({
            "device_id": str(device.get("id") or eid),
            "entry_id": eid,
            "name": name,
            "host": host,
            "model": model,
            "area": area_name,
        })

    # Make any remaining duplicate names unique. Prefer area, then model, then IP.
    name_groups: Dict[str, list[Dict[str, str]]] = {}
    for item in result:
        name_groups.setdefault(item["name"].lower(), []).append(item)

    for group in name_groups.values():
        if len(group) <= 1:
            continue
        for item in group:
            suffix = item.get("area") or item.get("model") or item.get("host")
            if suffix and suffix.lower() not in item["name"].lower():
                item["name"] = f'{item["name"]} {suffix}'
            elif item.get("host"):
                item["name"] = f'{item["name"]} ({item["host"]})'

    # Host is the physical network identity. One Fully monitor per tablet.
    deduped: Dict[str, Dict[str, str]] = {}
    for item in result:
        deduped.setdefault(item["host"].lower(), item)

    return sorted(deduped.values(), key=lambda d: d["name"].lower())



def discover_homematic_ip_infrastructure() -> Dict[str, Any]:
    """Discover the HCU Ping target and native physical Connectivity devices."""
    with HAWebSocket() as ha:
        entries = ha.call({"type": "config_entries/get", "domain": "hcu_integration"}) or []
        devices = ha.call({"type": "config/device_registry/list"}) or []
        entities = ha.call({"type": "config/entity_registry/list"}) or []
        states = ha.call({"type": "get_states"}) or []

    entry_ids = {str(e.get("entry_id")) for e in entries if e.get("entry_id")}
    if not entry_ids:
        LOG.info("No Homematic IP HCU integration config entry found")
        return {}

    entry_hosts = _config_entry_hosts_from_storage("hcu_integration", entry_ids)
    for entry in entries:
        eid = str(entry.get("entry_id") or "")
        host = str((entry.get("data") or {}).get("host") or "").strip()
        if eid and host:
            entry_hosts.setdefault(eid, host)

    state_by_entity = {
        str(s.get("entity_id")): s for s in states if s.get("entity_id")
    }

    entities_by_device: Dict[str, list[Dict[str, Any]]] = {}
    for entity in entities:
        eid = str(entity.get("config_entry_id") or "")
        if eid not in entry_ids or entity.get("platform") != "hcu_integration":
            continue
        did = str(entity.get("device_id") or "")
        if did:
            entities_by_device.setdefault(did, []).append(entity)

    hcu = None
    connectivity_devices = []
    seen_devices = set()

    for device in devices:
        eid = str(device.get("config_entry_id") or "")
        legacy = {str(x) for x in (device.get("config_entries") or [])}
        matching = []
        if eid in entry_ids:
            matching.append(eid)
        matching.extend(sorted((legacy & entry_ids) - set(matching)))
        if not matching:
            continue

        model = str(device.get("model") or "").strip()
        did = str(device.get("id") or "")
        name = str(device.get("name_by_user") or device.get("name") or model).strip()

        if not did or did in seen_devices or device.get("disabled_by") is not None:
            continue
        if not _device_has_identifier(device, "hcu_integration"):
            continue
        seen_devices.add(did)

        if model in {"HmIP-HCU1", "HmIP-HCU-1", "HmIP-HCU1-A"}:
            host = None
            source_entry = None
            for candidate_eid in matching:
                candidate = str(entry_hosts.get(candidate_eid) or "").strip()
                if candidate and _is_private_or_local_host(candidate):
                    host = candidate
                    source_entry = candidate_eid
                    break
            if host:
                hcu = {
                    "device_id": did,
                    "name": "HCU",
                    "host": host,
                    "model": model,
                    "source": f"hcu_integration.config_entry.host:{source_entry}",
                }
            else:
                LOG.warning("Homematic IP HCU '%s' has no usable local host", name)

        else:
            # HCU physical models and native registry identifiers are positive
            # evidence of hardware. Groups/services and virtual models are not.
            if device.get("entry_type") is not None:
                continue
            if not model.lower().startswith(("hmip-", "hmipw-", "hm-", "alpha-", "elv")):
                continue
            if any(word in model.lower() for word in ("virtual", "logical", "group", "room", "helper")):
                continue

            candidates = []
            for entity in entities_by_device.get(did, []):
                entity_id = str(entity.get("entity_id") or "")
                if entity.get("disabled_by") is not None or not entity_id.startswith("binary_sensor."):
                    continue
                current = state_by_entity.get(entity_id) or {}
                attributes = current.get("attributes") or {}
                if attributes.get("is_group"):
                    continue
                unique_id = str(entity.get("unique_id") or "").lower()
                native_unreach = unique_id.endswith("_unreach")
                device_class = (entity.get("original_device_class")
                                or attributes.get("device_class"))
                if native_unreach or device_class == "connectivity":
                    candidates.append((not native_unreach, unique_id, entity_id, current))

            if not candidates:
                LOG.info("Skipping Homematic IP device '%s': no enabled Connectivity entity", name)
                continue
            # Prefer the integration's native unreach feature; select exactly
            # one deterministically even if multiple channel entities exist.
            _, _, connectivity, current = min(candidates, key=lambda item: item[:3])
            connectivity_devices.append({
                "device_id": did,
                "name": name or model,
                "model": model,
                "connectivity_entity": connectivity,
                "state": str(current.get("state") or "unknown").lower(),
            })

    return {
        "hcu": hcu,
        "devices": connectivity_devices,
    }



def discover_matter_devices() -> list[Dict[str, Any]]:
    """
    Discover physical devices belonging to Home Assistant's Matter integration.

    Matter/Thread devices are not suitable for generic ICMP monitoring:
    battery-powered Thread nodes may sleep and many devices expose no stable
    IPv4/IPv6 address. We therefore monitor Home Assistant/Matter availability
    instead of pinging the device.

    A Matter device is considered UP when at least one enabled, stateful Matter
    entity is currently available. It is DOWN when all suitable enabled entities
    are unavailable/unknown or no suitable active Matter entity exists.
    """
    with HAWebSocket() as ha:
        entries = ha.call({"type": "config_entries/get", "domain": "matter"}) or []
        devices = ha.call({"type": "config/device_registry/list"}) or []
        entities = ha.call({"type": "config/entity_registry/list"}) or []
        states = ha.call({"type": "get_states"}) or []

    matter_entry_ids = {
        str(e.get("entry_id"))
        for e in entries
        if e.get("entry_id")
    }
    if not matter_entry_ids:
        LOG.info("No Matter integration config entry found")
        return []

    state_by_entity = {
        str(s.get("entity_id")): s
        for s in states
        if s.get("entity_id")
    }

    entities_by_device: Dict[str, list[Dict[str, Any]]] = {}
    for entity in entities:
        if str(entity.get("platform") or "") != "matter":
            continue

        entry_id = str(entity.get("config_entry_id") or "")
        legacy_entries = {str(x) for x in (entity.get("config_entry_ids") or [])}
        if entry_id not in matter_entry_ids and not (legacy_entries & matter_entry_ids):
            continue

        device_id = str(entity.get("device_id") or "")
        if device_id:
            entities_by_device.setdefault(device_id, []).append(entity)

    # Domains whose state is useful for determining whether a Matter node is
    # currently available. Buttons are often "unknown" even when a node is fine.
    stateful_domains = {
        "binary_sensor",
        "sensor",
        "switch",
        "light",
        "lock",
        "climate",
        "cover",
        "select",
        "number",
        "fan",
        "valve",
    }

    result = []

    for device in devices:
        device_id = str(device.get("id") or "")
        if not device_id:
            continue

        entry_id = str(device.get("config_entry_id") or "")
        legacy_entries = {str(x) for x in (device.get("config_entries") or [])}
        if entry_id not in matter_entry_ids and not (legacy_entries & matter_entry_ids):
            continue

        # Extra guard: native Matter devices carry at least one "matter"
        # identifier. This avoids unrelated devices sharing a config entry.
        has_matter_identifier = any(
            isinstance(i, (list, tuple))
            and len(i) >= 2
            and str(i[0]).lower() == "matter"
            for i in (device.get("identifiers") or [])
        )
        if not has_matter_identifier:
            continue

        candidates = []
        for entity in entities_by_device.get(device_id, []):
            if entity.get("disabled_by") is not None:
                continue

            entity_id = str(entity.get("entity_id") or "")
            domain = _entity_domain(entity_id)
            if domain not in stateful_domains:
                continue

            current = state_by_entity.get(entity_id)
            if not current:
                continue

            current_state = str(current.get("state") or "").lower()
            candidates.append({
                "entity_id": entity_id,
                "state": current_state,
                "domain": domain,
            })

        available = [
            c for c in candidates
            if c["state"] not in ("unavailable", "unknown", "")
        ]

        name = str(
            device.get("name_by_user")
            or device.get("name")
            or device.get("model")
            or device_id
        ).strip()

        result.append({
            "device_id": device_id,
            "name": name,
            "manufacturer": str(device.get("manufacturer") or "").strip(),
            "model": str(device.get("model") or "").strip(),
            "up": bool(available),
            "available_entities": len(available),
            "checked_entities": len(candidates),
            "sample_entity": (
                available[0]["entity_id"]
                if available
                else (candidates[0]["entity_id"] if candidates else "")
            ),
        })

    return sorted(result, key=lambda d: d["name"].lower())



def discover_e3dc_devices() -> list[Dict[str, str]]:
    """
    Discover only the physical E3/DC system from the native/custom `e3dc_rscp`
    integration. Battery packs/modules exposed as child devices are ignored.

    The integration config-entry host is used directly as the ping target, so
    there is no dependency on UniFi, FRITZ!Box or any other network integration.
    """
    with HAWebSocket() as ha:
        entries = ha.call({"type": "config_entries/get", "domain": "e3dc_rscp"}) or []
        devices = ha.call({"type": "config/device_registry/list"}) or []

    entry_ids = {str(e.get("entry_id")) for e in entries if e.get("entry_id")}
    if not entry_ids:
        LOG.info("No E3/DC RSCP config entry found")
        return []

    entry_hosts = _config_entry_hosts_from_storage("e3dc_rscp", entry_ids)
    for entry in entries:
        eid = str(entry.get("entry_id") or "")
        host = str((entry.get("data") or {}).get("host") or "").strip()
        if eid and host:
            entry_hosts.setdefault(eid, host)

    result = []

    for device in devices:
        eid = str(device.get("config_entry_id") or "")
        legacy = {str(x) for x in (device.get("config_entries") or [])}
        matching = []
        if eid in entry_ids:
            matching.append(eid)
        matching.extend(sorted((legacy & entry_ids) - set(matching)))
        if not matching:
            continue

        # Only monitor the physical E3/DC controller.
        #
        # Battery packs/modules also carry e3dc_rscp identifiers, so the
        # identifier alone is not enough. The physical controller is the
        # top-level device and exposes a real MAC connection; child battery
        # devices do not.
        identifiers = device.get("identifiers") or []
        native_ids = [
            str(i[1])
            for i in identifiers
            if isinstance(i, (list, tuple))
            and len(i) >= 2
            and str(i[0]).lower() == "e3dc_rscp"
        ]
        if not native_ids:
            continue

        has_mac = any(
            isinstance(c, (list, tuple))
            and len(c) >= 2
            and str(c[0]).lower() == "mac"
            for c in (device.get("connections") or [])
        )
        if not has_mac:
            continue

        # Child devices such as battery packs/modules are linked via the main
        # E3/DC device. Exclude them even if a future integration version adds
        # extra connection metadata.
        if device.get("via_device_id"):
            continue

        host = None
        source_entry = None
        for candidate_eid in matching:
            candidate = str(entry_hosts.get(candidate_eid) or "").strip()
            if candidate and _is_private_or_local_host(candidate):
                host = candidate
                source_entry = candidate_eid
                break

        if not host:
            LOG.warning(
                "E3/DC device '%s' has no usable local host in its e3dc_rscp config entry; skipping.",
                device.get("name_by_user") or device.get("name") or device.get("model") or "unknown",
            )
            continue

        raw_name = str(
            device.get("name_by_user")
            or device.get("name")
            or device.get("model")
            or "E3/DC"
        ).strip()
        # Display names look nicer with spaces than underscores.
        name = raw_name.replace("_", " ")

        result.append({
            "device_id": str(device.get("id") or ""),
            "name": name,
            "host": host,
            "model": str(device.get("model") or "").strip(),
            "serial": native_ids[0],
            "source": f"e3dc_rscp.config_entry.host:{source_entry}",
        })

    return sorted(result, key=lambda d: d["name"].lower())



def _strip_host_port(host: str) -> str:
    host = str(host or "").strip()
    if not host:
        return ""
    # The local Overkiz config commonly stores "gateway-....local:8443".
    # Ping needs only the host name. Preserve bracketed IPv6 if ever used.
    if host.startswith("[") and "]" in host:
        return host[1:host.index("]")]
    if host.count(":") == 1:
        left, right = host.rsplit(":", 1)
        if right.isdigit():
            return left
    return host


def discover_overkiz_devices() -> Dict[str, Any]:
    """
    Discover the local Somfy/Overkiz hub and its physical child devices.

    - Hub (TaHoma Switch): Ping the local host from overkiz config-entry data.host.
    - Somfy devices: Push monitors based only on native Overkiz entity availability.
    """
    with HAWebSocket() as ha:
        entries = ha.call({"type": "config_entries/get", "domain": "overkiz"}) or []
        devices = ha.call({"type": "config/device_registry/list"}) or []
        entities = ha.call({"type": "config/entity_registry/list"}) or []
        states = ha.call({"type": "get_states"}) or []

    entry_ids = {str(e.get("entry_id")) for e in entries if e.get("entry_id")}
    if not entry_ids:
        LOG.info("No Overkiz config entry found")
        return {}

    entry_hosts = _config_entry_hosts_from_storage("overkiz", entry_ids)
    for entry in entries:
        eid = str(entry.get("entry_id") or "")
        host = str((entry.get("data") or {}).get("host") or "").strip()
        if eid and host:
            entry_hosts.setdefault(eid, host)

    # Local TaHoma hub. We deliberately derive it only from Overkiz itself.
    hub = None
    for entry in entries:
        eid = str(entry.get("entry_id") or "")
        raw_host = str(entry_hosts.get(eid) or "").strip()
        ping_host = _strip_host_port(raw_host)
        if not ping_host:
            continue

        hub_kind = str((entry.get("data") or {}).get("hub") or "").lower()
        hub_name = "Tahoma Switch" if "somfy" in hub_kind else "Overkiz Hub"
        hub = {
            "entry_id": eid,
            "name": hub_name,
            "host": ping_host,
            "source": "overkiz.config_entry.host",
        }
        break

    state_by_entity = {
        str(s.get("entity_id")): s for s in states if s.get("entity_id")
    }

    entities_by_device: Dict[str, list[Dict[str, Any]]] = {}
    for entity in entities:
        if str(entity.get("platform") or "") != "overkiz":
            continue

        eid = str(entity.get("config_entry_id") or "")
        legacy = {str(x) for x in (entity.get("config_entry_ids") or [])}
        if eid not in entry_ids and not (legacy & entry_ids):
            continue

        did = str(entity.get("device_id") or "")
        if did:
            entities_by_device.setdefault(did, []).append(entity)

    # Buttons are frequently unknown by design and should not make a device
    # look unavailable. These domains have meaningful persistent states.
    stateful_domains = {
        "binary_sensor", "sensor", "switch", "light", "cover",
        "lock", "climate", "select", "number", "fan", "valve"
    }

    children = []
    for device in devices:
        eid = str(device.get("config_entry_id") or "")
        legacy = {str(x) for x in (device.get("config_entries") or [])}
        if eid not in entry_ids and not (legacy & entry_ids):
            continue

        # Native Overkiz devices carry an overkiz identifier.
        identifiers = device.get("identifiers") or []
        if not any(
            isinstance(i, (list, tuple))
            and len(i) >= 2
            and str(i[0]).lower() == "overkiz"
            for i in identifiers
        ):
            continue

        did = str(device.get("id") or "")
        candidates = []
        for entity in entities_by_device.get(did, []):
            if entity.get("disabled_by") is not None:
                continue
            entity_id = str(entity.get("entity_id") or "")
            domain = _entity_domain(entity_id)
            if domain not in stateful_domains:
                continue
            current = state_by_entity.get(entity_id)
            if not current:
                continue
            current_state = str(current.get("state") or "").lower()
            candidates.append({
                "entity_id": entity_id,
                "state": current_state,
            })

        available = [
            c for c in candidates
            if c["state"] not in ("unavailable", "unknown", "")
        ]

        name = str(
            device.get("name_by_user")
            or device.get("name")
            or device.get("model")
            or did
        ).strip()

        # The TaHoma Switch / Overkiz base is already monitored separately
        # by a Ping monitor. Do not create a second Push monitor for the hub.
        hubish = " ".join([
            name,
            str(device.get("manufacturer") or ""),
            str(device.get("model") or ""),
        ]).lower()
        if any(token in hubish for token in ("tahoma", "overkiz hub", "gateway")):
            LOG.info(
                "Skipping Overkiz hub device '%s' as child; base is monitored by Ping",
                name,
            )
            continue

        children.append({
            "device_id": did,
            "name": name,
            "manufacturer": str(device.get("manufacturer") or "").strip(),
            "model": str(device.get("model") or "").strip(),
            "up": bool(available),
            "available_entities": len(available),
            "checked_entities": len(candidates),
            "sample_entity": (
                available[0]["entity_id"]
                if available
                else (candidates[0]["entity_id"] if candidates else "")
            ),
        })

    return {
        "hub": hub,
        "children": sorted(children, key=lambda d: d["name"].lower()),
    }



def discover_hue(include_devices: bool = True) -> Dict[str, Any]:
    """
    Discover the Hue Bridge and optional Hue child devices.

    - Bridge: ping target comes directly from the Hue config entry's data.host.
    - Child devices: availability comes only from native Hue entities in HA.
    """
    with HAWebSocket() as ha:
        entries = ha.call({"type": "config_entries/get", "domain": "hue"}) or []
        if include_devices:
            devices = ha.call({"type": "config/device_registry/list"}) or []
            entities = ha.call({"type": "config/entity_registry/list"}) or []
            states = ha.call({"type": "get_states"}) or []
        else:
            devices = []
            entities = []
            states = []

    entry_ids = {str(e.get("entry_id")) for e in entries if e.get("entry_id")}
    if not entry_ids:
        LOG.info("No Hue config entry found")
        return {}

    entry_hosts = _config_entry_hosts_from_storage("hue", entry_ids)
    for entry in entries:
        eid = str(entry.get("entry_id") or "")
        host = str((entry.get("data") or {}).get("host") or "").strip()
        if eid and host:
            entry_hosts.setdefault(eid, host)

    bridges = []
    for entry in entries:
        eid = str(entry.get("entry_id") or "")
        host = str(entry_hosts.get(eid) or "").strip()
        if not host:
            continue

        title = str(entry.get("title") or "Hue Bridge").strip()
        bridges.append({
            "entry_id": eid,
            "name": "Bridge",
            "host": host,
            "title": title,
        })

    if not include_devices:
        return {
            "bridges": bridges,
            "children": [],
        }

    state_by_entity = {
        str(s.get("entity_id")): s for s in states if s.get("entity_id")
    }

    entities_by_device: Dict[str, list[Dict[str, Any]]] = {}
    for entity in entities:
        if str(entity.get("platform") or "") != "hue":
            continue

        eid = str(entity.get("config_entry_id") or "")
        legacy = {str(x) for x in (entity.get("config_entry_ids") or [])}
        if eid not in entry_ids and not (legacy & entry_ids):
            continue

        did = str(entity.get("device_id") or "")
        if did:
            entities_by_device.setdefault(did, []).append(entity)

    stateful_domains = {
        "binary_sensor", "sensor", "switch", "light", "cover",
        "lock", "climate", "select", "number", "fan", "valve"
    }

    children = []

    for device in devices:
        eid = str(device.get("config_entry_id") or "")
        legacy = {str(x) for x in (device.get("config_entries") or [])}
        if eid not in entry_ids and not (legacy & entry_ids):
            continue

        name = str(
            device.get("name_by_user")
            or device.get("name")
            or device.get("model")
            or device.get("id")
            or ""
        ).strip()

        model = str(device.get("model") or "").strip()
        manufacturer = str(device.get("manufacturer") or "").strip()

        # Do not create a child Push monitor for the bridge itself.
        hubish = f"{name} {model}".lower()
        if "hue bridge" in hubish or model.lower() == "hue bridge":
            continue

        # Only real physical Hue/Zigbee devices should become Kuma child
        # monitors. Hue also exposes logical Room/Zone devices in HA. Those
        # have Hue identifiers and may even own light/scene entities, but
        # they do not have their own hardware MAC connection.
        identifiers = device.get("identifiers") or []
        has_hue_identifier = any(
            isinstance(i, (list, tuple))
            and len(i) >= 2
            and str(i[0]).lower() == "hue"
            for i in identifiers
        )
        if not has_hue_identifier:
            continue

        connections = device.get("connections") or []
        has_mac_connection = any(
            isinstance(c, (list, tuple))
            and len(c) >= 2
            and str(c[0]).lower() == "mac"
            and str(c[1]).strip()
            for c in connections
        )
        if not has_mac_connection:
            LOG.debug(
                "Skipping logical Hue device '%s' (model=%s): no MAC connection",
                name,
                model or "unknown",
            )
            continue

        # Explicit extra guard for the logical Hue device types seen in HA.
        if model.strip().lower() in {"room", "zone"}:
            LOG.debug(
                "Skipping logical Hue %s '%s'",
                model,
                name,
            )
            continue

        did = str(device.get("id") or "")
        candidates = []
        for entity in entities_by_device.get(did, []):
            if entity.get("disabled_by") is not None:
                continue

            entity_id = str(entity.get("entity_id") or "")
            domain = _entity_domain(entity_id)
            if domain not in stateful_domains:
                continue

            current = state_by_entity.get(entity_id)
            if not current:
                continue

            current_state = str(current.get("state") or "").lower()
            candidates.append({
                "entity_id": entity_id,
                "state": current_state,
            })

        available = [
            c for c in candidates
            if c["state"] not in ("unavailable", "unknown", "")
        ]

        # Devices without a meaningful enabled stateful entity are skipped.
        if not candidates:
            continue

        children.append({
            "device_id": did,
            "name": name,
            "manufacturer": manufacturer,
            "model": model,
            "up": bool(available),
            "available_entities": len(available),
            "checked_entities": len(candidates),
            "sample_entity": (
                available[0]["entity_id"]
                if available
                else candidates[0]["entity_id"]
            ),
        })

    return {
        "bridges": bridges,
        "children": sorted(children, key=lambda d: d["name"].lower()),
    }



def discover_smlight_devices() -> list[Dict[str, Any]]:
    """
    Discover physical SMLIGHT coordinators from the native Home Assistant
    `smlight` integration.

    The config entry's explicit `data.host` is the authoritative Ping target.
    Entries without a host are skipped. This avoids pulling duplicate devices
    from UniFi, Uptime Kuma or Zigbee2MQTT.
    """
    with HAWebSocket() as ha:
        entries = ha.call({"type": "config_entries/get", "domain": "smlight"}) or []

    entry_ids = {str(e.get("entry_id")) for e in entries if e.get("entry_id")}
    storage_hosts = _config_entry_hosts_from_storage("smlight", entry_ids)

    result = []
    seen_hosts = set()

    for entry in entries:
        eid = str(entry.get("entry_id") or "")
        title = str(entry.get("title") or "SMLIGHT").strip()

        # Home Assistant's WebSocket config_entries/get response may redact
        # config-entry data. Prefer data.host when present, otherwise fall back
        # to the local core.config_entries storage file.
        data = entry.get("data") or {}
        host = str(data.get("host") or storage_hosts.get(eid) or "").strip()

        if not host:
            LOG.info(
                "Skipping SMLIGHT config entry '%s' (%s): no host configured",
                title,
                eid or "unknown-entry",
            )
            continue

        host_key = host.lower()
        if host_key in seen_hosts:
            LOG.info(
                "Skipping duplicate SMLIGHT host %s from config entry '%s'",
                host,
                title,
            )
            continue
        seen_hosts.add(host_key)

        result.append({
            "entry_id": eid,
            "name": title,
            "host": host,
        })

    return sorted(result, key=lambda d: d["name"].lower())


def sync_smlight_devices(opts, api, monitors, default_notification_ids, state):
    devices = discover_smlight_devices()
    LOG.info(
        "Home Assistant returned %d SMLIGHT device(s) with an explicit host",
        len(devices),
    )

    for device in devices:
        monitor_name = f'{opts["smlight_monitor_prefix"]}{device["name"]}'
        ensure_ping_monitor(
            api,
            monitors,
            monitor_name,
            device["host"],
            opts["smlight_ping_interval"],
            opts["smlight_max_retries"],
            default_notification_ids,
            state=state,
            identity=f'smlight:{device["entry_id"]}',
        )

        LOG.info(
            "%s -> PING %s (source=smlight.config_entry.host, entry_id=%s)",
            monitor_name,
            device["host"],
            device["entry_id"],
        )

    state["smlight"] = {
        d["entry_id"]: {
            "name": d["name"],
            "host": d["host"],
        }
        for d in devices
    }



def discover_stiebel_eltron() -> list[Dict[str, Any]]:
    """
    Discover the native Stiebel Eltron ISG integration.

    The integration config entry provides the ISG host. The device registry is
    used only to derive the friendly physical device/model name (e.g. LWZ).
    Duplicate HACS/UPnP representations are ignored because only the native
    `stiebel_eltron_isg` config entry/device is considered.
    """
    with HAWebSocket() as ha:
        entries = ha.call(
            {"type": "config_entries/get", "domain": "stiebel_eltron_isg"}
        ) or []
        devices = ha.call({"type": "config/device_registry/list"}) or []

    entry_ids = {str(e.get("entry_id")) for e in entries if e.get("entry_id")}
    storage_hosts = _config_entry_hosts_from_storage(
        "stiebel_eltron_isg", entry_ids
    )

    result = []
    for entry in entries:
        eid = str(entry.get("entry_id") or "")
        data = entry.get("data") or {}
        host = str(data.get("host") or storage_hosts.get(eid) or "").strip()
        if not host:
            LOG.info(
                "Skipping Stiebel Eltron config entry %s: no host configured",
                eid or "unknown-entry",
            )
            continue

        # Prefer the native physical device's model/name.
        native_device = None
        for device in devices:
            dev_eid = str(device.get("config_entry_id") or "")
            dev_entries = {str(x) for x in (device.get("config_entries") or [])}
            if dev_eid != eid and eid not in dev_entries:
                continue

            identifiers = device.get("identifiers") or []
            has_native_identifier = any(
                isinstance(i, (list, tuple))
                and len(i) >= 2
                and str(i[0]) == "stiebel_eltron_isg"
                for i in identifiers
            )
            if has_native_identifier:
                native_device = device
                break

        if native_device:
            raw_name = str(
                native_device.get("name_by_user")
                or native_device.get("name")
                or native_device.get("model")
                or "ISG"
            ).strip()
            model = str(native_device.get("model") or "").strip()
            # "Stiebel Eltron LWZ" -> "LWZ"
            name = re.sub(
                r"^Stiebel\s+Eltron\s+",
                "",
                raw_name,
                flags=re.IGNORECASE,
            ).strip() or model or "ISG"
        else:
            name = "ISG"
            model = ""

        result.append({
            "entry_id": eid,
            "name": name,
            "model": model,
            "host": host,
            "port": int(data.get("port") or 502),
        })

    return result


def sync_stiebel_eltron(opts, api, monitors, default_notification_ids, state):
    devices = discover_stiebel_eltron()
    LOG.info(
        "Home Assistant returned %d native Stiebel Eltron device(s)",
        len(devices),
    )

    for device in devices:
        monitor_name = f'{opts["stiebel_eltron_monitor_prefix"]}{device["name"]}'
        ensure_ping_monitor(
            api,
            monitors,
            monitor_name,
            device["host"],
            opts["stiebel_eltron_ping_interval"],
            opts["stiebel_eltron_max_retries"],
            default_notification_ids,
            state=state,
            identity=f'stiebel_eltron:{device["entry_id"]}',
        )
        LOG.info(
            "%s -> PING %s (source=stiebel_eltron_isg.config_entry.host, modbus_port=%s)",
            monitor_name,
            device["host"],
            device["port"],
        )

    state["stiebel_eltron"] = {
        d["entry_id"]: {
            "name": d["name"],
            "model": d["model"],
            "host": d["host"],
            "port": d["port"],
        }
        for d in devices
    }



def discover_synology_dsm() -> list[Dict[str, Any]]:
    """
    Discover physical Synology NAS systems from the native `synology_dsm`
    integration.

    Only the root NAS device for a config entry is considered. Drive, M.2,
    USB-disk and volume child devices are ignored by requiring `via_device_id`
    to be empty and a native `synology_dsm` identifier.
    """
    with HAWebSocket() as ha:
        entries = ha.call(
            {"type": "config_entries/get", "domain": "synology_dsm"}
        ) or []
        devices = ha.call({"type": "config/device_registry/list"}) or []

    entry_ids = {str(e.get("entry_id")) for e in entries if e.get("entry_id")}
    storage_hosts = _config_entry_hosts_from_storage("synology_dsm", entry_ids)

    result = []
    seen_hosts = set()

    for entry in entries:
        eid = str(entry.get("entry_id") or "")
        data = entry.get("data") or {}
        host = str(data.get("host") or storage_hosts.get(eid) or "").strip()

        # Old/stale entries can still exist without usable data.
        if not host:
            LOG.info(
                "Skipping Synology DSM config entry '%s' (%s): no host configured",
                str(entry.get("title") or "Synology DSM"),
                eid or "unknown-entry",
            )
            continue

        if host.lower() in seen_hosts:
            LOG.info("Skipping duplicate Synology DSM host %s", host)
            continue
        seen_hosts.add(host.lower())

        root_device = None
        for device in devices:
            dev_eid = str(device.get("config_entry_id") or "")
            dev_entries = {str(x) for x in (device.get("config_entries") or [])}
            if dev_eid != eid and eid not in dev_entries:
                continue

            if device.get("via_device_id"):
                continue

            identifiers = device.get("identifiers") or []
            has_native_identifier = any(
                isinstance(i, (list, tuple))
                and len(i) >= 2
                and str(i[0]) == "synology_dsm"
                for i in identifiers
            )
            if not has_native_identifier:
                continue

            root_device = device
            break

        if root_device:
            name = str(
                root_device.get("name_by_user")
                or root_device.get("name")
                or root_device.get("model")
                or "NAS"
            ).strip()
            model = str(root_device.get("model") or "").strip()
        else:
            name = "NAS"
            model = ""

        result.append({
            "entry_id": eid,
            "name": name,
            "model": model,
            "host": host,
        })

    return sorted(result, key=lambda d: d["name"].lower())


def sync_synology_dsm(opts, api, monitors, default_notification_ids, state):
    devices = discover_synology_dsm()
    LOG.info(
        "Home Assistant returned %d physical Synology NAS device(s)",
        len(devices),
    )

    for device in devices:
        monitor_name = f'{opts["synology_monitor_prefix"]}{device["name"]}'
        ensure_ping_monitor(
            api,
            monitors,
            monitor_name,
            device["host"],
            opts["synology_ping_interval"],
            opts["synology_max_retries"],
            default_notification_ids,
            state=state,
            identity=f'synology_dsm:{device["entry_id"]}',
        )

        LOG.info(
            "%s -> PING %s (source=synology_dsm.config_entry.host, model=%s)",
            monitor_name,
            device["host"],
            device["model"] or "unknown",
        )

    state["synology_dsm"] = {
        d["entry_id"]: {
            "name": d["name"],
            "model": d["model"],
            "host": d["host"],
        }
        for d in devices
    }



def discover_esphome_devices() -> list[Dict[str, Any]]:
    """
    Discover physical ESPHome devices from native `esphome` config entries.

    The config entry itself is the source of truth for monitor name and host.
    This avoids duplicate Bluetooth-proxy helper devices and ignores the
    ESPHome Device Builder add-on device.
    """
    with HAWebSocket() as ha:
        entries = ha.call(
            {"type": "config_entries/get", "domain": "esphome"}
        ) or []

    entry_ids = {str(e.get("entry_id")) for e in entries if e.get("entry_id")}
    storage_hosts = _config_entry_hosts_from_storage("esphome", entry_ids)

    result = []
    seen_hosts = set()

    for entry in entries:
        eid = str(entry.get("entry_id") or "")
        title = str(entry.get("title") or "ESPHome").strip()
        data = entry.get("data") or {}

        # HA may redact config-entry data over WebSocket. Fall back to the
        # local config-entry storage exactly like SMLIGHT/Synology.
        host = str(data.get("host") or storage_hosts.get(eid) or "").strip()
        if not host:
            LOG.info(
                "Skipping ESPHome config entry '%s' (%s): no host configured",
                title,
                eid or "unknown-entry",
            )
            continue

        host_key = host.lower()
        if host_key in seen_hosts:
            LOG.info(
                "Skipping duplicate ESPHome host %s from config entry '%s'",
                host,
                title,
            )
            continue
        seen_hosts.add(host_key)

        result.append({
            "entry_id": eid,
            "name": title,
            "host": host,
            "port": int(data.get("port") or 6053),
            "device_name": str(data.get("device_name") or "").strip(),
        })

    return sorted(result, key=lambda d: d["name"].lower())


def sync_esphome_devices(opts, api, monitors, default_notification_ids, state):
    devices = discover_esphome_devices()
    LOG.info(
        "Home Assistant returned %d ESPHome device(s) with an explicit host",
        len(devices),
    )

    for device in devices:
        monitor_name = f'{opts["esphome_monitor_prefix"]}{device["name"]}'
        ensure_ping_monitor(
            api,
            monitors,
            monitor_name,
            device["host"],
            opts["esphome_ping_interval"],
            opts["esphome_max_retries"],
            default_notification_ids,
            state=state,
            identity=f'esphome:{device["entry_id"]}',
        )

        LOG.info(
            "%s -> PING %s (source=esphome.config_entry.host, api_port=%s)",
            monitor_name,
            device["host"],
            device["port"],
        )

    state["esphome"] = {
        d["entry_id"]: {
            "name": d["name"],
            "host": d["host"],
            "port": d["port"],
            "device_name": d["device_name"],
        }
        for d in devices
    }



def discover_airgradient_devices() -> list[Dict[str, Any]]:
    """One physical native AirGradient device, using its explicit entry host."""
    with HAWebSocket() as ha:
        entries = ha.call({"type": "config_entries/get", "domain": "airgradient"}) or []
        if not entries:
            return []
        devices = ha.call({"type": "config/device_registry/list"}) or []
    if not devices:
        return []

    entry_by_id = {str(e["entry_id"]): e for e in entries if e.get("entry_id")}
    hosts = _config_entry_hosts_from_storage("airgradient", set(entry_by_id))
    result, seen = [], set()
    for device in devices:
        if device.get("entry_type") is not None or device.get("disabled_by") is not None:
            continue
        if device.get("via_device_id"):
            continue
        native_ids = sorted(str(i[1]) for i in device.get("identifiers") or []
                            if isinstance(i, (list, tuple)) and len(i) == 2
                            and i[0] == "airgradient" and i[1])
        if not native_ids or native_ids[0] in seen:
            continue
        matching = set(str(e) for e in device.get("config_entries") or [])
        if device.get("config_entry_id"):
            matching.add(str(device["config_entry_id"]))
        matching &= entry_by_id.keys()
        if not matching:
            continue
        host, entry = "", None
        for eid in sorted(matching):
            candidate_entry = entry_by_id[eid]
            candidate = str((candidate_entry.get("data") or {}).get("host") or hosts.get(eid) or "").strip()
            # Explicit native host only: do not interpret URLs, credentials,
            # entity names, MAC addresses or arbitrary connection strings.
            try:
                address = ipaddress.ip_address(candidate)
            except ValueError:
                valid = bool(candidate and len(candidate) <= 253 and all(
                    re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label)
                    for label in candidate.rstrip(".").split(".")
                ))
            else:
                valid = address.is_private and not (address.is_unspecified or address.is_multicast or address.is_loopback)
            if valid:
                host, entry = candidate, candidate_entry
                break
        if not host:
            LOG.info("Skipping AirGradient device: no usable local config-entry host")
            continue
        serial = native_ids[0]
        seen.add(serial)
        # Core's entry title is usually a model shared by many devices. A
        # serial-qualified fallback stays unique even without a user name.
        name = str(device.get("name_by_user") or device.get("name") or "").strip()
        if not name:
            name = f'{entry.get("title") or device.get("model") or "Device"} ({serial})'
        result.append({"device_id": str(device.get("id") or serial),
                       "entry_id": str(entry["entry_id"]), "serial": serial,
                       "name": name, "host": host})
    # Keep distinct physical devices with identical user names distinct in Kuma.
    counts = {}
    for device in result:
        counts[device["name"]] = counts.get(device["name"], 0) + 1
    for device in result:
        if counts[device["name"]] > 1:
            device["name"] += f' ({device["serial"]})'
    return sorted(result, key=lambda d: d["name"].lower())


def sync_airgradient_devices(opts, api, monitors, default_notification_ids, state):
    devices = discover_airgradient_devices()
    for device in devices:
        name = f'{opts["airgradient_monitor_prefix"]}{device["name"]}'
        ensure_ping_monitor(api, monitors, name, device["host"],
                            opts["airgradient_ping_interval"], opts["airgradient_max_retries"],
                            default_notification_ids, state=state,
                            identity=f'airgradient:{device["entry_id"]}')
        LOG.info("%s -> PING %s (source=airgradient.config_entry.host)", name, device["host"])
    state["airgradient"] = {
        d["device_id"]: {"name": d["name"], "host": d["host"], "entry_id": d["entry_id"]}
        for d in devices
    }


def discover_mqtt_physical_devices() -> Dict[str, list[Dict[str, Any]]]:
    """
    Discover MQTT-backed physical devices from Home Assistant.

    Devices are split into:
      - Zigbee2MQTT: native MQTT identifiers starting with `zigbee2mqtt_0x`
      - Generic MQTT: other native MQTT identifiers

    Explicitly excluded:
      - Zigbee2MQTT Bridge
      - Zigbee2MQTT Group objects
      - non-MQTT devices such as Uptime Kuma imports
      - devices without a reliable enabled stateful entity

    Availability is derived from Home Assistant entity availability. Devices
    that expose only buttons/events are skipped because those entities are not
    a trustworthy liveness signal. For Zigbee2MQTT, configuration/diagnostic
    entities such as linkquality, last_seen and light_indicator_level are also
    ignored as sole availability indicators.
    """
    with HAWebSocket() as ha:
        devices = ha.call({"type": "config/device_registry/list"}) or []
        entities = ha.call({"type": "config/entity_registry/list"}) or []
        states = ha.call({"type": "get_states"}) or []

    state_by_entity = {
        str(s.get("entity_id")): s for s in states if s.get("entity_id")
    }

    entities_by_device: Dict[str, list[Dict[str, Any]]] = {}
    for entity in entities:
        if str(entity.get("platform") or "") != "mqtt":
            continue
        did = str(entity.get("device_id") or "")
        if did:
            entities_by_device.setdefault(did, []).append(entity)

    stateful_domains = {
        "binary_sensor", "sensor", "switch", "light", "cover",
        "lock", "climate", "select", "number", "fan", "valve",
        "text"
    }

    zigbee2mqtt_devices = []
    mqtt_devices = []

    for device in devices:
        did = str(device.get("id") or "")
        identifiers = device.get("identifiers") or []

        mqtt_ids = [
            str(i[1])
            for i in identifiers
            if isinstance(i, (list, tuple))
            and len(i) >= 2
            and str(i[0]).lower() == "mqtt"
        ]
        if not mqtt_ids:
            continue

        name = str(
            device.get("name_by_user")
            or device.get("name")
            or device.get("model")
            or did
        ).strip()
        manufacturer = str(device.get("manufacturer") or "").strip()
        model = str(device.get("model") or "").strip()

        id_lower = [x.lower() for x in mqtt_ids]
        is_z2m_bridge = any(x.startswith("zigbee2mqtt_bridge_") for x in id_lower)
        is_z2m_group = (
            manufacturer.lower() == "zigbee2mqtt"
            and model.lower() == "group"
        )
        if is_z2m_bridge or is_z2m_group:
            LOG.debug(
                "Skipping logical Zigbee2MQTT object '%s' (model=%s)",
                name,
                model or "unknown",
            )
            continue

        # A physical Zigbee2MQTT device uses the IEEE-address based identifier.
        is_z2m_physical = any(
            re.match(r"^zigbee2mqtt_0x[0-9a-f]+$", x)
            for x in id_lower
        )

        preferred = []
        z2m_event_fallback = []

        ignored_z2m_availability_suffixes = (
            "_linkquality_zigbee2mqtt",
            "_last_seen_zigbee2mqtt",
            "_light_indicator_level_zigbee2mqtt",
            "_power_on_behavior_zigbee2mqtt",
        )

        for entity in entities_by_device.get(did, []):
            if entity.get("disabled_by") is not None:
                continue

            entity_id = str(entity.get("entity_id") or "")
            unique_id = str(entity.get("unique_id") or "").lower()
            current = state_by_entity.get(entity_id)
            if not current:
                continue

            if is_z2m_physical and unique_id.endswith(
                ignored_z2m_availability_suffixes
            ):
                continue

            domain = _entity_domain(entity_id)
            item = {
                "entity_id": entity_id,
                "state": str(current.get("state") or "").lower(),
            }

            if domain in stateful_domains:
                preferred.append(item)
            elif is_z2m_physical and domain == "event":
                # Battery remotes/buttons can legitimately expose only an
                # event entity. Its explicit HA availability is still useful,
                # even though the event value itself is not stateful.
                z2m_event_fallback.append(item)

        if preferred:
            candidates = preferred
            available = [
                item for item in candidates
                if item["state"] not in ("unavailable", "unknown", "")
            ]
            availability_mode = "stateful"
        elif z2m_event_fallback:
            candidates = z2m_event_fallback
            available = [
                item for item in candidates
                if item["state"] != "unavailable"
            ]
            availability_mode = "zigbee2mqtt_event"
        else:
            LOG.info(
                "Skipping MQTT device '%s': no reliable availability entity",
                name,
            )
            continue

        record = {
            "device_id": did,
            "name": name,
            "manufacturer": manufacturer,
            "model": model,
            "mqtt_ids": mqtt_ids,
            "up": bool(available),
            "available_entities": len(available),
            "checked_entities": len(candidates),
            "sample_entity": (
                available[0]["entity_id"]
                if available
                else candidates[0]["entity_id"]
            ),
            "availability_mode": availability_mode,
        }

        if is_z2m_physical:
            zigbee2mqtt_devices.append(record)
        else:
            mqtt_devices.append(record)

    return {
        "zigbee2mqtt": sorted(
            zigbee2mqtt_devices, key=lambda d: d["name"].lower()
        ),
        "mqtt": sorted(mqtt_devices, key=lambda d: d["name"].lower()),
    }



def _push_effective_up(
    state: Dict[str, Any],
    state_key: str,
    device_id: str,
    observed_up: bool,
    grace_cycles: int,
) -> tuple[bool, int]:
    """
    Debounce Home Assistant state-based Push monitor DOWN transitions.

    UP is reported immediately. DOWN is reported only after the configured
    number of consecutive unavailable sync cycles. The counter is persisted
    in the add-on state across sync cycles.
    """
    debounce = state.setdefault("_push_down_debounce", {})
    bucket = debounce.setdefault(state_key, {})
    entry = bucket.setdefault(device_id, {"down_cycles": 0})

    if observed_up:
        entry["down_cycles"] = 0
        return True, 0

    down_cycles = int(entry.get("down_cycles", 0)) + 1
    entry["down_cycles"] = down_cycles

    effective_up = down_cycles < grace_cycles
    return effective_up, down_cycles


def _sync_mqtt_device_list(
    opts,
    api,
    monitors,
    default_notification_ids,
    state,
    devices,
    prefix,
    state_key,
):
    LOG.info(
        "Home Assistant returned %d physical %s device(s)",
        len(devices),
        state_key,
    )

    for device in devices:
        monitor_name = f'{prefix}{device["name"]}'
        monitor = ensure_push_monitor(
            api,
            monitors,
            monitor_name,
            opts["heartbeat_interval"],
            default_notification_ids,
            state=state,
            identity=f'{state_key}:{device["device_id"]}',
        )

        effective_up, down_cycles = _push_effective_up(
            state,
            state_key,
            device["device_id"],
            bool(device["up"]),
            opts["push_down_grace_cycles"],
        )

        message = (
            f'HA MQTT availability: '
            f'{device["available_entities"]}/{device["checked_entities"]} '
            f'entities available'
        )
        if not device["up"] and effective_up:
            message += (
                f' | DOWN grace '
                f'{down_cycles}/{opts["push_down_grace_cycles"]}'
            )
        if device.get("sample_entity"):
            message += f' | sample: {device["sample_entity"]}'

        push_status_if_needed(
            opts["kuma_url"],
            monitor,
            effective_up,
            message,
            opts["verify_ssl"],
            state,
            opts["heartbeat_interval"],
            opts["sync_interval"],
        )

        LOG.info(
            "%s -> %s (observed=%s, down_grace=%d/%d, %d/%d MQTT entities available, mode=%s, model=%s)",
            monitor_name,
            "UP" if effective_up else "DOWN",
            "UP" if device["up"] else "DOWN",
            down_cycles,
            opts["push_down_grace_cycles"],
            device["available_entities"],
            device["checked_entities"],
            device["availability_mode"],
            device["model"] or "unknown",
        )

    state[state_key] = {
        d["device_id"]: {
            "name": d["name"],
            "manufacturer": d["manufacturer"],
            "model": d["model"],
            "mqtt_ids": d["mqtt_ids"],
        }
        for d in devices
    }


def sync_mqtt_devices(opts, api, monitors, default_notification_ids, state):
    data = discover_mqtt_physical_devices()

    if opts["discover_zigbee2mqtt_devices"]:
        _sync_mqtt_device_list(
            opts,
            api,
            monitors,
            default_notification_ids,
            state,
            data["zigbee2mqtt"],
            opts["zigbee2mqtt_monitor_prefix"],
            "zigbee2mqtt",
        )

    if opts["discover_mqtt_devices"]:
        _sync_mqtt_device_list(
            opts,
            api,
            monitors,
            default_notification_ids,
            state,
            data["mqtt"],
            opts["mqtt_monitor_prefix"],
            "mqtt",
        )


def sync_hue(opts, api, monitors, default_notification_ids, state):
    data = discover_hue(include_devices=opts["discover_hue_devices"])
    prefix = opts["hue_monitor_prefix"]

    bridges = data.get("bridges") or []
    if opts["discover_hue_bridge"]:
        for index, bridge in enumerate(bridges, start=1):
            suffix = "" if len(bridges) == 1 else f" {index}"
            monitor_name = f'{prefix}{bridge["name"]}{suffix}'
            ensure_ping_monitor(
                api,
                monitors,
                monitor_name,
                bridge["host"],
                opts["hue_ping_interval"],
                opts["hue_max_retries"],
                default_notification_ids,
                state=state,
                identity=f'hue_bridge:{bridge["entry_id"]}',
            )
            LOG.info(
                "%s -> PING %s (source=hue.config_entry.host, title=%s)",
                monitor_name,
                bridge["host"],
                bridge["title"],
            )

    children = data.get("children") or []
    if opts["discover_hue_devices"]:
        LOG.info("Home Assistant returned %d Hue child device(s)", len(children))

        for device in children:
            monitor_name = f'{prefix}{device["name"]}'
            monitor = ensure_push_monitor(
                api,
                monitors,
                monitor_name,
                opts["heartbeat_interval"],
                default_notification_ids,
                state=state,
                identity=f'hue_device:{device["device_id"]}',
            )

            message = (
                f'HA Hue availability: '
                f'{device["available_entities"]}/{device["checked_entities"]} '
                f'active entities available'
            )
            if device.get("sample_entity"):
                message += f' | sample: {device["sample_entity"]}'

            effective_up, down_cycles = _push_effective_up(
                state,
                "hue",
                device["device_id"],
                bool(device["up"]),
                opts["push_down_grace_cycles"],
            )
            if not device["up"] and effective_up:
                message += f' | DOWN grace {down_cycles}/{opts["push_down_grace_cycles"]}'

            push_status_if_needed(
                opts["kuma_url"],
                monitor,
                effective_up,
                message,
                opts["verify_ssl"],
                state,
                opts["heartbeat_interval"],
                opts["sync_interval"],
            )

            LOG.info(
                "%s -> %s (observed=%s, down_grace=%d/%d, %d/%d Hue entities available, model=%s, device_id=%s)",
                monitor_name,
                "UP" if effective_up else "DOWN",
                "UP" if device["up"] else "DOWN",
                down_cycles,
                opts["push_down_grace_cycles"],
                device["available_entities"],
                device["checked_entities"],
                device["model"] or "unknown",
                device["device_id"],
            )

    state["hue"] = {
        "bridges": bridges,
        "devices": {
            d["device_id"]: {
                "name": d["name"],
                "manufacturer": d["manufacturer"],
                "model": d["model"],
            }
            for d in children
        },
    }


def sync_overkiz_devices(opts, api, monitors, default_notification_ids, state):
    data = discover_overkiz_devices()
    prefix = opts["overkiz_monitor_prefix"]

    hub = data.get("hub")
    if hub:
        monitor_name = f'{prefix}{hub["name"]}'
        ensure_ping_monitor(
            api,
            monitors,
            monitor_name,
            hub["host"],
            opts["overkiz_ping_interval"],
            opts["overkiz_max_retries"],
            default_notification_ids,
            state=state,
            identity=f'overkiz_hub:{hub["entry_id"]}',
        )
        LOG.info(
            "%s -> PING %s (source=%s)",
            monitor_name,
            hub["host"],
            hub["source"],
        )

    children = data.get("children") or []
    LOG.info("Home Assistant returned %d Overkiz/Somfy child device(s)", len(children))

    for device in children:
        monitor_name = f'{prefix}{device["name"]}'
        monitor = ensure_push_monitor(
            api,
            monitors,
            monitor_name,
            opts["heartbeat_interval"],
            default_notification_ids,
            state=state,
            identity=f'overkiz_device:{device["device_id"]}',
        )

        message = (
            f'HA Overkiz availability: '
            f'{device["available_entities"]}/{device["checked_entities"]} '
            f'active entities available'
        )
        if device.get("sample_entity"):
            message += f' | sample: {device["sample_entity"]}'

        effective_up, down_cycles = _push_effective_up(
            state,
            "overkiz",
            device["device_id"],
            bool(device["up"]),
            opts["push_down_grace_cycles"],
        )
        if not device["up"] and effective_up:
            message += f' | DOWN grace {down_cycles}/{opts["push_down_grace_cycles"]}'

        push_status_if_needed(
            opts["kuma_url"],
            monitor,
            effective_up,
            message,
            opts["verify_ssl"],
            state,
            opts["heartbeat_interval"],
            opts["sync_interval"],
        )

        LOG.info(
            "%s -> %s (observed=%s, down_grace=%d/%d, %d/%d Overkiz entities available, model=%s, device_id=%s)",
            monitor_name,
            "UP" if effective_up else "DOWN",
            "UP" if device["up"] else "DOWN",
            down_cycles,
            opts["push_down_grace_cycles"],
            device["available_entities"],
            device["checked_entities"],
            device["model"] or "unknown",
            device["device_id"],
        )

    state["overkiz"] = {
        "hub": hub or {},
        "devices": {
            d["device_id"]: {
                "name": d["name"],
                "manufacturer": d["manufacturer"],
                "model": d["model"],
            }
            for d in children
        },
    }


def sync_e3dc_devices(opts, api, monitors, default_notification_ids, state):
    devices = discover_e3dc_devices()
    LOG.info("Home Assistant returned %d E3/DC device(s) with an address", len(devices))

    for device in devices:
        monitor_name = f'{opts["e3dc_monitor_prefix"]}{device["name"]}'
        ensure_ping_monitor(
            api,
            monitors,
            monitor_name,
            device["host"],
            opts["e3dc_ping_interval"],
            opts["e3dc_max_retries"],
            default_notification_ids,
            state=state,
            identity=f'e3dc:{device["device_id"]}',
        )
        LOG.info(
            "%s -> PING %s (model=%s, serial=%s, source=%s, device_id=%s)",
            monitor_name,
            device["host"],
            device["model"] or "unknown",
            device["serial"],
            device["source"],
            device["device_id"],
        )

    state["known_e3dc_device_ids"] = sorted(d["device_id"] for d in devices)
    state["e3dc_devices"] = {
        d["device_id"]: {
            "name": d["name"],
            "host": d["host"],
            "model": d["model"],
            "serial": d["serial"],
        }
        for d in devices
    }


def sync_matter_devices(opts, api, monitors, default_notification_ids, state):
    devices = discover_matter_devices()
    LOG.info("Home Assistant returned %d Matter device(s)", len(devices))

    for device in devices:
        monitor_name = f'{opts["matter_monitor_prefix"]}{device["name"]}'
        monitor = ensure_push_monitor(
            api,
            monitors,
            monitor_name,
            opts["heartbeat_interval"],
            default_notification_ids,
            state=state,
            identity=f'matter:{device["device_id"]}',
        )

        message = (
            f'HA Matter availability: '
            f'{device["available_entities"]}/{device["checked_entities"]} '
            f'active entities available'
        )
        if device.get("sample_entity"):
            message += f' | sample: {device["sample_entity"]}'

        effective_up, down_cycles = _push_effective_up(
            state,
            "matter",
            device["device_id"],
            bool(device["up"]),
            opts["push_down_grace_cycles"],
        )
        if not device["up"] and effective_up:
            message += f' | DOWN grace {down_cycles}/{opts["push_down_grace_cycles"]}'

        push_status_if_needed(
            opts["kuma_url"],
            monitor,
            effective_up,
            message,
            opts["verify_ssl"],
            state,
            opts["heartbeat_interval"],
            opts["sync_interval"],
        )

        LOG.info(
            "%s -> %s (observed=%s, down_grace=%d/%d, %d/%d Matter entities available, model=%s, device_id=%s)",
            monitor_name,
            "UP" if effective_up else "DOWN",
            "UP" if device["up"] else "DOWN",
            down_cycles,
            opts["push_down_grace_cycles"],
            device["available_entities"],
            device["checked_entities"],
            device["model"] or "unknown",
            device["device_id"],
        )

    state["known_matter_device_ids"] = sorted(d["device_id"] for d in devices)
    state["matter_devices"] = {
        d["device_id"]: {
            "name": d["name"],
            "manufacturer": d["manufacturer"],
            "model": d["model"],
        }
        for d in devices
    }


def sync_homematic_ip_infrastructure(opts, api, monitors, default_notification_ids, state):
    infra = discover_homematic_ip_infrastructure()
    prefix = opts["homematic_ip_monitor_prefix"]

    hcu = infra.get("hcu")
    if hcu:
        monitor_name = f'{prefix}{hcu["name"]}'
        ensure_ping_monitor(
            api,
            monitors,
            monitor_name,
            hcu["host"],
            opts["homematic_ip_ping_interval"],
            opts["homematic_ip_max_retries"],
            default_notification_ids,
            state=state,
            identity=f'homematic_hcu:{hcu["device_id"]}',
        )
        LOG.info(
            "%s -> PING %s (model=%s, source=%s)",
            monitor_name,
            hcu["host"],
            hcu["model"],
            hcu["source"],
        )

    devices = infra.get("devices") or []
    for device in devices:
        monitor_name = f'{prefix}{device["name"]}'
        monitor = ensure_push_monitor(
            api,
            monitors,
            monitor_name,
            opts["heartbeat_interval"],
            default_notification_ids,
            state=state,
            identity=f'homematic_device:{device["device_id"]}',
        )

        # HA connectivity binary_sensor:
        #   on  = connected/reachable
        #   off = disconnected/unreachable
        # Unknown/unavailable is treated as DOWN because the integration itself
        # cannot currently confirm reachability.
        ha_state = device["state"]
        up = ha_state == "on"

        effective_up, down_cycles = _push_effective_up(
            state,
            "homematic_ip",
            device["device_id"],
            up,
            opts["push_down_grace_cycles"],
        )
        message = f'HA {device["connectivity_entity"]}: {ha_state}'
        if not up and effective_up:
            message += f' | DOWN grace {down_cycles}/{opts["push_down_grace_cycles"]}'

        push_status_if_needed(
            opts["kuma_url"],
            monitor,
            effective_up,
            message,
            opts["verify_ssl"],
            state,
            opts["heartbeat_interval"],
            opts["sync_interval"],
        )
        LOG.info(
            "%s -> %s via %s (observed=%s, down_grace=%d/%d, HA state=%s)",
            monitor_name,
            "UP" if effective_up else "DOWN",
            device["connectivity_entity"],
            "UP" if up else "DOWN",
            down_cycles,
            opts["push_down_grace_cycles"],
            ha_state,
        )

    records = {
        device["device_id"]: {
            "name": device["name"],
            "model": device["model"],
            "connectivity_entity": device["connectivity_entity"],
        }
        for device in devices
    }
    state["homematic_ip"] = {
        "hcu": hcu or {},
        "devices": records,
        # Keep the existing HAP inventory key for persisted-state compatibility.
        "access_points": {did: item for did, item in records.items()
                          if item["model"] == "HmIP-HAP"},
    }


def sync_fully_kiosk_devices(opts, api, monitors, default_notification_ids, state):
    devices = discover_fully_kiosk_devices()
    LOG.info(
        "Home Assistant returned %d Fully Kiosk device(s) with an address",
        len(devices),
    )

    for device in devices:
        monitor_name = f'{opts["fully_kiosk_monitor_prefix"]}{device["name"]}'
        ensure_ping_monitor(
            api,
            monitors,
            monitor_name,
            device["host"],
            opts["fully_kiosk_ping_interval"],
            opts["fully_kiosk_max_retries"],
            default_notification_ids,
            state=state,
            identity=f'fully_kiosk:{device["device_id"]}',
        )
        LOG.info(
            "%s -> PING %s (model=%s, area=%s, device_id=%s)",
            monitor_name,
            device["host"],
            device["model"] or "unknown",
            device.get("area") or "none",
            device["device_id"],
        )

    state["known_fully_kiosk_device_ids"] = sorted(d["device_id"] for d in devices)
    state["fully_kiosk_devices"] = {
        d["device_id"]: {
            "name": d["name"],
            "host": d["host"],
            "model": d["model"],
            "area": d.get("area") or "",
        }
        for d in devices
    }


def sync_fritz_network_devices(opts, api, monitors, default_notification_ids, state):
    devices = discover_fritz_network_devices()
    LOG.info(
        "Home Assistant returned %d FRITZ! network infrastructure device(s)",
        len(devices),
    )

    for device in devices:
        monitor_name = f'{opts["fritz_monitor_prefix"]}{device["name"]}'
        ensure_ping_monitor(
            api,
            monitors,
            monitor_name,
            device["host"],
            opts["fritz_ping_interval"],
            opts["fritz_max_retries"],
            default_notification_ids,
            state=state,
            identity=f'fritz:{device["device_id"]}',
        )
        LOG.info(
            "%s -> PING %s (model=%s, source=%s, device_id=%s)",
            monitor_name,
            device["host"],
            device["model"] or "unknown",
            device.get("source") or "unknown",
            device["device_id"],
        )

    state["known_fritz_device_ids"] = sorted(d["device_id"] for d in devices)
    state["fritz_devices"] = {
        d["device_id"]: {
            "name": d["name"],
            "host": d["host"],
            "model": d["model"],
        }
        for d in devices
    }


def sync_unifi_network_devices(opts, api, monitors, default_notification_ids, state):
    devices = discover_unifi_network_devices()
    LOG.info(
        "Home Assistant returned %d UniFi infrastructure device(s) with an address",
        len(devices),
    )

    for device in devices:
        monitor_name = f'{opts["unifi_monitor_prefix"]}{device["name"]}'
        ensure_ping_monitor(
            api,
            monitors,
            monitor_name,
            device["host"],
            opts["unifi_ping_interval"],
            opts["unifi_max_retries"],
            default_notification_ids,
            state=state,
            identity=f'unifi:{device["device_id"]}',
        )
        LOG.info(
            "%s -> PING %s (model=%s, source=%s, device_id=%s)",
            monitor_name,
            device["host"],
            device["model"] or "unknown",
            device.get("ip_source") or "unknown",
            device["device_id"],
        )

    state["known_unifi_device_ids"] = sorted(d["device_id"] for d in devices)
    state["unifi_devices"] = {
        d["device_id"]: {
            "name": d["name"],
            "host": d["host"],
            "model": d["model"],
        }
        for d in devices
    }


def sync_once(opts):
    state = load_state()
    try:
        with kuma_session(opts) as api:
            kuma_call("authentication/login", api.login,
                      opts["kuma_username"], opts["kuma_password"],
                      _log_duration=True)
            monitors = normalize_items(kuma_call(
                "fetching monitors", api.get_monitors, _log_duration=True,
            ))
            default_notification_ids = get_default_notification_ids(api)
            jobs = [
                (opts["discover_addons"], sync_addons),
                (opts["discover_shelly"], sync_shelly),
                (opts["discover_unifi_network_devices"], sync_unifi_network_devices),
                (opts["discover_fritz_network_devices"], sync_fritz_network_devices),
                (opts["discover_fully_kiosk_devices"], sync_fully_kiosk_devices),
                (opts["discover_homematic_ip_infrastructure"], sync_homematic_ip_infrastructure),
                (opts["discover_matter_devices"], sync_matter_devices),
                (opts["discover_e3dc_devices"], sync_e3dc_devices),
                (opts["discover_overkiz_devices"], sync_overkiz_devices),
                (opts["discover_hue_bridge"] or opts["discover_hue_devices"], sync_hue),
                (opts["discover_smlight_devices"], sync_smlight_devices),
                (opts["discover_stiebel_eltron"], sync_stiebel_eltron),
                (opts["discover_synology_dsm"], sync_synology_dsm),
                (opts["discover_esphome_devices"], sync_esphome_devices),
                (opts["discover_airgradient_devices"], sync_airgradient_devices),
                (opts["discover_zigbee2mqtt_devices"] or opts["discover_mqtt_devices"], sync_mqtt_devices),
            ]
            failed = []
            completed = 0
            timings = []
            HAWebSocket.begin_cycle()
            try:
                for enabled, sync in jobs:
                    if not enabled:
                        continue
                    integration_started = time.monotonic()
                    try:
                        sync(opts, api, monitors, default_notification_ids, state)
                        completed += 1
                    except Exception as exc:
                        failed.append(sync.__name__)
                        # Request exceptions can contain secret Push URLs.
                        LOG.error("Integration %s failed (%s); continuing with remaining integrations",
                                  sync.__name__, type(exc).__name__)
                    finally:
                        timings.append((sync.__name__, time.monotonic() - integration_started))
            finally:
                HAWebSocket.end_cycle()
            if timings:
                LOG.info("Integration timings: %s", ", ".join(
                    f"{name}={duration:.1f}s" for name, duration in timings
                ))
            if failed:
                LOG.warning("Sync partially completed: %d succeeded, %d failed: %s",
                            completed, len(failed), ", ".join(failed))
            else:
                LOG.info("Sync completed: %d integration(s) succeeded", completed)
    finally:
        # Preserve successful Push timestamps and debounce counters on partial failure.
        save_state(state)


def _run():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    LOG.info("Starting HA Kuma Discovery 2.0.1")

    while True:
        started = time.monotonic()
        try:
            opts = read_options()
            sync_once(opts)
            sync_interval = opts["sync_interval"]
        except KeyboardInterrupt:
            return
        except Exception as exc:
            LOG.error("Sync failed (%s)", type(exc).__name__)
            try:
                sync_interval = read_options().get("sync_interval", 60)
            except Exception:
                sync_interval = 60

        elapsed = time.monotonic() - started
        sleep_for = max(1, sync_interval - elapsed)
        LOG.info("Sync cycle took %.1fs; next cycle in %.1fs", elapsed, sleep_for)
        time.sleep(sleep_for)


def main():
    try:
        _run()
    finally:
        HTTP.close()


if __name__ == "__main__":
    main()
