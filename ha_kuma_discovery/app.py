#!/usr/bin/env python3

import json
import logging
import os
import re
import time
import ipaddress
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Any
from urllib.parse import urlparse

import requests
import websocket
from uptime_kuma_api import UptimeKumaApi

import ha_client
import integration_addons
import integration_e3dc
import integration_fritz
import integration_fully_kiosk
import integration_homematic
import integration_hue
import integration_matter
import integration_overkiz
import integration_shelly
import integration_smlight
import integration_stiebel_eltron
import integration_unifi
import kuma_monitor
import push_state
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



normalize_items = kuma_monitor.normalize_items
find_monitor = kuma_monitor.find_monitor
find_managed_monitor = kuma_monitor.find_managed_monitor
remember_monitor_identity = kuma_monitor.remember_monitor_identity
notification_is_default = kuma_monitor.notification_is_default
notification_is_active = kuma_monitor.notification_is_active


@contextmanager
def kuma_operation(stage, log_duration=False):
    with kuma_monitor.kuma_operation(stage, log_duration=log_duration):
        yield


def kuma_call(stage, operation, *args, _log_duration=False, **kwargs):
    return kuma_monitor.kuma_call(
        stage, operation, *args, _log_duration=_log_duration, **kwargs
    )


@contextmanager
def kuma_session(opts):
    with kuma_monitor.kuma_session(opts, api_factory=UptimeKumaApi) as api:
        yield api


get_default_notification_ids = kuma_monitor.get_default_notification_ids
monitor_notification_ids = kuma_monitor.monitor_notification_ids
ensure_push_monitor = kuma_monitor.ensure_push_monitor
ensure_ping_monitor = kuma_monitor.ensure_ping_monitor


def push_status(kuma_url, monitor, up, message, verify_ssl):
    return push_state.push_status(
        kuma_url, monitor, up, message, verify_ssl, HTTP, kuma_operation
    )


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
    return push_state.push_status_if_needed(
        kuma_url,
        monitor,
        up,
        message,
        verify_ssl,
        state,
        heartbeat_interval,
        sync_interval,
        sender=push_status,
        now=time.time,
    )


_clean_shelly_name = integration_shelly._clean_shelly_name
_best_shelly_group_name = integration_shelly._best_shelly_group_name


def discover_shelly_devices() -> list[Dict[str, str]]:
    return integration_shelly.discover_shelly_devices(HAWebSocket, LOG)


def sync_addons(opts, api, monitors, default_notification_ids, state):
    integration_addons.sync(
        opts,
        api,
        monitors,
        default_notification_ids,
        state,
        supervisor_get,
        ensure_push_monitor,
        push_status_if_needed,
        LOG,
    )


def sync_shelly(opts, api, monitors, default_notification_ids, state):
    integration_shelly.sync_shelly(
        opts,
        api,
        monitors,
        default_notification_ids,
        state,
        discover_shelly_devices,
        ensure_ping_monitor,
        LOG,
    )


def discover_unifi_network_devices() -> list[Dict[str, str]]:
    return integration_unifi.discover_unifi_network_devices(
        HAWebSocket, HA_CONFIG_ENTRIES, LOG,
    )


def sync_unifi_network_devices(opts, api, monitors, default_notification_ids, state):
    integration_unifi.sync_unifi_network_devices(
        opts,
        api,
        monitors,
        default_notification_ids,
        state,
        discover_unifi_network_devices,
        ensure_ping_monitor,
        LOG,
    )


def discover_fritz_network_devices() -> list[Dict[str, str]]:
    return integration_fritz.discover_fritz_network_devices(
        HAWebSocket,
        _config_entry_hosts_from_storage,
        _device_has_identifier,
        _is_private_or_local_host,
        _device_mac_from_registry,
        LOG,
    )


def sync_fritz_network_devices(opts, api, monitors, default_notification_ids, state):
    integration_fritz.sync_fritz_network_devices(
        opts,
        api,
        monitors,
        default_notification_ids,
        state,
        discover_fritz_network_devices,
        ensure_ping_monitor,
        LOG,
    )


def discover_fully_kiosk_devices() -> list[Dict[str, str]]:
    return integration_fully_kiosk.discover_fully_kiosk_devices(
        HAWebSocket, _config_entry_hosts_from_storage, LOG,
    )


def sync_fully_kiosk_devices(opts, api, monitors, default_notification_ids, state):
    integration_fully_kiosk.sync_fully_kiosk_devices(
        opts,
        api,
        monitors,
        default_notification_ids,
        state,
        discover_fully_kiosk_devices,
        ensure_ping_monitor,
        LOG,
    )


def discover_homematic_ip_infrastructure() -> Dict[str, Any]:
    return integration_homematic.discover_homematic_ip_infrastructure(
        HAWebSocket,
        _config_entry_hosts_from_storage,
        _device_has_identifier,
        _is_private_or_local_host,
        LOG,
    )


def sync_homematic_ip_infrastructure(opts, api, monitors, default_notification_ids, state):
    integration_homematic.sync_homematic_ip_infrastructure(
        opts,
        api,
        monitors,
        default_notification_ids,
        state,
        discover_homematic_ip_infrastructure,
        ensure_ping_monitor,
        ensure_push_monitor,
        _push_effective_up,
        push_status_if_needed,
        LOG,
    )


def discover_matter_devices() -> list[Dict[str, Any]]:
    return integration_matter.discover_matter_devices(
        HAWebSocket, _entity_domain, LOG,
    )


def sync_matter_devices(opts, api, monitors, default_notification_ids, state):
    integration_matter.sync_matter_devices(
        opts,
        api,
        monitors,
        default_notification_ids,
        state,
        discover_matter_devices,
        ensure_push_monitor,
        _push_effective_up,
        push_status_if_needed,
        LOG,
    )


def discover_e3dc_devices() -> list[Dict[str, str]]:
    return integration_e3dc.discover_e3dc_devices(
        HAWebSocket,
        _config_entry_hosts_from_storage,
        _is_private_or_local_host,
        LOG,
    )


def sync_e3dc_devices(opts, api, monitors, default_notification_ids, state):
    integration_e3dc.sync_e3dc_devices(
        opts,
        api,
        monitors,
        default_notification_ids,
        state,
        discover_e3dc_devices,
        ensure_ping_monitor,
        LOG,
    )


def discover_overkiz_devices() -> Dict[str, Any]:
    return integration_overkiz.discover_overkiz_devices(
        HAWebSocket, _config_entry_hosts_from_storage, _entity_domain, LOG,
    )


def sync_overkiz_devices(opts, api, monitors, default_notification_ids, state):
    integration_overkiz.sync_overkiz_devices(
        opts,
        api,
        monitors,
        default_notification_ids,
        state,
        discover_overkiz_devices,
        ensure_ping_monitor,
        ensure_push_monitor,
        _push_effective_up,
        push_status_if_needed,
        LOG,
    )


def discover_hue(include_devices: bool = True) -> Dict[str, Any]:
    return integration_hue.discover_hue(
        include_devices, HAWebSocket, _config_entry_hosts_from_storage,
        _entity_domain, LOG,
    )


def sync_hue(opts, api, monitors, default_notification_ids, state):
    integration_hue.sync_hue(
        opts, api, monitors, default_notification_ids, state, discover_hue,
        ensure_ping_monitor, ensure_push_monitor, _push_effective_up,
        push_status_if_needed, LOG,
    )


def discover_smlight_devices() -> list[Dict[str, Any]]:
    return integration_smlight.discover_smlight_devices(
        HAWebSocket, _config_entry_hosts_from_storage, LOG,
    )


def sync_smlight_devices(opts, api, monitors, default_notification_ids, state):
    integration_smlight.sync_smlight_devices(
        opts, api, monitors, default_notification_ids, state,
        discover_smlight_devices, ensure_ping_monitor, LOG,
    )


def discover_stiebel_eltron() -> list[Dict[str, Any]]:
    return integration_stiebel_eltron.discover_stiebel_eltron(
        HAWebSocket, _config_entry_hosts_from_storage, LOG,
    )


def sync_stiebel_eltron(opts, api, monitors, default_notification_ids, state):
    integration_stiebel_eltron.sync_stiebel_eltron(
        opts, api, monitors, default_notification_ids, state,
        discover_stiebel_eltron, ensure_ping_monitor, LOG,
    )


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



_push_effective_up = push_state.push_effective_up


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
