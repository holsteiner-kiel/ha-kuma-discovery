"""Matter device discovery and availability Push synchronization."""

from typing import Any, Dict


def discover_matter_devices(ha_websocket, entity_domain, log) -> list[Dict[str, Any]]:
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
    with ha_websocket() as ha:
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
        log.info("No Matter integration config entry found")
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
            domain = entity_domain(entity_id)
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



def sync_matter_devices(
    opts, api, monitors, default_notification_ids, state,
    discover_devices, ensure_push_monitor, push_effective_up,
    push_status_if_needed, log,
):
    devices = discover_devices()
    log.info("Home Assistant returned %d Matter device(s)", len(devices))

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

        effective_up, down_cycles = push_effective_up(
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

        log.info(
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


