"""SMLIGHT coordinator discovery and Ping synchronization."""

from typing import Any, Dict


def discover_smlight_devices(
    ha_websocket, config_entry_hosts_from_storage, log,
) -> list[Dict[str, Any]]:
    """
    Discover physical SMLIGHT coordinators from the native Home Assistant
    `smlight` integration.

    The config entry's explicit `data.host` is the authoritative Ping target.
    Entries without a host are skipped. This avoids pulling duplicate devices
    from UniFi, Uptime Kuma or Zigbee2MQTT.
    """
    with ha_websocket() as ha:
        entries = ha.call({"type": "config_entries/get", "domain": "smlight"}) or []

    entry_ids = {str(e.get("entry_id")) for e in entries if e.get("entry_id")}
    storage_hosts = config_entry_hosts_from_storage("smlight", entry_ids)

    result = []
    seen_hosts = set()

    for entry in entries:
        eid = str(entry.get("entry_id") or "")
        title = str(entry.get("title") or "SMLIGHT").strip()

        # Home Assistant's WebSocket config_entries/get response may redact
        # config-entry data. Prefer data.host when present, otherwise fall back
        # to the local core.config_entries storage file.
        data = entry.get("data") or {}
        host = str(data.get("host") or storage_hosts.get(eid) or "").strip()

        if not host:
            log.info(
                "Skipping SMLIGHT config entry '%s' (%s): no host configured",
                title,
                eid or "unknown-entry",
            )
            continue

        host_key = host.lower()
        if host_key in seen_hosts:
            log.info(
                "Skipping duplicate SMLIGHT host %s from config entry '%s'",
                host,
                title,
            )
            continue
        seen_hosts.add(host_key)

        result.append({
            "entry_id": eid,
            "name": title,
            "host": host,
        })

    return sorted(result, key=lambda d: d["name"].lower())


def sync_smlight_devices(
    opts, api, monitors, default_notification_ids, state,
    discover_devices, ensure_ping_monitor, log,
):
    devices = discover_devices()
    log.info(
        "Home Assistant returned %d SMLIGHT device(s) with an explicit host",
        len(devices),
    )

    for device in devices:
        monitor_name = f'{opts["smlight_monitor_prefix"]}{device["name"]}'
        ensure_ping_monitor(
            api,
            monitors,
            monitor_name,
            device["host"],
            opts["smlight_ping_interval"],
            opts["smlight_max_retries"],
            default_notification_ids,
            state=state,
            identity=f'smlight:{device["entry_id"]}',
        )

        log.info(
            "%s -> PING %s (source=smlight.config_entry.host, entry_id=%s)",
            monitor_name,
            device["host"],
            device["entry_id"],
        )

    state["smlight"] = {
        d["entry_id"]: {
            "name": d["name"],
            "host": d["host"],
        }
        for d in devices
    }
