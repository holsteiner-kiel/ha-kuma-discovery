"""Push heartbeat delivery state and DOWN debounce handling."""

from typing import Any, Dict


def push_status(kuma_url, monitor, up, message, verify_ssl, http, operation):
    with operation("Push heartbeat HTTP call"):
        token = monitor.get("pushToken") or monitor.get("push_token")
        if not token:
            raise RuntimeError(f"Monitor '{monitor.get('name')}' has no push token")

        r = http.get(
            f"{kuma_url}/api/push/{token}",
            params={"status": "up" if up else "down", "msg": message[:250]},
            timeout=20,
            verify=verify_ssl,
        )
        r.raise_for_status()
        payload = r.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Push failed for '{monitor.get('name')}': {payload}")


def push_status_if_needed(
    kuma_url,
    monitor,
    up,
    message,
    verify_ssl,
    state,
    heartbeat_interval,
    sync_interval,
    sender,
    now,
):
    """Send every evaluated state; commit the successful heartbeat only after I/O.

    Keep the existing call signature and persisted cache format compatible.
    Callers must obtain a real observation before invoking this helper.
    """
    name = str(monitor.get("name") or monitor.get("id") or "unknown")
    sender(kuma_url, monitor, up, message, verify_ssl)
    state.setdefault("_push_status_cache", {})[name] = {
        "up": bool(up), "last_push": now(),
    }
    return True



def push_effective_up(
    state: Dict[str, Any],
    state_key: str,
    device_id: str,
    observed_up: bool,
    grace_cycles: int,
) -> tuple[bool, int]:
    """
    Debounce Home Assistant state-based Push monitor DOWN transitions.

    UP is reported immediately. DOWN is reported only after the configured
    number of consecutive unavailable sync cycles. The counter is persisted
    in the add-on state across sync cycles.
    """
    debounce = state.setdefault("_push_down_debounce", {})
    bucket = debounce.setdefault(state_key, {})
    entry = bucket.setdefault(device_id, {"down_cycles": 0})

    if observed_up:
        entry["down_cycles"] = 0
        return True, 0

    down_cycles = int(entry.get("down_cycles", 0)) + 1
    entry["down_cycles"] = down_cycles

    effective_up = down_cycles < grace_cycles
    return effective_up, down_cycles


