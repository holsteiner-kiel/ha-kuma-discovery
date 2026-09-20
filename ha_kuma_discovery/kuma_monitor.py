"""Uptime Kuma sessions, notifications, and managed monitor lifecycle."""

import json
import logging
import time
from contextlib import contextmanager, ExitStack
from typing import Any, Dict

from uptime_kuma_api import UptimeKumaApi, MonitorType


LOG = logging.getLogger("ha-kuma-discovery")


def normalize_items(raw):
    if isinstance(raw, dict):
        return list(raw.values())
    if isinstance(raw, list):
        return raw
    return []


def find_monitor(monitors, name: str, monitor_type: str):
    for monitor in monitors:
        if monitor.get("name") == name and monitor.get("type") == monitor_type:
            return monitor
    return None


def find_managed_monitor(monitors, name, monitor_type, state=None, identity=None):
    """Resolve a managed monitor by its persisted source identity before name."""
    if state is not None and identity:
        record = state.get("_monitor_identities", {}).get(identity, {})
        monitor_id = record.get("monitor_id")
        if monitor_id is not None:
            for monitor in monitors:
                if (str(monitor.get("id")) == str(monitor_id)
                        and monitor.get("type") == monitor_type):
                    return monitor

        previous_name = str(record.get("name") or "")
        if previous_name:
            previous = find_monitor(monitors, previous_name, monitor_type)
            if previous:
                return previous

    return find_monitor(monitors, name, monitor_type)


def remember_monitor_identity(state, identity, monitor, name, monitor_type):
    if state is None or not identity or not monitor or monitor.get("id") is None:
        return
    state.setdefault("_monitor_identities", {})[identity] = {
        "monitor_id": monitor["id"],
        "name": name,
        "type": monitor_type,
    }


def notification_is_default(notification: Dict[str, Any]) -> bool:
    if bool(notification.get("isDefault")):
        return True

    raw_config = notification.get("config")
    if isinstance(raw_config, str):
        try:
            return bool(json.loads(raw_config).get("isDefault"))
        except Exception:
            return False
    if isinstance(raw_config, dict):
        return bool(raw_config.get("isDefault"))
    return False


def notification_is_active(notification: Dict[str, Any]) -> bool:
    return notification.get("active", True) is not False


@contextmanager
def kuma_operation(stage, log_duration=False):
    """Report only our fixed stage and exception class, never request payloads."""
    started = time.monotonic()
    try:
        yield
    except Exception as exc:
        LOG.error("Kuma operation failed: %s (%s)", stage, type(exc).__name__)
        raise
    else:
        if log_duration:
            LOG.info("Kuma operation completed: %s in %.1fs",
                     stage, time.monotonic() - started)


def kuma_call(stage, operation, *args, _log_duration=False, **kwargs):
    with kuma_operation(stage, log_duration=_log_duration):
        return operation(*args, **kwargs)


@contextmanager
def kuma_session(opts, api_factory=UptimeKumaApi):
    with ExitStack() as stack:
        with kuma_operation("opening Kuma API session", log_duration=True):
            api = stack.enter_context(api_factory(
                opts["kuma_url"], timeout=30, ssl_verify=opts["verify_ssl"],
            ))
        yield api


def get_default_notification_ids(api) -> list[int]:
    notifications = normalize_items(kuma_call(
        "fetching notifications", api.get_notifications, _log_duration=True,
    ))
    ids = []
    for n in notifications:
        if notification_is_active(n) and notification_is_default(n):
            try:
                ids.append(int(n["id"]))
            except (KeyError, TypeError, ValueError):
                pass
    ids = sorted(set(ids))
    if ids:
        LOG.info("Using default Uptime Kuma notification(s): %s", ids)
    else:
        LOG.warning("No active default Uptime Kuma notification found")
    return ids


def monitor_notification_ids(monitor: Dict[str, Any]) -> list[int]:
    raw = monitor.get("notificationIDList")
    if isinstance(raw, dict):
        out = []
        for key, enabled in raw.items():
            if enabled:
                try:
                    out.append(int(key))
                except (TypeError, ValueError):
                    pass
        return sorted(set(out))
    if isinstance(raw, list):
        out = []
        for item in raw:
            try:
                out.append(int(item))
            except (TypeError, ValueError):
                pass
        return sorted(set(out))
    return []


def ensure_push_monitor(
    api, monitors, name, heartbeat_interval, default_notification_ids,
    state=None, identity=None,
):
    monitor = find_managed_monitor(monitors, name, "push", state, identity)

    if not monitor:
        LOG.info("Creating Uptime Kuma push monitor: %s", name)
        kwargs = {
            "type": MonitorType.PUSH,
            "name": name,
            "interval": heartbeat_interval,
            "retryInterval": heartbeat_interval,
            "maxretries": 0,
        }
        if default_notification_ids:
            kwargs["notificationIDList"] = default_notification_ids
        kuma_call("monitor creation", api.add_monitor, **kwargs)
        time.sleep(0.4)
        monitors[:] = normalize_items(kuma_call("fetching monitors", api.get_monitors))
        monitor = find_monitor(monitors, name, "push")
        if not monitor:
            raise RuntimeError(f"Could not retrieve created monitor '{name}'")
        remember_monitor_identity(state, identity, monitor, name, "push")
        return monitor

    edit = {}
    if str(monitor.get("name") or "") != name:
        edit["name"] = name
    current_interval = int(monitor.get("interval") or 0)
    if (
        current_interval != heartbeat_interval
        or int(monitor.get("retryInterval") or 0) != heartbeat_interval
        or int(monitor.get("maxretries") or 0) != 0
    ):
        edit.update(
            interval=heartbeat_interval,
            retryInterval=heartbeat_interval,
            maxretries=0,
        )

    current_notifications = monitor_notification_ids(monitor)
    if default_notification_ids and current_notifications != default_notification_ids:
        edit["notificationIDList"] = default_notification_ids

    if edit:
        LOG.info("Updating %s: %s", name, edit)
        kuma_call("monitor update", api.edit_monitor, int(monitor["id"]), **edit)
        time.sleep(0.2)
        monitors[:] = normalize_items(kuma_call("fetching monitors", api.get_monitors))
        monitor = find_managed_monitor(monitors, name, "push", state, identity)

    remember_monitor_identity(state, identity, monitor, name, "push")
    return monitor


def ensure_ping_monitor(
    api,
    monitors,
    name,
    host,
    interval,
    max_retries,
    default_notification_ids,
    state=None,
    identity=None,
):
    monitor = find_managed_monitor(monitors, name, "ping", state, identity)

    if not monitor:
        LOG.info("Creating ping monitor: %s -> %s", name, host)
        kwargs = {
            "type": MonitorType.PING,
            "name": name,
            "hostname": host,
            "interval": interval,
            "retryInterval": interval,
            "maxretries": max_retries,
        }
        if default_notification_ids:
            kwargs["notificationIDList"] = default_notification_ids
        kuma_call("monitor creation", api.add_monitor, **kwargs)
        time.sleep(0.4)
        monitors[:] = normalize_items(kuma_call("fetching monitors", api.get_monitors))
        monitor = find_monitor(monitors, name, "ping")
        if not monitor:
            raise RuntimeError(f"Could not retrieve created ping monitor '{name}'")
        remember_monitor_identity(state, identity, monitor, name, "ping")
        return monitor

    edit = {}
    if str(monitor.get("name") or "") != name:
        edit["name"] = name
    if str(monitor.get("hostname") or "") != host:
        edit["hostname"] = host
    if int(monitor.get("interval") or 0) != interval:
        edit["interval"] = interval
    if int(monitor.get("retryInterval") or 0) != interval:
        edit["retryInterval"] = interval
    if int(monitor.get("maxretries") or 0) != max_retries:
        edit["maxretries"] = max_retries

    current_notifications = monitor_notification_ids(monitor)
    if default_notification_ids and current_notifications != default_notification_ids:
        edit["notificationIDList"] = default_notification_ids

    if edit:
        LOG.info("Updating ping monitor %s: %s", name, edit)
        kuma_call("monitor update", api.edit_monitor, int(monitor["id"]), **edit)
        time.sleep(0.2)
        monitors[:] = normalize_items(kuma_call("fetching monitors", api.get_monitors))
        monitor = find_managed_monitor(monitors, name, "ping", state, identity)

    remember_monitor_identity(state, identity, monitor, name, "ping")
    return monitor


