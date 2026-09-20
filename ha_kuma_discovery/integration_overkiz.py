"""Overkiz/Somfy hub and child-device monitoring."""

from typing import Any, Dict


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


def discover_overkiz_devices(
    ha_websocket, config_entry_hosts_from_storage, entity_domain, log,
) -> Dict[str, Any]:
    """
    Discover the local Somfy/Overkiz hub and its physical child devices.

    - Hub (TaHoma Switch): Ping the local host from overkiz config-entry data.host.
    - Somfy devices: Push monitors based only on native Overkiz entity availability.
    """
    with ha_websocket() as ha:
        entries = ha.call({"type": "config_entries/get", "domain": "overkiz"}) or []
        devices = ha.call({"type": "config/device_registry/list"}) or []
        entities = ha.call({"type": "config/entity_registry/list"}) or []
        states = ha.call({"type": "get_states"}) or []

    entry_ids = {str(e.get("entry_id")) for e in entries if e.get("entry_id")}
    if not entry_ids:
        log.info("No Overkiz config entry found")
        return {}

    entry_hosts = config_entry_hosts_from_storage("overkiz", entry_ids)
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
            log.info(
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



def sync_overkiz_devices(
    opts, api, monitors, default_notification_ids, state,
    discover_devices, ensure_ping_monitor, ensure_push_monitor,
    push_effective_up, push_status_if_needed, log,
):
    data = discover_devices()
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
        log.info(
            "%s -> PING %s (source=%s)",
            monitor_name,
            hub["host"],
            hub["source"],
        )

    children = data.get("children") or []
    log.info("Home Assistant returned %d Overkiz/Somfy child device(s)", len(children))

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

        effective_up, down_cycles = push_effective_up(
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

        log.info(
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


