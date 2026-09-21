"""Home Connect Local and Cloud appliance monitoring."""

import ipaddress
import re
from typing import Any, Dict


_CONNECTED_SUFFIX = "bsh.common.appliance.connected"


def _valid_local_host(value: Any) -> str:
    """Accept only a direct local IP address or hostname from integration data."""
    host = str(value or "").strip()
    if not host or "://" in host or "/" in host or "@" in host:
        return ""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        labels = host.rstrip(".").split(".")
        valid = bool(host and len(host) <= 253 and labels and all(
            re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label)
            for label in labels
        ))
        return host if valid else ""
    if address.is_unspecified or address.is_multicast or address.is_loopback:
        return ""
    return host if address.is_private or address.is_link_local else ""


def _identifiers(device: Dict[str, Any], domain: str) -> set[str]:
    return {
        str(identifier[1]).strip().lower()
        for identifier in device.get("identifiers") or []
        if isinstance(identifier, (list, tuple)) and len(identifier) >= 2
        and str(identifier[0]).lower() == domain and str(identifier[1]).strip()
    }


def _appliance_ids(value: Any) -> set[str]:
    """Normalize native appliance identifiers without relying on visible names."""
    raw = str(value or "").strip().lower()
    if not raw:
        return set()
    result = {raw}
    if raw.endswith(_CONNECTED_SUFFIX):
        result.add(raw[:-len(_CONNECTED_SUFFIX)].rstrip("._:-"))
    return {item for item in result if item}


def _entry_ids(device: Dict[str, Any]) -> set[str]:
    result = {str(item) for item in device.get("config_entries") or [] if item}
    if device.get("config_entry_id"):
        result.add(str(device["config_entry_id"]))
    return result


def _name(device: Dict[str, Any], fallback: str) -> str:
    return str(
        device.get("name_by_user") or device.get("name") or device.get("model") or fallback
    ).strip()


def discover_home_connect_local(
    ha_websocket, config_entry_hosts_from_storage, log,
) -> Dict[str, Any]:
    """Discover local appliances directly from their ``homeconnect_ws`` entries."""
    with ha_websocket() as ha:
        entries = ha.call({"type": "config_entries/get", "domain": "homeconnect_ws"}) or []
        if not entries:
            return {"devices": [], "appliance_ids": set()}
        devices = ha.call({"type": "config/device_registry/list"}) or []

    entry_by_id = {str(entry["entry_id"]): entry for entry in entries if entry.get("entry_id")}
    # WebSocket config entries redact private data. Read only data.host for
    # matching Home Connect Local entries from read-only HA storage.
    storage_hosts = config_entry_hosts_from_storage("homeconnect_ws", set(entry_by_id))
    device_by_entry = {}
    for device in devices:
        if device.get("entry_type") is not None or device.get("disabled_by") is not None:
            continue
        for entry_id in _entry_ids(device) & entry_by_id.keys():
            if _identifiers(device, "homeconnect_ws"):
                device_by_entry.setdefault(entry_id, device)

    result, appliance_ids, seen = [], set(), set()
    for entry_id, entry in entry_by_id.items():
        device = device_by_entry.get(entry_id, {})
        identifiers = _identifiers(device, "homeconnect_ws") | _appliance_ids(entry.get("unique_id"))
        stable_id = sorted(identifiers)[0] if identifiers else entry_id
        appliance_ids.update(identifiers or {stable_id})
        if stable_id in seen:
            continue
        seen.add(stable_id)
        host = _valid_local_host(
            (entry.get("data") or {}).get("host") or storage_hosts.get(entry_id)
        )
        if not host:
            log.info("Skipping Home Connect Local appliance %s: no usable data.host", stable_id)
            continue
        result.append({
            "device_id": str(device.get("id") or stable_id),
            "appliance_id": stable_id,
            "name": _name(device, str(entry.get("title") or stable_id)),
            "host": host,
        })
    return {"devices": sorted(result, key=lambda item: item["name"].lower()),
            "appliance_ids": appliance_ids}


def discover_home_connect_cloud(ha_websocket, log, local_appliance_ids) -> list[Dict[str, Any]]:
    """Discover Cloud appliances with an enabled semantic connectivity entity."""
    with ha_websocket() as ha:
        entries = ha.call({"type": "config_entries/get", "domain": "home_connect"}) or []
        if not entries:
            return []
        devices = ha.call({"type": "config/device_registry/list"}) or []
        entities = ha.call({"type": "config/entity_registry/list"}) or []
        states = ha.call({"type": "get_states"}) or []

    entry_ids = {str(entry.get("entry_id")) for entry in entries if entry.get("entry_id")}
    if not entry_ids:
        return []
    states_by_entity = {str(state.get("entity_id")): state for state in states if state.get("entity_id")}
    entities_by_device: Dict[str, list[Dict[str, Any]]] = {}
    for entity in entities:
        if str(entity.get("platform") or "") != "home_connect" or entity.get("disabled_by") is not None:
            continue
        if not (_entry_ids(entity) & entry_ids):
            continue
        device_id = str(entity.get("device_id") or "")
        if device_id:
            entities_by_device.setdefault(device_id, []).append(entity)

    result = []
    local_ids = {item.lower() for item in local_appliance_ids}
    for device in devices:
        if device.get("entry_type") is not None or device.get("disabled_by") is not None:
            continue
        if not (_entry_ids(device) & entry_ids):
            continue
        appliance_ids = set()
        for identifier in _identifiers(device, "home_connect"):
            appliance_ids.update(_appliance_ids(identifier))
        if not appliance_ids:
            continue
        if appliance_ids & local_ids:
            continue
        device_id = str(device.get("id") or "")
        connectivity = []
        for entity in entities_by_device.get(device_id, []):
            unique_id = str(entity.get("unique_id") or "").lower()
            semantic = (
                str(entity.get("original_device_class") or "").lower() == "connectivity"
                or unique_id.endswith(_CONNECTED_SUFFIX)
            )
            if not semantic or not str(entity.get("entity_id") or "").startswith("binary_sensor."):
                continue
            connectivity.append(entity)
        if not connectivity:
            continue
        entity = sorted(connectivity, key=lambda item: str(item.get("entity_id") or ""))[0]
        current = states_by_entity.get(str(entity.get("entity_id"))) or {}
        observed_state = str(current.get("state") or "unknown").lower()
        result.append({
            "device_id": device_id,
            "appliance_id": sorted(appliance_ids)[0],
            "name": _name(device, sorted(appliance_ids)[0]),
            "entity_id": str(entity.get("entity_id")),
            "state": observed_state,
            "up": observed_state == "on",
        })
    return sorted(result, key=lambda item: item["name"].lower())


def sync_home_connect_local(opts, api, monitors, default_notification_ids, state, discover_devices, ensure_ping_monitor, log):
    data = discover_devices()
    devices = data.get("devices") or []
    for device in devices:
        monitor_name = f'{opts["homeconnect_local_monitor_prefix"]}{device["name"]}'
        ensure_ping_monitor(api, monitors, monitor_name, device["host"],
                            opts["homeconnect_local_ping_interval"], opts["homeconnect_local_max_retries"],
                            default_notification_ids, state=state,
                            identity=f'homeconnect_ws:{device["appliance_id"]}')
        log.info("%s -> PING %s (source=homeconnect_ws.config_entry.data.host)", monitor_name, device["host"])
    state["homeconnect_local"] = {device["appliance_id"]: {"name": device["name"], "host": device["host"]}
                                  for device in devices}


def sync_home_connect_cloud(opts, api, monitors, default_notification_ids, state, discover_devices,
                            ensure_push_monitor, push_effective_up, push_status_if_needed, log):
    devices = discover_devices()
    for device in devices:
        monitor_name = f'{opts["homeconnect_monitor_prefix"]}{device["name"]}'
        monitor = ensure_push_monitor(api, monitors, monitor_name, opts["heartbeat_interval"],
                                      default_notification_ids, state=state,
                                      identity=f'home_connect:{device["appliance_id"]}')
        effective_up, down_cycles = push_effective_up(state, "home_connect", device["appliance_id"],
                                                       device["up"], opts["push_down_grace_cycles"])
        message = f'HA Home Connect connectivity: {device["entity_id"]}={device["state"]}'
        if not device["up"] and effective_up:
            message += f' | DOWN grace {down_cycles}/{opts["push_down_grace_cycles"]}'
        push_status_if_needed(opts["kuma_url"], monitor, effective_up, message, opts["verify_ssl"], state,
                              opts["heartbeat_interval"], opts["sync_interval"])
        log.info("%s -> %s (observed=%s, down_grace=%d/%d, device_id=%s)", monitor_name,
                 "UP" if effective_up else "DOWN", "UP" if device["up"] else "DOWN", down_cycles,
                 opts["push_down_grace_cycles"], device["appliance_id"])
    state["home_connect"] = {device["appliance_id"]: {"name": device["name"], "entity_id": device["entity_id"]}
                             for device in devices}
