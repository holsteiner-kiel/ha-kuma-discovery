"""ESPHome device discovery and Ping synchronization."""

from typing import Any, Dict


def discover_esphome_devices(
    ha_websocket, config_entry_hosts_from_storage, log,
) -> list[Dict[str, Any]]:
    """
    Discover physical ESPHome devices from native `esphome` config entries.

    The config entry itself is the source of truth for monitor name and host.
    This avoids duplicate Bluetooth-proxy helper devices and ignores the
    ESPHome Device Builder add-on device.
    """
    with ha_websocket() as ha:
        entries = ha.call(
            {"type": "config_entries/get", "domain": "esphome"}
        ) or []

    entry_ids = {str(e.get("entry_id")) for e in entries if e.get("entry_id")}
    storage_hosts = config_entry_hosts_from_storage("esphome", entry_ids)

    result = []
    seen_hosts = set()

    for entry in entries:
        eid = str(entry.get("entry_id") or "")
        title = str(entry.get("title") or "ESPHome").strip()
        data = entry.get("data") or {}

        # HA may redact config-entry data over WebSocket. Fall back to the
        # local config-entry storage exactly like SMLIGHT/Synology.
        host = str(data.get("host") or storage_hosts.get(eid) or "").strip()
        if not host:
            log.info(
                "Skipping ESPHome config entry '%s' (%s): no host configured",
                title,
                eid or "unknown-entry",
            )
            continue

        host_key = host.lower()
        if host_key in seen_hosts:
            log.info(
                "Skipping duplicate ESPHome host %s from config entry '%s'",
                host,
                title,
            )
            continue
        seen_hosts.add(host_key)

        result.append({
            "entry_id": eid,
            "name": title,
            "host": host,
            "port": int(data.get("port") or 6053),
            "device_name": str(data.get("device_name") or "").strip(),
        })

    return sorted(result, key=lambda d: d["name"].lower())


def sync_esphome_devices(
    opts, api, monitors, default_notification_ids, state,
    discover_devices, ensure_ping_monitor, log,
):
    devices = discover_devices()
    log.info(
        "Home Assistant returned %d ESPHome device(s) with an explicit host",
        len(devices),
    )

    for device in devices:
        monitor_name = f'{opts["esphome_monitor_prefix"]}{device["name"]}'
        ensure_ping_monitor(
            api,
            monitors,
            monitor_name,
            device["host"],
            opts["esphome_ping_interval"],
            opts["esphome_max_retries"],
            default_notification_ids,
            state=state,
            identity=f'esphome:{device["entry_id"]}',
        )

        log.info(
            "%s -> PING %s (source=esphome.config_entry.host, api_port=%s)",
            monitor_name,
            device["host"],
            device["port"],
        )

    state["esphome"] = {
        d["entry_id"]: {
            "name": d["name"],
            "host": d["host"],
            "port": d["port"],
            "device_name": d["device_name"],
        }
        for d in devices
    }
