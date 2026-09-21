"""Load and normalize HA Kuma Discovery add-on options."""

import json
from pathlib import Path
from typing import Any, Dict


def load_options(options_path: Path) -> Dict[str, Any]:
    with options_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    required = ("kuma_url", "kuma_username", "kuma_password")
    missing = [key for key in required if not str(data.get(key, "")).strip()]
    if missing:
        raise RuntimeError("Missing required option(s): " + ", ".join(missing))

    data["kuma_url"] = str(data["kuma_url"]).rstrip("/")
    data["sync_interval"] = max(20, int(data.get("sync_interval", 60)))
    data["heartbeat_interval"] = max(
        data["sync_interval"] + 30,
        int(data.get("heartbeat_interval", 180)),
    )

    for name in (
        "shelly", "unifi", "fritz", "fully_kiosk", "homematic_ip", "e3dc",
        "overkiz", "hue", "smlight", "stiebel_eltron", "synology",
        "airgradient", "homeconnect_local", "ecovacs", "esphome",
    ):
        data[f"{name}_ping_interval"] = max(
            20, int(data.get(f"{name}_ping_interval", 60))
        )
        data[f"{name}_max_retries"] = max(
            0, int(data.get(f"{name}_max_retries", 2))
        )

    prefixes = {
        "airgradient_monitor_prefix": "AirGradient: ",
        "homeconnect_local_monitor_prefix": "Home Connect Local: ",
        "homeconnect_monitor_prefix": "Home Connect: ",
        "ecovacs_monitor_prefix": "Ecovacs: ",
        "monitor_prefix": "HA Add-on: ",
        "shelly_monitor_prefix": "Shelly: ",
        "unifi_monitor_prefix": "UniFi: ",
        "fritz_monitor_prefix": "FRITZ!: ",
        "fully_kiosk_monitor_prefix": "Fully Kiosk: ",
        "homematic_ip_monitor_prefix": "Homematic IP: ",
        "matter_monitor_prefix": "Matter: ",
        "e3dc_monitor_prefix": "E3DC: ",
        "overkiz_monitor_prefix": "Somfy: ",
        "hue_monitor_prefix": "Hue: ",
        "smlight_monitor_prefix": "SMLIGHT: ",
        "stiebel_eltron_monitor_prefix": "Stiebel Eltron: ",
        "synology_monitor_prefix": "Synology: ",
        "esphome_monitor_prefix": "ESPHome: ",
        "zigbee2mqtt_monitor_prefix": "Zigbee2MQTT: ",
        "mqtt_monitor_prefix": "MQTT: ",
    }
    for name, default in prefixes.items():
        data[name] = str(data.get(name, default))

    data["push_down_grace_cycles"] = max(
        1, int(data.get("push_down_grace_cycles", 3))
    )

    defaults = {
        "verify_ssl": True,
        "discover_addons": True,
        "discover_shelly": True,
        "discover_unifi_network_devices": True,
        "discover_fritz_network_devices": True,
        "discover_fully_kiosk_devices": True,
        "discover_homematic_ip_infrastructure": True,
        "discover_matter_devices": True,
        "discover_e3dc_devices": True,
        "discover_overkiz_devices": True,
        "discover_hue_bridge": True,
        "discover_hue_devices": False,
        "discover_smlight_devices": True,
        "discover_stiebel_eltron": True,
        "discover_synology_dsm": True,
        "discover_esphome_devices": True,
        "discover_airgradient_devices": True,
        "discover_homeconnect_local_devices": True,
        "discover_homeconnect_cloud_devices": True,
        "discover_ecovacs_devices": True,
        "discover_zigbee2mqtt_devices": True,
        "discover_mqtt_devices": True,
    }
    for name, default in defaults.items():
        data[name] = bool(data.get(name, default))

    data["ecovacs_ignore_set"] = {
        value.strip().lower()
        for value in str(data.get("ecovacs_ignore", "")).split(",")
        if value.strip()
    }

    data["ignore_slugs_set"] = {
        value.strip()
        for value in str(data.get("ignore_slugs", "")).split(",")
        if value.strip()
    }
    return data
