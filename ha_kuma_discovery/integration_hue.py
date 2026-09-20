"""Philips Hue bridge and physical-device monitoring."""

from typing import Any, Dict


def discover_hue(
    include_devices: bool, ha_websocket, config_entry_hosts_from_storage, entity_domain, log,
) -> Dict[str, Any]:
    """
    Discover the Hue Bridge and optional Hue child devices.

    - Bridge: ping target comes directly from the Hue config entry's data.host.
    - Child devices: availability comes only from native Hue entities in HA.
    """
    with ha_websocket() as ha:
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
        log.info("No Hue config entry found")
        return {}

    entry_hosts = config_entry_hosts_from_storage("hue", entry_ids)
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
            log.debug(
                "Skipping logical Hue device '%s' (model=%s): no MAC connection",
                name,
                model or "unknown",
            )
            continue

        # Explicit extra guard for the logical Hue device types seen in HA.
        if model.strip().lower() in {"room", "zone"}:
            log.debug(
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



def sync_hue(
    opts, api, monitors, default_notification_ids, state, discover_devices,
    ensure_ping_monitor, ensure_push_monitor, push_effective_up,
    push_status_if_needed, log,
):
    data = discover_devices(include_devices=opts["discover_hue_devices"])
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
            log.info(
                "%s -> PING %s (source=hue.config_entry.host, title=%s)",
                monitor_name,
                bridge["host"],
                bridge["title"],
            )

    children = data.get("children") or []
    if opts["discover_hue_devices"]:
        log.info("Home Assistant returned %d Hue child device(s)", len(children))

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

            effective_up, down_cycles = push_effective_up(
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

            log.info(
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


