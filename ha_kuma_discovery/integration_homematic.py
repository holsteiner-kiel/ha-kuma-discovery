"""Homematic IP HCU and physical-device monitoring."""

from typing import Any, Dict


def discover_homematic_ip_infrastructure(
    ha_websocket, config_entry_hosts_from_storage, device_has_identifier,
    is_private_or_local_host, log,
) -> Dict[str, Any]:
    """Discover the HCU Ping target and native physical Connectivity devices."""
    with ha_websocket() as ha:
        entries = ha.call({"type": "config_entries/get", "domain": "hcu_integration"}) or []
        devices = ha.call({"type": "config/device_registry/list"}) or []
        entities = ha.call({"type": "config/entity_registry/list"}) or []
        states = ha.call({"type": "get_states"}) or []

    entry_ids = {str(e.get("entry_id")) for e in entries if e.get("entry_id")}
    if not entry_ids:
        log.info("No Homematic IP HCU integration config entry found")
        return {}

    entry_hosts = config_entry_hosts_from_storage("hcu_integration", entry_ids)
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
        if not device_has_identifier(device, "hcu_integration"):
            continue
        seen_devices.add(did)

        if model in {"HmIP-HCU1", "HmIP-HCU-1", "HmIP-HCU1-A"}:
            host = None
            source_entry = None
            for candidate_eid in matching:
                candidate = str(entry_hosts.get(candidate_eid) or "").strip()
                if candidate and is_private_or_local_host(candidate):
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
                log.warning("Homematic IP HCU '%s' has no usable local host", name)

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
                log.info("Skipping Homematic IP device '%s': no enabled Connectivity entity", name)
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



def sync_homematic_ip_infrastructure(
    opts, api, monitors, default_notification_ids, state,
    discover_infrastructure, ensure_ping_monitor, ensure_push_monitor,
    push_effective_up, push_status_if_needed, log,
):
    infra = discover_infrastructure()
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
        log.info(
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

        effective_up, down_cycles = push_effective_up(
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
        log.info(
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


