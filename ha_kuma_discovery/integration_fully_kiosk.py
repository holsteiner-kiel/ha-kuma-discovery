"""Fully Kiosk Browser discovery and Ping synchronization."""

import re
from typing import Any, Dict


def _clean_fully_name(value: str) -> str:
    value = str(value or "").strip().replace("_", " ")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def discover_fully_kiosk_devices(
    ha_websocket, config_entry_hosts_from_storage, log,
) -> list[Dict[str, str]]:
    """
    Discover only devices belonging to the Home Assistant Fully Kiosk Browser
    integration and create one ping target per configured Fully host.

    The config entry is the source of truth for the device IP/host. Device
    registry metadata and HA areas are used only to build a friendly unique name.
    """
    with ha_websocket() as ha:
        entries = ha.call({"type": "config_entries/get", "domain": "fully_kiosk"}) or []
        devices = ha.call({"type": "config/device_registry/list"}) or []
        try:
            areas = ha.call({"type": "config/area_registry/list"}) or []
        except Exception:
            areas = []

    if not entries:
        log.info("No Fully Kiosk Browser config entry found")
        return []

    entry_ids = {str(e.get("entry_id")) for e in entries if e.get("entry_id")}
    entry_hosts = config_entry_hosts_from_storage("fully_kiosk", entry_ids)

    # Compatibility if HA ever exposes the host via the WS config-entry result.
    for entry in entries:
        eid = str(entry.get("entry_id") or "")
        host = str((entry.get("data") or {}).get("host") or "").strip()
        if eid and host:
            entry_hosts.setdefault(eid, host)

    area_names = {
        str(a.get("area_id")): str(a.get("name") or "").strip()
        for a in areas
        if a.get("area_id")
    }

    device_by_entry: Dict[str, Dict[str, Any]] = {}
    for device in devices:
        eid = str(device.get("config_entry_id") or "")
        if eid in entry_ids:
            device_by_entry[eid] = device
            continue

        legacy = {str(x) for x in (device.get("config_entries") or [])}
        for match in sorted(legacy & entry_ids):
            device_by_entry.setdefault(match, device)

    result = []
    for entry in entries:
        eid = str(entry.get("entry_id") or "")
        if not eid:
            continue

        host = str(entry_hosts.get(eid) or "").strip()
        if not host:
            log.warning(
                "Fully Kiosk config entry '%s' has no usable host; skipping.",
                entry.get("title") or eid,
            )
            continue

        device = device_by_entry.get(eid) or {}
        entry_title = _clean_fully_name(entry.get("title") or "")
        device_name = _clean_fully_name(
            device.get("name_by_user")
            or device.get("name")
            or ""
        )
        model = _clean_fully_name(device.get("model") or "")
        area_name = _clean_fully_name(area_names.get(str(device.get("area_id") or ""), ""))

        # Prefer the HA device name because users often rename Fully devices
        # there (e.g. "Tablet Arbeitszimmer"). Otherwise use the config-entry title.
        name = device_name or entry_title or model or host

        # When the visible device name is generic or duplicated, area names give
        # useful stable differentiation such as "Fire Tablet Wohnzimmer/Flur".
        if area_name and area_name.lower() not in name.lower():
            name = f"{name} {area_name}"

        result.append({
            "device_id": str(device.get("id") or eid),
            "entry_id": eid,
            "name": name,
            "host": host,
            "model": model,
            "area": area_name,
        })

    # Make any remaining duplicate names unique. Prefer area, then model, then IP.
    name_groups: Dict[str, list[Dict[str, str]]] = {}
    for item in result:
        name_groups.setdefault(item["name"].lower(), []).append(item)

    for group in name_groups.values():
        if len(group) <= 1:
            continue
        for item in group:
            suffix = item.get("area") or item.get("model") or item.get("host")
            if suffix and suffix.lower() not in item["name"].lower():
                item["name"] = f'{item["name"]} {suffix}'
            elif item.get("host"):
                item["name"] = f'{item["name"]} ({item["host"]})'

    # Host is the physical network identity. One Fully monitor per tablet.
    deduped: Dict[str, Dict[str, str]] = {}
    for item in result:
        deduped.setdefault(item["host"].lower(), item)

    return sorted(deduped.values(), key=lambda d: d["name"].lower())



def sync_fully_kiosk_devices(
    opts, api, monitors, default_notification_ids, state,
    discover_devices, ensure_ping_monitor, log,
):
    devices = discover_devices()
    log.info(
        "Home Assistant returned %d Fully Kiosk device(s) with an address",
        len(devices),
    )

    for device in devices:
        monitor_name = f'{opts["fully_kiosk_monitor_prefix"]}{device["name"]}'
        ensure_ping_monitor(
            api,
            monitors,
            monitor_name,
            device["host"],
            opts["fully_kiosk_ping_interval"],
            opts["fully_kiosk_max_retries"],
            default_notification_ids,
            state=state,
            identity=f'fully_kiosk:{device["device_id"]}',
        )
        log.info(
            "%s -> PING %s (model=%s, area=%s, device_id=%s)",
            monitor_name,
            device["host"],
            device["model"] or "unknown",
            device.get("area") or "none",
            device["device_id"],
        )

    state["known_fully_kiosk_device_ids"] = sorted(d["device_id"] for d in devices)
    state["fully_kiosk_devices"] = {
        d["device_id"]: {
            "name": d["name"],
            "host": d["host"],
            "model": d["model"],
            "area": d.get("area") or "",
        }
        for d in devices
    }


