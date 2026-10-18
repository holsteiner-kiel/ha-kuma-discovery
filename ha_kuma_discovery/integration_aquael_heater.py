"""Native Aquael Heater availability monitoring."""

from typing import Any, Dict


def discover_aquael_heater_devices(ha_websocket, log) -> list[Dict[str, Any]]:
    """Discover physical Aquael Heater devices through their native Connectivity entity."""
    with ha_websocket() as ha:
        entries = ha.call({"type": "config_entries/get", "domain": "aquael_heater"}) or []
        if not entries:
            log.info("No Aquael Heater integration config entry found")
            return []
        devices = ha.call({"type": "config/device_registry/list"}) or []
        entities = ha.call({"type": "config/entity_registry/list"}) or []
        states = ha.call({"type": "get_states"}) or []

    entry_ids = {str(entry.get("entry_id") or "") for entry in entries if entry.get("entry_id")}
    states_by_entity = {str(item.get("entity_id") or ""): item for item in states if item.get("entity_id")}
    devices_by_id = {str(device.get("id") or ""): device for device in devices if device.get("id")}
    found = []

    for entity in entities:
        if entity.get("platform") != "aquael_heater":
            continue
        if str(entity.get("config_entry_id") or "") not in entry_ids:
            continue
        if entity.get("disabled_by") is not None:
            continue
        if str(entity.get("translation_key") or "") != "connectivity":
            continue
        entity_id = str(entity.get("entity_id") or "")
        if not entity_id.startswith("binary_sensor."):
            continue
        device = devices_by_id.get(str(entity.get("device_id") or ""))
        if not device or device.get("disabled_by") is not None:
            continue
        device_id = str(device.get("id") or "")
        name = str(device.get("name_by_user") or device.get("name") or device.get("model") or device_id).strip()
        current = states_by_entity.get(entity_id) or {}
        found.append({
            "device_id": device_id,
            "name": name,
            "model": str(device.get("model") or "").strip(),
            "connectivity_entity": entity_id,
            "state": str(current.get("state") or "unknown").lower(),
        })

    return sorted(found, key=lambda item: (item["name"].lower(), item["device_id"]))


def sync_aquael_heater_devices(
    opts, api, monitors, default_notification_ids, state, discover_devices,
    ensure_push_monitor, push_effective_up, push_status_if_needed, log,
):
    devices = discover_devices()
    prefix = opts["aquael_heater_monitor_prefix"]
    for device in devices:
        monitor_name = f'{prefix}{device["name"]}'
        monitor = ensure_push_monitor(
            api, monitors, monitor_name, opts["heartbeat_interval"],
            default_notification_ids, state=state,
            identity=f'aquael_heater:{device["device_id"]}',
        )
        observed_up = device["state"] == "on"
        effective_up, down_cycles = push_effective_up(
            state, "aquael_heater", device["device_id"], observed_up,
            opts["push_down_grace_cycles"],
        )
        message = f'HA {device["connectivity_entity"]}: {device["state"]}'
        if not observed_up and effective_up:
            message += f' | DOWN grace {down_cycles}/{opts["push_down_grace_cycles"]}'
        push_status_if_needed(
            opts["kuma_url"], monitor, effective_up, message, opts["verify_ssl"],
            state, opts["heartbeat_interval"], opts["sync_interval"],
        )
        log.info("%s -> %s via %s (observed=%s, down_grace=%d/%d, HA state=%s)",
                 monitor_name, "UP" if effective_up else "DOWN",
                 device["connectivity_entity"], "UP" if observed_up else "DOWN",
                 down_cycles, opts["push_down_grace_cycles"], device["state"])
    state["aquael_heater"] = {"devices": {
        device["device_id"]: {
            "name": device["name"], "model": device["model"],
            "connectivity_entity": device["connectivity_entity"],
        } for device in devices
    }}
