"""AirGradient device discovery and Ping synchronization."""

import ipaddress
import re
from typing import Any, Dict


def discover_airgradient_devices(
    ha_websocket, config_entry_hosts_from_storage, log,
) -> list[Dict[str, Any]]:
    """One physical native AirGradient device, using its explicit entry host."""
    with ha_websocket() as ha:
        entries = ha.call({"type": "config_entries/get", "domain": "airgradient"}) or []
        if not entries:
            return []
        devices = ha.call({"type": "config/device_registry/list"}) or []
    if not devices:
        return []

    entry_by_id = {str(e["entry_id"]): e for e in entries if e.get("entry_id")}
    hosts = config_entry_hosts_from_storage("airgradient", set(entry_by_id))
    result, seen = [], set()
    for device in devices:
        if device.get("entry_type") is not None or device.get("disabled_by") is not None:
            continue
        if device.get("via_device_id"):
            continue
        native_ids = sorted(str(i[1]) for i in device.get("identifiers") or []
                            if isinstance(i, (list, tuple)) and len(i) == 2
                            and i[0] == "airgradient" and i[1])
        if not native_ids or native_ids[0] in seen:
            continue
        matching = set(str(e) for e in device.get("config_entries") or [])
        if device.get("config_entry_id"):
            matching.add(str(device["config_entry_id"]))
        matching &= entry_by_id.keys()
        if not matching:
            continue
        host, entry = "", None
        for eid in sorted(matching):
            candidate_entry = entry_by_id[eid]
            candidate = str((candidate_entry.get("data") or {}).get("host") or hosts.get(eid) or "").strip()
            # Explicit native host only: do not interpret URLs, credentials,
            # entity names, MAC addresses or arbitrary connection strings.
            try:
                address = ipaddress.ip_address(candidate)
            except ValueError:
                valid = bool(candidate and len(candidate) <= 253 and all(
                    re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label)
                    for label in candidate.rstrip(".").split(".")
                ))
            else:
                valid = address.is_private and not (address.is_unspecified or address.is_multicast or address.is_loopback)
            if valid:
                host, entry = candidate, candidate_entry
                break
        if not host:
            log.info("Skipping AirGradient device: no usable local config-entry host")
            continue
        serial = native_ids[0]
        seen.add(serial)
        # Core's entry title is usually a model shared by many devices. A
        # serial-qualified fallback stays unique even without a user name.
        name = str(device.get("name_by_user") or device.get("name") or "").strip()
        if not name:
            name = f'{entry.get("title") or device.get("model") or "Device"} ({serial})'
        result.append({"device_id": str(device.get("id") or serial),
                       "entry_id": str(entry["entry_id"]), "serial": serial,
                       "name": name, "host": host})
    # Keep distinct physical devices with identical user names distinct in Kuma.
    counts = {}
    for device in result:
        counts[device["name"]] = counts.get(device["name"], 0) + 1
    for device in result:
        if counts[device["name"]] > 1:
            device["name"] += f' ({device["serial"]})'
    return sorted(result, key=lambda d: d["name"].lower())


def sync_airgradient_devices(
    opts, api, monitors, default_notification_ids, state,
    discover_devices, ensure_ping_monitor, log,
):
    devices = discover_devices()
    for device in devices:
        name = f'{opts["airgradient_monitor_prefix"]}{device["name"]}'
        ensure_ping_monitor(api, monitors, name, device["host"],
                            opts["airgradient_ping_interval"], opts["airgradient_max_retries"],
                            default_notification_ids, state=state,
                            identity=f'airgradient:{device["entry_id"]}')
        log.info("%s -> PING %s (source=airgradient.config_entry.host)", name, device["host"])
    state["airgradient"] = {
        d["device_id"]: {"name": d["name"], "host": d["host"], "entry_id": d["entry_id"]}
        for d in devices
    }
