"""Synology DSM discovery and Ping synchronization."""

from typing import Any, Dict


def discover_synology_dsm(
    ha_websocket, config_entry_hosts_from_storage, log,
) -> list[Dict[str, Any]]:
    """
    Discover physical Synology NAS systems from the native `synology_dsm`
    integration.

    Only the root NAS device for a config entry is considered. Drive, M.2,
    USB-disk and volume child devices are ignored by requiring `via_device_id`
    to be empty and a native `synology_dsm` identifier.
    """
    with ha_websocket() as ha:
        entries = ha.call(
            {"type": "config_entries/get", "domain": "synology_dsm"}
        ) or []
        devices = ha.call({"type": "config/device_registry/list"}) or []

    entry_ids = {str(e.get("entry_id")) for e in entries if e.get("entry_id")}
    storage_hosts = config_entry_hosts_from_storage("synology_dsm", entry_ids)

    result = []
    seen_hosts = set()

    for entry in entries:
        eid = str(entry.get("entry_id") or "")
        data = entry.get("data") or {}
        host = str(data.get("host") or storage_hosts.get(eid) or "").strip()

        # Old/stale entries can still exist without usable data.
        if not host:
            log.info(
                "Skipping Synology DSM config entry '%s' (%s): no host configured",
                str(entry.get("title") or "Synology DSM"),
                eid or "unknown-entry",
            )
            continue

        if host.lower() in seen_hosts:
            log.info("Skipping duplicate Synology DSM host %s", host)
            continue
        seen_hosts.add(host.lower())

        root_device = None
        for device in devices:
            dev_eid = str(device.get("config_entry_id") or "")
            dev_entries = {str(x) for x in (device.get("config_entries") or [])}
            if dev_eid != eid and eid not in dev_entries:
                continue

            if device.get("via_device_id"):
                continue

            identifiers = device.get("identifiers") or []
            has_native_identifier = any(
                isinstance(i, (list, tuple))
                and len(i) >= 2
                and str(i[0]) == "synology_dsm"
                for i in identifiers
            )
            if not has_native_identifier:
                continue

            root_device = device
            break

        if root_device:
            name = str(
                root_device.get("name_by_user")
                or root_device.get("name")
                or root_device.get("model")
                or "NAS"
            ).strip()
            model = str(root_device.get("model") or "").strip()
        else:
            name = "NAS"
            model = ""

        result.append({
            "entry_id": eid,
            "name": name,
            "model": model,
            "host": host,
        })

    return sorted(result, key=lambda d: d["name"].lower())


def sync_synology_dsm(
    opts, api, monitors, default_notification_ids, state,
    discover_devices, ensure_ping_monitor, log,
):
    devices = discover_devices()
    log.info(
        "Home Assistant returned %d physical Synology NAS device(s)",
        len(devices),
    )

    for device in devices:
        monitor_name = f'{opts["synology_monitor_prefix"]}{device["name"]}'
        ensure_ping_monitor(
            api,
            monitors,
            monitor_name,
            device["host"],
            opts["synology_ping_interval"],
            opts["synology_max_retries"],
            default_notification_ids,
            state=state,
            identity=f'synology_dsm:{device["entry_id"]}',
        )

        log.info(
            "%s -> PING %s (source=synology_dsm.config_entry.host, model=%s)",
            monitor_name,
            device["host"],
            device["model"] or "unknown",
        )

    state["synology_dsm"] = {
        d["entry_id"]: {
            "name": d["name"],
            "model": d["model"],
            "host": d["host"],
        }
        for d in devices
    }
