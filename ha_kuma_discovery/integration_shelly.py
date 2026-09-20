"""Shelly discovery and Ping monitor synchronization."""

import re
from typing import Any, Dict
from urllib.parse import urlparse


def _clean_shelly_name(name: str) -> str:
    """
    Collapse Home Assistant child/channel names to a physical-device name.

    Examples:
      "Schuppen Output 0" -> "Schuppen"
      "Shelly_Verdichter Energy Meter 1" -> "Shelly_Verdichter"
    """
    cleaned = str(name).strip()

    # Remove common channel/subdevice suffixes emitted by HA/Shelly.
    patterns = [
        r"\s+Energy Meter\s+\d+$",
        r"\s+Output\s+\d+$",
        r"\s+Channel\s+\d+$",
        r"\s+Switch\s+\d+$",
        r"\s+Input\s+\d+$",
        r"\s+Relay\s+\d+$",
        r"\s+Light\s+\d+$",
        r"\s+Cover\s+\d+$",
    ]
    changed = True
    while changed:
        changed = False
        for pattern in patterns:
            new = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()
            if new != cleaned:
                cleaned = new
                changed = True

    return cleaned or str(name).strip()


def _best_shelly_group_name(names: list[str]) -> str:
    """
    Pick a stable human-friendly name for one physical Shelly.

    Prefer a cleaned name that already exists as a device name, then the
    shortest cleaned name. This makes:
      Shelly_Verdichter
      Shelly_Verdichter Energy Meter 0
      Shelly_Verdichter Energy Meter 1
    become:
      Shelly_Verdichter
    """
    original = [str(n).strip() for n in names if str(n).strip()]
    if not original:
        return "Unknown Shelly"

    cleaned = [_clean_shelly_name(n) for n in original]

    # Prefer a cleaned value that is also present verbatim among the HA names.
    verbatim = [c for c in cleaned if c in original]
    if verbatim:
        return sorted(verbatim, key=lambda x: (len(x), x.lower()))[0]

    # Otherwise prefer the shortest cleaned name.
    return sorted(cleaned, key=lambda x: (len(x), x.lower()))[0]


def discover_shelly_devices(ha_websocket, log) -> list[Dict[str, str]]:
    with ha_websocket() as ha:
        entries = ha.call({"type": "config_entries/get", "domain": "shelly"}) or []
        shelly_entry_ids = {
            str(e.get("entry_id"))
            for e in entries
            if e.get("entry_id")
        }

        devices = ha.call({"type": "config/device_registry/list"}) or []

    # Group by network host/IP, not by Home Assistant device_id.
    # A multi-channel Shelly may expose several HA Device Registry entries
    # (Output 0, Output 1, Energy Meter 0, ...), but they are one physical host.
    groups: Dict[str, Dict[str, Any]] = {}

    for device in devices:
        entry_id = device.get("config_entry_id")
        legacy_entries = set(device.get("config_entries") or [])
        if entry_id not in shelly_entry_ids and not (legacy_entries & shelly_entry_ids):
            continue

        config_url = str(device.get("configuration_url") or "")
        if not config_url:
            # Child devices often lack an address. They do not need their own
            # ping monitor and are intentionally skipped here.
            continue

        parsed = urlparse(config_url)
        host = parsed.hostname
        if not host:
            log.warning(
                "Shelly device '%s' has unusable configuration_url: %s",
                device.get("name_by_user") or device.get("name") or device.get("id"),
                config_url,
            )
            continue

        host_key = str(host).strip().lower()
        if not host_key:
            continue

        raw_name = (
            device.get("name_by_user")
            or device.get("name")
            or device.get("model")
            or device.get("id")
            or host
        )

        group = groups.setdefault(
            host_key,
            {
                "host": str(host),
                "names": [],
                "device_ids": [],
                "configuration_urls": [],
            },
        )

        group["names"].append(str(raw_name))
        if device.get("id"):
            group["device_ids"].append(str(device["id"]))
        if config_url:
            group["configuration_urls"].append(config_url)

    result = []
    for host_key, group in sorted(groups.items()):
        name = _best_shelly_group_name(group["names"])
        device_ids = sorted(set(group["device_ids"]))

        if len(set(group["names"])) > 1:
            log.info(
                "Collapsed %d Shelly registry entries on %s into one monitor '%s': %s",
                len(set(group["names"])),
                group["host"],
                name,
                ", ".join(sorted(set(group["names"]))),
            )

        result.append({
            # Use host as the physical-device identity for ping monitoring.
            "device_id": f"host:{host_key}",
            "source_device_ids": ",".join(device_ids),
            "name": name,
            "host": group["host"],
            "configuration_url": (
                sorted(set(group["configuration_urls"]))[0]
                if group["configuration_urls"]
                else ""
            ),
        })

    return result

def sync_shelly(
    opts, api, monitors, default_notification_ids, state,
    discover_devices, ensure_ping_monitor, log,
):
    shellys = discover_devices()
    log.info("Home Assistant returned %d Shelly device(s) with an address", len(shellys))

    for device in shellys:
        monitor_name = f'{opts["shelly_monitor_prefix"]}{device["name"]}'
        ensure_ping_monitor(
            api,
            monitors,
            monitor_name,
            device["host"],
            opts["shelly_ping_interval"],
            opts["shelly_max_retries"],
            default_notification_ids,
            state=state,
            identity=f'shelly:{device["device_id"]}',
        )
        log.info(
            "%s -> PING %s (device_id=%s)",
            monitor_name,
            device["host"],
            device["device_id"],
        )

    state["known_shelly_device_ids"] = sorted(d["device_id"] for d in shellys)
    state["shelly_devices"] = {
        d["device_id"]: {
            "name": d["name"],
            "host": d["host"],
        }
        for d in shellys
    }



