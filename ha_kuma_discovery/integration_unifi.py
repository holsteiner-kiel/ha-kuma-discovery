"""UniFi Network infrastructure discovery and Ping monitor synchronization."""

import ipaddress
import json
import re
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse


def _entity_domain(entity_id: str) -> str:
    return str(entity_id).split(".", 1)[0] if "." in str(entity_id) else ""


def _state_ip(attributes: Dict[str, Any]) -> str | None:
    """
    Try common Home Assistant attributes used for network-device addresses.
    """
    for key in ("ip", "ip_address", "host", "address"):
        value = attributes.get(key)
        if not value:
            continue
        value = str(value).strip()

        # Strip URL/port if a host-like attribute happens to contain one.
        if "://" in value:
            try:
                parsed = urlparse(value)
                value = parsed.hostname or ""
            except Exception:
                pass

        # A normal IPv4/IPv6/hostname is fine; ignore obvious MAC addresses.
        if value and not re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", value):
            return value
    return None


def _normalize_mac(value: str) -> str:
    return re.sub(r"[^0-9a-f]", "", str(value).lower())


def _device_mac_from_registry(device: Dict[str, Any]) -> str | None:
    for connection in device.get("connections") or []:
        if not isinstance(connection, (list, tuple)) or len(connection) != 2:
            continue
        connection_type, value = connection
        if str(connection_type).lower() == "mac" and value:
            return _normalize_mac(str(value))
    return None


def _looks_like_mac_name(value: str) -> bool:
    value = str(value or "").strip()
    if not value:
        return False
    return bool(
        re.fullmatch(r"(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}", value)
        or re.fullmatch(r"[0-9A-Fa-f]{12}", value)
    )


def _generic_unifi_name(value: str) -> bool:
    value = str(value or "").strip().lower()
    return value in {
        "",
        "firmware",
        "firmware update",
        "update",
        "device update",
        "unifi device update",
        "network device",
    }


def _clean_unifi_friendly_name(value: str) -> str:
    value = str(value or "").strip()
    value = re.sub(
        r"\s+(?:Firmware|Firmware Update|Update|State|Zustand)$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    return value


def _strip_unifi_entity_suffix(value: str) -> str:
    value = str(value or "").strip()

    # Only strip suffixes from infrastructure status sensors we explicitly use
    # as a fallback. Do not use action-button names such as "Neu starten".
    suffixes = [
        r"\s+State$",
        r"\s+Zustand$",
        r"\s+Uptime$",
        r"\s+Betriebszeit$",
        r"\s+Clients$",
        r"\s+CPU Utilization$",
        r"\s+CPU Auslastung$",
        r"\s+Memory Utilization$",
        r"\s+Speicherauslastung$",
        r"\s+Temperature$",
        r"\s+Temperatur$",
    ]
    changed = True
    while changed:
        changed = False
        for pattern in suffixes:
            new = re.sub(pattern, "", value, flags=re.IGNORECASE).strip()
            if new != value:
                value = new
                changed = True
    return value


def _best_unifi_device_name(
    device: Dict[str, Any],
    device_entities: list[Dict[str, Any]],
    state_by_entity: Dict[str, Dict[str, Any]],
) -> str:
    """
    Choose the managed UniFi device's actual HA name.

    Priority:
      1. HA device-registry user name / device name
      2. friendly_name from infrastructure status sensors only
      3. model

    Button/action friendly names (e.g. '<MAC> Neu starten') and generic update
    labels are never used as monitor names.
    """
    # 1) Device registry is authoritative and gave the correct names in the
    #    UniFi discovery logs (Core, USW-Flex-..., U6-Pro-..., UCG Fiber, ...).
    for key in ("name_by_user", "name"):
        candidate = str(device.get(key) or "").strip()
        if not candidate:
            continue
        candidate = _clean_unifi_friendly_name(candidate)
        if candidate and not _looks_like_mac_name(candidate) and not _generic_unifi_name(candidate):
            return candidate

    # 2) Only use stable status/sensor entities as fallback. Never buttons,
    #    update entities, lights or port switches.
    preferred_sensor_suffixes = (
        "_state", "_zustand", "_uptime", "_betriebszeit",
        "_clients", "_cpu_utilization", "_cpu_auslastung",
        "_memory_utilization", "_speicherauslastung",
    )

    for entity in device_entities:
        entity_id = str(entity.get("entity_id") or "")
        if not entity_id.startswith("sensor."):
            continue
        if not entity_id.endswith(preferred_sensor_suffixes):
            continue

        state = state_by_entity.get(entity_id)
        if not state:
            continue
        friendly = str((state.get("attributes") or {}).get("friendly_name") or "").strip()
        if not friendly:
            continue

        candidate = _strip_unifi_entity_suffix(friendly)
        candidate = _clean_unifi_friendly_name(candidate)
        if candidate and not _looks_like_mac_name(candidate) and not _generic_unifi_name(candidate):
            return candidate

    # 3) Stable final fallback.
    return str(device.get("model") or device.get("id") or "UniFi Device")

def _is_private_or_local_host(host: str) -> bool:
    """
    UniFi infrastructure management addresses should normally be LAN addresses.
    Hostnames are accepted. Literal public IP addresses are rejected so a
    gateway's WAN IP is not accidentally monitored instead of its management IP.
    """
    host = str(host or "").strip()
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local)


def _unifi_config_entry_hosts_from_storage(
    allowed_entry_ids: set[str], config_entries_path: Path, log,
) -> Dict[str, str]:
    """
    Read only the UniFi config-entry host from Home Assistant's local storage.

    The WebSocket config_entries/get response intentionally does not expose the
    integration's private `data` mapping, so the controller host is not present
    there. The add-on mounts Home Assistant's config read-only at /homeassistant
    and reads only data.host for matching UniFi entries.
    """
    hosts: Dict[str, str] = {}
    if not allowed_entry_ids:
        return hosts

    if not config_entries_path.exists():
        log.warning(
            "Home Assistant config-entry storage is not mounted at %s; "
            "Cloud Gateway local-host fallback is unavailable.",
            config_entries_path,
        )
        return hosts

    try:
        raw = json.loads(config_entries_path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning(
            "Could not read Home Assistant config-entry storage for UniFi host lookup: %s",
            exc,
        )
        return hosts

    for entry in (raw.get("data") or {}).get("entries") or []:
        if str(entry.get("domain") or "") != "unifi":
            continue

        entry_id = str(entry.get("entry_id") or "")
        if not entry_id or entry_id not in allowed_entry_ids:
            continue

        host = str((entry.get("data") or {}).get("host") or "").strip()
        if host:
            hosts[entry_id] = host

    if hosts:
        log.info(
            "Loaded local UniFi config-entry host(s) for %d integration entr%s",
            len(hosts),
            "y" if len(hosts) == 1 else "ies",
        )

    return hosts


def discover_unifi_network_devices(ha_websocket, config_entries_path: Path, log) -> list[Dict[str, str]]:
    """
    Discover only UniFi infrastructure devices (gateway, switches, APs), not clients.

    Home Assistant's UniFi integration can create dedicated Device Tracker entities
    for UniFi network devices when "Track network devices" is enabled. Those
    trackers expose the device IP address, but they are intentionally not linked
    to the normal HA device-registry entry. Their unique_id is the UniFi device MAC.

    We therefore:
      1. identify infrastructure devices by their firmware update entity;
      2. read the physical device MAC from the HA device registry;
      3. map that MAC to the UniFi Device Tracker entity;
      4. read the tracker's live `ip` attribute.
    """
    with ha_websocket() as ha:
        entries = ha.call({"type": "config_entries/get", "domain": "unifi"}) or []
        unifi_entry_ids = {
            str(e.get("entry_id"))
            for e in entries
            if e.get("entry_id")
        }

        # The WebSocket entry list normally omits private config-entry data such
        # as the UniFi host. Read the matching host from HA storage instead.
        unifi_entry_hosts = _unifi_config_entry_hosts_from_storage(unifi_entry_ids, config_entries_path, log)

        # Keep compatibility in case a future HA version exposes data.host here.
        for entry in entries:
            entry_id = str(entry.get("entry_id") or "")
            data = entry.get("data") or {}
            host = str(data.get("host") or "").strip()
            if entry_id and host:
                unifi_entry_hosts.setdefault(entry_id, host)

        devices = ha.call({"type": "config/device_registry/list"}) or []
        entities = ha.call({"type": "config/entity_registry/list"}) or []
        states = ha.call({"type": "get_states"}) or []

    if not unifi_entry_ids:
        log.info("No UniFi Network config entry found")
        return []

    state_by_entity = {
        str(s.get("entity_id")): s
        for s in states
        if s.get("entity_id")
    }

    entities_by_device: Dict[str, list[Dict[str, Any]]] = {}
    tracker_by_mac: Dict[str, Dict[str, Any]] = {}

    for entity in entities:
        entry_id = entity.get("config_entry_id")
        legacy_entries = set(entity.get("config_entry_ids") or [])
        if entry_id not in unifi_entry_ids and not (legacy_entries & unifi_entry_ids):
            continue

        device_id = entity.get("device_id")
        if device_id:
            entities_by_device.setdefault(str(device_id), []).append(entity)

        entity_id = str(entity.get("entity_id") or "")
        if _entity_domain(entity_id) != "device_tracker":
            continue

        unique_id = str(entity.get("unique_id") or "")
        mac_key = _normalize_mac(unique_id)
        if len(mac_key) != 12:
            continue

        state = state_by_entity.get(entity_id)
        if not state:
            continue

        attrs = state.get("attributes") or {}
        host = _state_ip(attrs)
        if not host:
            continue

        tracker_by_mac[mac_key] = {
            "entity_id": entity_id,
            "host": host,
            "state": str(state.get("state") or ""),
            "friendly_name": str(
                entity.get("name")
                or entity.get("original_name")
                or ""
            ).strip(),
        }

    result = []

    for device in devices:
        device_id = str(device.get("id") or "")
        if not device_id:
            continue

        entry_id = device.get("config_entry_id")
        legacy_entries = set(device.get("config_entries") or [])
        if entry_id not in unifi_entry_ids and not (legacy_entries & unifi_entry_ids):
            if device_id not in entities_by_device:
                continue

        device_entities = entities_by_device.get(device_id, [])

        # Managed UniFi infrastructure has firmware-update entities; ordinary
        # network clients do not.
        update_entities = [
            e for e in device_entities
            if _entity_domain(e.get("entity_id", "")) == "update"
        ]
        if not update_entities:
            continue

        host = None
        source = None

        # First use any IP attributes directly exposed by a device entity.
        for entity in device_entities:
            state = state_by_entity.get(str(entity.get("entity_id") or ""))
            if not state:
                continue
            host = _state_ip(state.get("attributes") or {})
            if host:
                source = str(entity.get("entity_id") or "")
                break

        # Normal case for UniFi infrastructure: resolve MAC -> UniFi Device Tracker.
        if not host:
            mac_key = _device_mac_from_registry(device)
            tracker = tracker_by_mac.get(mac_key or "")
            if tracker:
                host = tracker["host"]
                source = tracker["entity_id"]

        tracker_name = ""
        mac_key = _device_mac_from_registry(device)
        if mac_key:
            tracker = tracker_by_mac.get(mac_key)
            if tracker:
                tracker_name = str(tracker.get("friendly_name") or "").strip()

        if tracker_name and not _looks_like_mac_name(tracker_name) and not _generic_unifi_name(tracker_name):
            name = tracker_name
        else:
            name = _best_unifi_device_name(device, device_entities, state_by_entity)

        if not host:
            mac_key = _device_mac_from_registry(device)
            log.warning(
                "UniFi infrastructure device '%s' (%s) has no usable IP. "
                "MAC=%s. Enable 'Track network devices' in the Home Assistant "
                "UniFi Network integration so HA creates device_tracker entities.",
                name,
                device.get("model") or "unknown model",
                mac_key or "unknown",
            )
            continue

        if not _is_private_or_local_host(host):
            # Cloud Gateways may expose their WAN IP through the UniFi device
            # tracker. In that case, use the Home Assistant UniFi config-entry
            # host, which is the controller/gateway's local management address.
            entry_candidates = []
            primary_entry = str(
                device.get("primary_config_entry")
                or device.get("config_entry_id")
                or ""
            )
            if primary_entry:
                entry_candidates.append(primary_entry)
            for eid in device.get("config_entries") or []:
                if str(eid) not in entry_candidates:
                    entry_candidates.append(str(eid))

            fallback_host = None
            for eid in entry_candidates:
                candidate = str(unifi_entry_hosts.get(eid) or "").strip()
                if candidate and _is_private_or_local_host(candidate):
                    fallback_host = candidate
                    break

            if fallback_host:
                log.info(
                    "UniFi infrastructure device '%s' (%s) exposed public tracker IP %s; "
                    "using local UniFi config-entry host %s instead.",
                    name,
                    device.get("model") or "unknown model",
                    host,
                    fallback_host,
                )
                host = fallback_host
                source = "unifi_config_entry.host"
            else:
                log.warning(
                    "UniFi infrastructure device '%s' (%s) resolved to public IP %s "
                    "via %s and no private/local UniFi config-entry host was available; skipping.",
                    name,
                    device.get("model") or "unknown model",
                    host,
                    source or "unknown source",
                )
                continue

        result.append({
            "device_id": device_id,
            "name": str(name),
            "host": str(host),
            "model": str(device.get("model") or ""),
            "manufacturer": str(device.get("manufacturer") or ""),
            "ip_source": source or "",
        })

    # Dedupe by host in case HA exposes multiple registry representations for
    # one physical UniFi device.
    grouped: Dict[str, Dict[str, str]] = {}
    for device in result:
        key = device["host"].strip().lower()
        if key not in grouped:
            grouped[key] = device
            continue

        current = grouped[key]
        if len(device["name"]) < len(current["name"]):
            grouped[key] = device

    devices_out = sorted(grouped.values(), key=lambda d: d["name"].lower())

    # Ensure different physical devices never collapse into the same Kuma monitor
    # merely because HA returned the same generic/friendly name.
    name_counts = {}
    for item in devices_out:
        name_counts[item["name"]] = name_counts.get(item["name"], 0) + 1

    for item in devices_out:
        if name_counts.get(item["name"], 0) > 1:
            item["name"] = f'{item["name"]} ({item["host"]})'

    return devices_out


def sync_unifi_network_devices(
    opts, api, monitors, default_notification_ids, state,
    discover_devices, ensure_ping_monitor, log,
):
    devices = discover_devices()
    log.info(
        "Home Assistant returned %d UniFi infrastructure device(s) with an address",
        len(devices),
    )

    for device in devices:
        monitor_name = f'{opts["unifi_monitor_prefix"]}{device["name"]}'
        ensure_ping_monitor(
            api,
            monitors,
            monitor_name,
            device["host"],
            opts["unifi_ping_interval"],
            opts["unifi_max_retries"],
            default_notification_ids,
            state=state,
            identity=f'unifi:{device["device_id"]}',
        )
        log.info(
            "%s -> PING %s (model=%s, source=%s, device_id=%s)",
            monitor_name,
            device["host"],
            device["model"] or "unknown",
            device.get("ip_source") or "unknown",
            device["device_id"],
        )

    state["known_unifi_device_ids"] = sorted(d["device_id"] for d in devices)
    state["unifi_devices"] = {
        d["device_id"]: {
            "name": d["name"],
            "host": d["host"],
            "model": d["model"],
        }
        for d in devices
    }


