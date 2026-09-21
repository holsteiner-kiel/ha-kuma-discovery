"""MQTT and Zigbee2MQTT physical-device discovery and Push synchronization."""

import re
from typing import Any, Dict


def discover_mqtt_physical_devices(
    ha_websocket, entity_domain, log,
) -> Dict[str, list[Dict[str, Any]]]:
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
    with ha_websocket() as ha:
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
            log.debug(
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

            domain = entity_domain(entity_id)
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
            log.info(
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


def _sync_mqtt_device_list(
    opts,
    api,
    monitors,
    default_notification_ids,
    state,
    devices,
    prefix,
    state_key,
    ensure_push_monitor,
    push_effective_up,
    push_status_if_needed,
    log,
):
    log.info(
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

        effective_up, down_cycles = push_effective_up(
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

        log.info(
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


def sync_mqtt_devices(
    opts, api, monitors, default_notification_ids, state,
    discover_devices, sync_device_list,
):
    data = discover_devices()

    if opts["discover_zigbee2mqtt_devices"]:
        sync_device_list(
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
        sync_device_list(
            opts,
            api,
            monitors,
            default_notification_ids,
            state,
            data["mqtt"],
            opts["mqtt_monitor_prefix"],
            "mqtt",
        )
