#!/usr/bin/env python3

import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Any

import requests
import websocket
from uptime_kuma_api import UptimeKumaApi

import ha_client
import integration_addons
import integration_airgradient
import integration_e3dc
import integration_esphome
import integration_fritz
import integration_fully_kiosk
import integration_homematic
import integration_hue
import integration_matter
import integration_mqtt
import integration_overkiz
import integration_shelly
import integration_smlight
import integration_stiebel_eltron
import integration_synology
import integration_unifi
import kuma_monitor
import option_loader
import push_state
import state_store


OPTIONS = Path("/data/options.json")
STATE = Path("/data/state.json")
SUPERVISOR = "http://supervisor/"
HA_WS = "ws://supervisor/core/websocket"
HA_CONFIG_ENTRIES = Path("/homeassistant/.storage/core.config_entries")
LOG = logging.getLogger("ha-kuma-discovery")
# Headers (especially SUPERVISOR_TOKEN) remain request-local.
HTTP = requests.Session()


def read_options() -> Dict[str, Any]:
    return option_loader.load_options(OPTIONS)


def load_state() -> Dict[str, Any]:
    return state_store.load_state(STATE, LOG)


def save_state(state: Dict[str, Any]) -> None:
    state_store.save_state(state, STATE, LOG)


def supervisor_get(path: str) -> Any:
    return ha_client.supervisor_get(path, HTTP, SUPERVISOR)


HAWebSocket = ha_client.HAWebSocket



normalize_items = kuma_monitor.normalize_items
find_monitor = kuma_monitor.find_monitor
find_managed_monitor = kuma_monitor.find_managed_monitor
remember_monitor_identity = kuma_monitor.remember_monitor_identity
notification_is_default = kuma_monitor.notification_is_default
notification_is_active = kuma_monitor.notification_is_active


@contextmanager
def kuma_operation(stage, log_duration=False):
    with kuma_monitor.kuma_operation(stage, log_duration=log_duration):
        yield


def kuma_call(stage, operation, *args, _log_duration=False, **kwargs):
    return kuma_monitor.kuma_call(
        stage, operation, *args, _log_duration=_log_duration, **kwargs
    )


@contextmanager
def kuma_session(opts):
    with kuma_monitor.kuma_session(opts, api_factory=UptimeKumaApi) as api:
        yield api


get_default_notification_ids = kuma_monitor.get_default_notification_ids
monitor_notification_ids = kuma_monitor.monitor_notification_ids
ensure_push_monitor = kuma_monitor.ensure_push_monitor
ensure_ping_monitor = kuma_monitor.ensure_ping_monitor


def push_status(kuma_url, monitor, up, message, verify_ssl):
    return push_state.push_status(
        kuma_url, monitor, up, message, verify_ssl, HTTP, kuma_operation
    )


def push_status_if_needed(
    kuma_url,
    monitor,
    up,
    message,
    verify_ssl,
    state,
    heartbeat_interval,
    sync_interval,
):
    return push_state.push_status_if_needed(
        kuma_url,
        monitor,
        up,
        message,
        verify_ssl,
        state,
        heartbeat_interval,
        sync_interval,
        sender=push_status,
        now=time.time,
    )


_clean_shelly_name = integration_shelly._clean_shelly_name
_best_shelly_group_name = integration_shelly._best_shelly_group_name


def discover_shelly_devices() -> list[Dict[str, str]]:
    return integration_shelly.discover_shelly_devices(HAWebSocket, LOG)


def sync_addons(opts, api, monitors, default_notification_ids, state):
    integration_addons.sync(
        opts,
        api,
        monitors,
        default_notification_ids,
        state,
        supervisor_get,
        ensure_push_monitor,
        push_status_if_needed,
        LOG,
    )


def sync_shelly(opts, api, monitors, default_notification_ids, state):
    integration_shelly.sync_shelly(
        opts,
        api,
        monitors,
        default_notification_ids,
        state,
        discover_shelly_devices,
        ensure_ping_monitor,
        LOG,
    )


def discover_unifi_network_devices() -> list[Dict[str, str]]:
    return integration_unifi.discover_unifi_network_devices(
        HAWebSocket, HA_CONFIG_ENTRIES, LOG,
    )


def sync_unifi_network_devices(opts, api, monitors, default_notification_ids, state):
    integration_unifi.sync_unifi_network_devices(
        opts,
        api,
        monitors,
        default_notification_ids,
        state,
        discover_unifi_network_devices,
        ensure_ping_monitor,
        LOG,
    )


def discover_fritz_network_devices() -> list[Dict[str, str]]:
    return integration_fritz.discover_fritz_network_devices(
        HAWebSocket,
        _config_entry_hosts_from_storage,
        _device_has_identifier,
        _is_private_or_local_host,
        _device_mac_from_registry,
        LOG,
    )


def sync_fritz_network_devices(opts, api, monitors, default_notification_ids, state):
    integration_fritz.sync_fritz_network_devices(
        opts,
        api,
        monitors,
        default_notification_ids,
        state,
        discover_fritz_network_devices,
        ensure_ping_monitor,
        LOG,
    )


def discover_fully_kiosk_devices() -> list[Dict[str, str]]:
    return integration_fully_kiosk.discover_fully_kiosk_devices(
        HAWebSocket, _config_entry_hosts_from_storage, LOG,
    )


def sync_fully_kiosk_devices(opts, api, monitors, default_notification_ids, state):
    integration_fully_kiosk.sync_fully_kiosk_devices(
        opts,
        api,
        monitors,
        default_notification_ids,
        state,
        discover_fully_kiosk_devices,
        ensure_ping_monitor,
        LOG,
    )


def discover_homematic_ip_infrastructure() -> Dict[str, Any]:
    return integration_homematic.discover_homematic_ip_infrastructure(
        HAWebSocket,
        _config_entry_hosts_from_storage,
        _device_has_identifier,
        _is_private_or_local_host,
        LOG,
    )


def sync_homematic_ip_infrastructure(opts, api, monitors, default_notification_ids, state):
    integration_homematic.sync_homematic_ip_infrastructure(
        opts,
        api,
        monitors,
        default_notification_ids,
        state,
        discover_homematic_ip_infrastructure,
        ensure_ping_monitor,
        ensure_push_monitor,
        _push_effective_up,
        push_status_if_needed,
        LOG,
    )


def discover_matter_devices() -> list[Dict[str, Any]]:
    return integration_matter.discover_matter_devices(
        HAWebSocket, _entity_domain, LOG,
    )


def sync_matter_devices(opts, api, monitors, default_notification_ids, state):
    integration_matter.sync_matter_devices(
        opts,
        api,
        monitors,
        default_notification_ids,
        state,
        discover_matter_devices,
        ensure_push_monitor,
        _push_effective_up,
        push_status_if_needed,
        LOG,
    )


def discover_e3dc_devices() -> list[Dict[str, str]]:
    return integration_e3dc.discover_e3dc_devices(
        HAWebSocket,
        _config_entry_hosts_from_storage,
        _is_private_or_local_host,
        LOG,
    )


def sync_e3dc_devices(opts, api, monitors, default_notification_ids, state):
    integration_e3dc.sync_e3dc_devices(
        opts,
        api,
        monitors,
        default_notification_ids,
        state,
        discover_e3dc_devices,
        ensure_ping_monitor,
        LOG,
    )


def discover_overkiz_devices() -> Dict[str, Any]:
    return integration_overkiz.discover_overkiz_devices(
        HAWebSocket, _config_entry_hosts_from_storage, _entity_domain, LOG,
    )


def sync_overkiz_devices(opts, api, monitors, default_notification_ids, state):
    integration_overkiz.sync_overkiz_devices(
        opts,
        api,
        monitors,
        default_notification_ids,
        state,
        discover_overkiz_devices,
        ensure_ping_monitor,
        ensure_push_monitor,
        _push_effective_up,
        push_status_if_needed,
        LOG,
    )


def discover_hue(include_devices: bool = True) -> Dict[str, Any]:
    return integration_hue.discover_hue(
        include_devices, HAWebSocket, _config_entry_hosts_from_storage,
        _entity_domain, LOG,
    )


def sync_hue(opts, api, monitors, default_notification_ids, state):
    integration_hue.sync_hue(
        opts, api, monitors, default_notification_ids, state, discover_hue,
        ensure_ping_monitor, ensure_push_monitor, _push_effective_up,
        push_status_if_needed, LOG,
    )


def discover_smlight_devices() -> list[Dict[str, Any]]:
    return integration_smlight.discover_smlight_devices(
        HAWebSocket, _config_entry_hosts_from_storage, LOG,
    )


def sync_smlight_devices(opts, api, monitors, default_notification_ids, state):
    integration_smlight.sync_smlight_devices(
        opts, api, monitors, default_notification_ids, state,
        discover_smlight_devices, ensure_ping_monitor, LOG,
    )


def discover_stiebel_eltron() -> list[Dict[str, Any]]:
    return integration_stiebel_eltron.discover_stiebel_eltron(
        HAWebSocket, _config_entry_hosts_from_storage, LOG,
    )


def sync_stiebel_eltron(opts, api, monitors, default_notification_ids, state):
    integration_stiebel_eltron.sync_stiebel_eltron(
        opts, api, monitors, default_notification_ids, state,
        discover_stiebel_eltron, ensure_ping_monitor, LOG,
    )


def discover_synology_dsm() -> list[Dict[str, Any]]:
    return integration_synology.discover_synology_dsm(
        HAWebSocket, _config_entry_hosts_from_storage, LOG,
    )


def sync_synology_dsm(opts, api, monitors, default_notification_ids, state):
    integration_synology.sync_synology_dsm(
        opts, api, monitors, default_notification_ids, state,
        discover_synology_dsm, ensure_ping_monitor, LOG,
    )


def discover_esphome_devices() -> list[Dict[str, Any]]:
    return integration_esphome.discover_esphome_devices(
        HAWebSocket, _config_entry_hosts_from_storage, LOG,
    )


def sync_esphome_devices(opts, api, monitors, default_notification_ids, state):
    integration_esphome.sync_esphome_devices(
        opts, api, monitors, default_notification_ids, state,
        discover_esphome_devices, ensure_ping_monitor, LOG,
    )


def discover_airgradient_devices() -> list[Dict[str, Any]]:
    return integration_airgradient.discover_airgradient_devices(
        HAWebSocket, _config_entry_hosts_from_storage, LOG,
    )


def sync_airgradient_devices(opts, api, monitors, default_notification_ids, state):
    integration_airgradient.sync_airgradient_devices(
        opts, api, monitors, default_notification_ids, state,
        discover_airgradient_devices, ensure_ping_monitor, LOG,
    )


_entity_domain = ha_client.entity_domain
_state_ip = ha_client.state_ip
_normalize_mac = ha_client.normalize_mac
_device_mac_from_registry = ha_client.device_mac_from_registry
_looks_like_mac_name = ha_client.looks_like_mac_name
_is_private_or_local_host = ha_client.is_private_or_local_host
_device_has_identifier = ha_client.device_has_identifier


def _config_entry_hosts_from_storage(
    domain: str,
    allowed_entry_ids: set[str],
) -> Dict[str, str]:
    return ha_client.config_entry_hosts_from_storage(
        domain,
        allowed_entry_ids,
        HA_CONFIG_ENTRIES,
        LOG,
    )


_push_effective_up = push_state.push_effective_up


def discover_mqtt_physical_devices() -> Dict[str, list[Dict[str, Any]]]:
    return integration_mqtt.discover_mqtt_physical_devices(
        HAWebSocket, _entity_domain, LOG,
    )


def _sync_mqtt_device_list(
    opts, api, monitors, default_notification_ids, state,
    devices, prefix, state_key,
):
    integration_mqtt._sync_mqtt_device_list(
        opts, api, monitors, default_notification_ids, state,
        devices, prefix, state_key, ensure_push_monitor,
        _push_effective_up, push_status_if_needed, LOG,
    )


def sync_mqtt_devices(opts, api, monitors, default_notification_ids, state):
    integration_mqtt.sync_mqtt_devices(
        opts, api, monitors, default_notification_ids, state,
        discover_mqtt_physical_devices, _sync_mqtt_device_list,
    )


def sync_once(opts):
    state = load_state()
    try:
        with kuma_session(opts) as api:
            kuma_call("authentication/login", api.login,
                      opts["kuma_username"], opts["kuma_password"],
                      _log_duration=True)
            monitors = normalize_items(kuma_call(
                "fetching monitors", api.get_monitors, _log_duration=True,
            ))
            default_notification_ids = get_default_notification_ids(api)
            jobs = [
                (opts["discover_addons"], sync_addons),
                (opts["discover_shelly"], sync_shelly),
                (opts["discover_unifi_network_devices"], sync_unifi_network_devices),
                (opts["discover_fritz_network_devices"], sync_fritz_network_devices),
                (opts["discover_fully_kiosk_devices"], sync_fully_kiosk_devices),
                (opts["discover_homematic_ip_infrastructure"], sync_homematic_ip_infrastructure),
                (opts["discover_matter_devices"], sync_matter_devices),
                (opts["discover_e3dc_devices"], sync_e3dc_devices),
                (opts["discover_overkiz_devices"], sync_overkiz_devices),
                (opts["discover_hue_bridge"] or opts["discover_hue_devices"], sync_hue),
                (opts["discover_smlight_devices"], sync_smlight_devices),
                (opts["discover_stiebel_eltron"], sync_stiebel_eltron),
                (opts["discover_synology_dsm"], sync_synology_dsm),
                (opts["discover_esphome_devices"], sync_esphome_devices),
                (opts["discover_airgradient_devices"], sync_airgradient_devices),
                (opts["discover_zigbee2mqtt_devices"] or opts["discover_mqtt_devices"], sync_mqtt_devices),
            ]
            failed = []
            completed = 0
            timings = []
            HAWebSocket.begin_cycle()
            try:
                for enabled, sync in jobs:
                    if not enabled:
                        continue
                    integration_started = time.monotonic()
                    try:
                        sync(opts, api, monitors, default_notification_ids, state)
                        completed += 1
                    except Exception as exc:
                        failed.append(sync.__name__)
                        # Request exceptions can contain secret Push URLs.
                        LOG.error("Integration %s failed (%s); continuing with remaining integrations",
                                  sync.__name__, type(exc).__name__)
                    finally:
                        timings.append((sync.__name__, time.monotonic() - integration_started))
            finally:
                HAWebSocket.end_cycle()
            if timings:
                LOG.info("Integration timings: %s", ", ".join(
                    f"{name}={duration:.1f}s" for name, duration in timings
                ))
            if failed:
                LOG.warning("Sync partially completed: %d succeeded, %d failed: %s",
                            completed, len(failed), ", ".join(failed))
            else:
                LOG.info("Sync completed: %d integration(s) succeeded", completed)
    finally:
        # Preserve successful Push timestamps and debounce counters on partial failure.
        save_state(state)


def _run():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    LOG.info("Starting HA Kuma Discovery 2.0.1")

    while True:
        started = time.monotonic()
        try:
            opts = read_options()
            sync_once(opts)
            sync_interval = opts["sync_interval"]
        except KeyboardInterrupt:
            return
        except Exception as exc:
            LOG.error("Sync failed (%s)", type(exc).__name__)
            try:
                sync_interval = read_options().get("sync_interval", 60)
            except Exception:
                sync_interval = 60

        elapsed = time.monotonic() - started
        sleep_for = max(1, sync_interval - elapsed)
        LOG.info("Sync cycle took %.1fs; next cycle in %.1fs", elapsed, sleep_for)
        time.sleep(sleep_for)


def main():
    try:
        _run()
    finally:
        HTTP.close()


if __name__ == "__main__":
    main()
