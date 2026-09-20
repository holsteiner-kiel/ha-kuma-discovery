"""Stiebel Eltron ISG discovery and Ping synchronization."""

import re
from typing import Any, Dict


def discover_stiebel_eltron(
    ha_websocket, config_entry_hosts_from_storage, log,
) -> list[Dict[str, Any]]:
    """
    Discover the native Stiebel Eltron ISG integration.

    The integration config entry provides the ISG host. The device registry is
    used only to derive the friendly physical device/model name (e.g. LWZ).
    Duplicate HACS/UPnP representations are ignored because only the native
    `stiebel_eltron_isg` config entry/device is considered.
    """
    with ha_websocket() as ha:
        entries = ha.call(
            {"type": "config_entries/get", "domain": "stiebel_eltron_isg"}
        ) or []
        devices = ha.call({"type": "config/device_registry/list"}) or []

    entry_ids = {str(e.get("entry_id")) for e in entries if e.get("entry_id")}
    storage_hosts = config_entry_hosts_from_storage(
        "stiebel_eltron_isg", entry_ids
    )

    result = []
    for entry in entries:
        eid = str(entry.get("entry_id") or "")
        data = entry.get("data") or {}
        host = str(data.get("host") or storage_hosts.get(eid) or "").strip()
        if not host:
            log.info(
                "Skipping Stiebel Eltron config entry %s: no host configured",
                eid or "unknown-entry",
            )
            continue

        # Prefer the native physical device's model/name.
        native_device = None
        for device in devices:
            dev_eid = str(device.get("config_entry_id") or "")
            dev_entries = {str(x) for x in (device.get("config_entries") or [])}
            if dev_eid != eid and eid not in dev_entries:
                continue

            identifiers = device.get("identifiers") or []
            has_native_identifier = any(
                isinstance(i, (list, tuple))
                and len(i) >= 2
                and str(i[0]) == "stiebel_eltron_isg"
                for i in identifiers
            )
            if has_native_identifier:
                native_device = device
                break

        if native_device:
            raw_name = str(
                native_device.get("name_by_user")
                or native_device.get("name")
                or native_device.get("model")
                or "ISG"
            ).strip()
            model = str(native_device.get("model") or "").strip()
            # "Stiebel Eltron LWZ" -> "LWZ"
            name = re.sub(
                r"^Stiebel\s+Eltron\s+",
                "",
                raw_name,
                flags=re.IGNORECASE,
            ).strip() or model or "ISG"
        else:
            name = "ISG"
            model = ""

        result.append({
            "entry_id": eid,
            "name": name,
            "model": model,
            "host": host,
            "port": int(data.get("port") or 502),
        })

    return result


def sync_stiebel_eltron(
    opts, api, monitors, default_notification_ids, state,
    discover_devices, ensure_ping_monitor, log,
):
    devices = discover_devices()
    log.info(
        "Home Assistant returned %d native Stiebel Eltron device(s)",
        len(devices),
    )

    for device in devices:
        monitor_name = f'{opts["stiebel_eltron_monitor_prefix"]}{device["name"]}'
        ensure_ping_monitor(
            api,
            monitors,
            monitor_name,
            device["host"],
            opts["stiebel_eltron_ping_interval"],
            opts["stiebel_eltron_max_retries"],
            default_notification_ids,
            state=state,
            identity=f'stiebel_eltron:{device["entry_id"]}',
        )
        log.info(
            "%s -> PING %s (source=stiebel_eltron_isg.config_entry.host, modbus_port=%s)",
            monitor_name,
            device["host"],
            device["port"],
        )

    state["stiebel_eltron"] = {
        d["entry_id"]: {
            "name": d["name"],
            "model": d["model"],
            "host": d["host"],
            "port": d["port"],
        }
        for d in devices
    }
