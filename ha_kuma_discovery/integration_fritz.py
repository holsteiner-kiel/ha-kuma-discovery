"""FRITZ! network infrastructure discovery and Ping synchronization."""

from typing import Dict


def discover_fritz_network_devices(
    ha_websocket, config_entry_hosts_from_storage, device_has_identifier,
    is_private_or_local_host, device_mac_from_registry, log,
) -> list[Dict[str, str]]:
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
    with ha_websocket() as ha:
        entries = ha.call({"type": "config_entries/get", "domain": "fritz"}) or []
        fritz_entry_ids = {
            str(e.get("entry_id"))
            for e in entries
            if e.get("entry_id")
        }
        devices = ha.call({"type": "config/device_registry/list"}) or []

    if not fritz_entry_ids:
        log.info("No FRITZ!Box Tools config entry found")
        return []

    fritz_entry_hosts = config_entry_hosts_from_storage("fritz", fritz_entry_ids)

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
        if not device_has_identifier(device, "fritz"):
            continue

        host = None
        source_entry = None
        for eid in matching_entries:
            candidate = str(fritz_entry_hosts.get(eid) or "").strip()
            if candidate and is_private_or_local_host(candidate):
                host = candidate
                source_entry = eid
                break

        if not host:
            log.warning(
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

        mac = device_mac_from_registry(device) or ""
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



def sync_fritz_network_devices(
    opts, api, monitors, default_notification_ids, state,
    discover_devices, ensure_ping_monitor, log,
):
    devices = discover_devices()
    log.info(
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
        log.info(
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


