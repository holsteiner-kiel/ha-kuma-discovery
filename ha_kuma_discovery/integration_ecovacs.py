"""Ecovacs device discovery through the native diagnostic network IP entity."""

import ipaddress
from typing import Any, Dict


def _entry_ids(item: Dict[str, Any]) -> set[str]:
    result = {str(value) for value in item.get("config_entries") or [] if value}
    if item.get("config_entry_id"):
        result.add(str(item["config_entry_id"]))
    return result


def _ecovacs_identifier(device: Dict[str, Any]) -> str:
    values = sorted(str(identifier[1]) for identifier in device.get("identifiers") or []
                    if isinstance(identifier, (list, tuple)) and len(identifier) >= 2
                    and str(identifier[0]).lower() == "ecovacs" and identifier[1])
    return values[0] if values else ""


def _valid_ip(value: Any) -> str:
    candidate = str(value or "").strip()
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return ""
    if address.is_unspecified or address.is_multicast or address.is_loopback:
        return ""
    return candidate


def discover_ecovacs_devices(ha_websocket, log) -> list[Dict[str, Any]]:
    with ha_websocket() as ha:
        entries = ha.call({"type": "config_entries/get", "domain": "ecovacs"}) or []
        if not entries:
            return []
        devices = ha.call({"type": "config/device_registry/list"}) or []
        entities = ha.call({"type": "config/entity_registry/list"}) or []
        states = ha.call({"type": "get_states"}) or []
    entry_ids = {str(entry.get("entry_id")) for entry in entries if entry.get("entry_id")}
    states_by_entity = {str(state.get("entity_id")): state for state in states if state.get("entity_id")}
    entities_by_device: Dict[str, list[Dict[str, Any]]] = {}
    for entity in entities:
        if str(entity.get("platform") or "") != "ecovacs" or not (_entry_ids(entity) & entry_ids):
            continue
        device_id = str(entity.get("device_id") or "")
        if device_id and str(entity.get("translation_key") or "") == "network_ip":
            entities_by_device.setdefault(device_id, []).append(entity)

    result = []
    for device in devices:
        if device.get("entry_type") is not None or device.get("disabled_by") is not None or not (_entry_ids(device) & entry_ids):
            continue
        stable_id = _ecovacs_identifier(device)
        if not stable_id:
            continue
        candidates = sorted(entities_by_device.get(str(device.get("id") or ""), []),
                            key=lambda item: str(item.get("entity_id") or ""))
        if not candidates:
            continue
        entity = candidates[0]
        disabled = entity.get("disabled_by") is not None
        state = str((states_by_entity.get(str(entity.get("entity_id"))) or {}).get("state") or "").strip()
        result.append({
            "device_id": str(device.get("id") or stable_id), "ecovacs_id": stable_id,
            "name": str(device.get("name_by_user") or device.get("name") or device.get("model") or stable_id).strip(),
            "entity_id": str(entity.get("entity_id") or ""), "disabled": disabled,
            "host": _valid_ip(state), "raw_state": state,
        })
    return sorted(result, key=lambda item: item["name"].lower())


def sync_ecovacs_devices(opts, api, monitors, default_notification_ids, state, discover_devices,
                         ensure_ping_monitor, log):
    ignored = opts.get("ecovacs_ignore_set")
    if ignored is None:
        ignored = {item.strip().lower() for item in str(opts.get("ecovacs_ignore", "")).split(",") if item.strip()}
    managed = []
    for device in discover_devices():
        if device["ecovacs_id"].lower() in ignored:
            log.debug("Skipping ignored Ecovacs device %s", device["ecovacs_id"])
            continue
        if device["disabled"]:
            log.warning('Ecovacs: %s skipped because its IP Address diagnostic entity (network_ip) is disabled. Enable the Ecovacs "IP Address" diagnostic entity in Home Assistant to enable Ping monitoring, or add device %s to ecovacs_ignore.',
                        device["name"], device["ecovacs_id"])
            continue
        if not device["host"]:
            log.warning("Ecovacs: %s skipped because its network_ip diagnostic entity has no valid IP currently available (device %s).",
                        device["name"], device["ecovacs_id"])
            continue
        monitor_name = f'{opts["ecovacs_monitor_prefix"]}{device["name"]}'
        ensure_ping_monitor(api, monitors, monitor_name, device["host"], opts["ecovacs_ping_interval"],
                            opts["ecovacs_max_retries"], default_notification_ids, state=state,
                            identity=f'ecovacs:{device["ecovacs_id"]}')
        managed.append(device)
        log.info("%s -> PING %s (source=ecovacs.network_ip)", monitor_name, device["host"])
    state["ecovacs"] = {device["ecovacs_id"]: {"name": device["name"], "host": device["host"]}
                        for device in managed}
