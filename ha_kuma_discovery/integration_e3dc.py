"""E3/DC controller discovery and Ping synchronization."""

from typing import Dict


def discover_e3dc_devices(
    ha_websocket, config_entry_hosts_from_storage,
    is_private_or_local_host, log,
) -> list[Dict[str, str]]:
    """
    Discover only the physical E3/DC system from the native/custom `e3dc_rscp`
    integration. Battery packs/modules exposed as child devices are ignored.

    The integration config-entry host is used directly as the ping target, so
    there is no dependency on UniFi, FRITZ!Box or any other network integration.
    """
    with ha_websocket() as ha:
        entries = ha.call({"type": "config_entries/get", "domain": "e3dc_rscp"}) or []
        devices = ha.call({"type": "config/device_registry/list"}) or []

    entry_ids = {str(e.get("entry_id")) for e in entries if e.get("entry_id")}
    if not entry_ids:
        log.info("No E3/DC RSCP config entry found")
        return []

    entry_hosts = config_entry_hosts_from_storage("e3dc_rscp", entry_ids)
    for entry in entries:
        eid = str(entry.get("entry_id") or "")
        host = str((entry.get("data") or {}).get("host") or "").strip()
        if eid and host:
            entry_hosts.setdefault(eid, host)

    result = []

    for device in devices:
        eid = str(device.get("config_entry_id") or "")
        legacy = {str(x) for x in (device.get("config_entries") or [])}
        matching = []
        if eid in entry_ids:
            matching.append(eid)
        matching.extend(sorted((legacy & entry_ids) - set(matching)))
        if not matching:
            continue

        # Only monitor the physical E3/DC controller.
        #
        # Battery packs/modules also carry e3dc_rscp identifiers, so the
        # identifier alone is not enough. The physical controller is the
        # top-level device and exposes a real MAC connection; child battery
        # devices do not.
        identifiers = device.get("identifiers") or []
        native_ids = [
            str(i[1])
            for i in identifiers
            if isinstance(i, (list, tuple))
            and len(i) >= 2
            and str(i[0]).lower() == "e3dc_rscp"
        ]
        if not native_ids:
            continue

        has_mac = any(
            isinstance(c, (list, tuple))
            and len(c) >= 2
            and str(c[0]).lower() == "mac"
            for c in (device.get("connections") or [])
        )
        if not has_mac:
            continue

        # Child devices such as battery packs/modules are linked via the main
        # E3/DC device. Exclude them even if a future integration version adds
        # extra connection metadata.
        if device.get("via_device_id"):
            continue

        host = None
        source_entry = None
        for candidate_eid in matching:
            candidate = str(entry_hosts.get(candidate_eid) or "").strip()
            if candidate and is_private_or_local_host(candidate):
                host = candidate
                source_entry = candidate_eid
                break

        if not host:
            log.warning(
                "E3/DC device '%s' has no usable local host in its e3dc_rscp config entry; skipping.",
                device.get("name_by_user") or device.get("name") or device.get("model") or "unknown",
            )
            continue

        raw_name = str(
            device.get("name_by_user")
            or device.get("name")
            or device.get("model")
            or "E3/DC"
        ).strip()
        # Display names look nicer with spaces than underscores.
        name = raw_name.replace("_", " ")

        result.append({
            "device_id": str(device.get("id") or ""),
            "name": name,
            "host": host,
            "model": str(device.get("model") or "").strip(),
            "serial": native_ids[0],
            "source": f"e3dc_rscp.config_entry.host:{source_entry}",
        })

    return sorted(result, key=lambda d: d["name"].lower())



def sync_e3dc_devices(
    opts, api, monitors, default_notification_ids, state,
    discover_devices, ensure_ping_monitor, log,
):
    devices = discover_devices()
    log.info("Home Assistant returned %d E3/DC device(s) with an address", len(devices))

    for device in devices:
        monitor_name = f'{opts["e3dc_monitor_prefix"]}{device["name"]}'
        ensure_ping_monitor(
            api,
            monitors,
            monitor_name,
            device["host"],
            opts["e3dc_ping_interval"],
            opts["e3dc_max_retries"],
            default_notification_ids,
            state=state,
            identity=f'e3dc:{device["device_id"]}',
        )
        log.info(
            "%s -> PING %s (model=%s, serial=%s, source=%s, device_id=%s)",
            monitor_name,
            device["host"],
            device["model"] or "unknown",
            device["serial"],
            device["source"],
            device["device_id"],
        )

    state["known_e3dc_device_ids"] = sorted(d["device_id"] for d in devices)
    state["e3dc_devices"] = {
        d["device_id"]: {
            "name": d["name"],
            "host": d["host"],
            "model": d["model"],
            "serial": d["serial"],
        }
        for d in devices
    }


