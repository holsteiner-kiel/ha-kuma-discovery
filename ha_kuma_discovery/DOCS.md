# HA Kuma Discovery 2.0.0

Home Assistant infrastructure and physical devices mirrored to Uptime Kuma.

## Setup and update

Add `https://github.com/holsteiner-kiel/ha-kuma-discovery` to the Home Assistant
app/add-on store, install HA Kuma Discovery and configure `kuma_url`,
`kuma_username` and `kuma_password`. Start the add-on and inspect its logs.
Home Assistant Supervisor is required. Architectures: amd64 and aarch64.

Installations download the prebuilt GHCR image matching the app version.
Maintainers: see [container publishing and release preparation](../PUBLISHING.md).

Existing repository installations can update from 1.5.1, 1.5.2 or 1.6.0 through the store.
Configuration and the state format remain compatible. Create a Home Assistant
backup before updating. Only one discovery instance should run against the same
managed Kuma monitors.

## Heartbeat behavior

With the default configuration:

```yaml
sync_interval: 60
heartbeat_interval: 180
push_down_grace_cycles: 3
```

Every successfully evaluated Push monitor sends its current state each sync
cycle, including unchanged states; there is no elapsed-time refresh gate. Kuma keeps its
180-second heartbeat window. State-based Push devices report DOWN after three
consecutive unavailable observations and recover immediately when observed UP.
Ping-based monitors retain their existing behavior.

## Reliability in 1.5.2

An integration error is logged and remaining integrations still run. The summary
identifies partial failures. Successful work is saved, including Push timestamps
and debounce counters. A global HA/Kuma connection failure can still prevent
the cycle from completing. Failed integrations do not receive fabricated UP
heartbeats; Kuma's configured timeout remains in effect. Calls remain sequential,
so a slow request can still delay later integrations.

State is saved through a temporary file and atomic replacement. The previous
valid state is backed up to `/data/state.json.bak`. If the primary state is missing,
invalid JSON or not a JSON object, the backup is tried and recovery is logged.
If neither file is usable, discovery starts with empty state and logs a warning.
This backup supplements Home Assistant backups; it does not replace them.

HTTP connections are reused. Supervisor authorization is sent only on Supervisor
requests. Error summaries omit exception text to avoid exposing secret Push URLs.

## Troubleshooting

- `Integration sync_... failed (...)`: this integration failed; check the named
  integration in HA and connectivity to Kuma. Other integrations continue.
- `Sync partially completed`: inspect the listed failed integrations.
- `Recovered state from backup`: a previous valid state was recovered; if repeated,
  check storage health and available space.
- `Sync cycle took ...`: if cycles approach the heartbeat window, inspect slow or
  failing integrations and network connections.

Version 2.0.0 has 50 automated behavior tests plus five image-policy tests. A live HA installation test remains
necessary after updating; the test suite does not replace that check.

## Push reliability and Kuma diagnostics in 1.6.0

The default 60-second sync and 180-second heartbeat window are unchanged.
With typical 8–13-second successful cycles, one missed cycle leaves headroom;
repeated failures or very long cycles can still exceed Kuma's window.
An integration failure does not generate substitute UP heartbeats. Successful
heartbeats already sent in a partially failed cycle remain saved; a failed Push
request never advances its saved timestamp or reported state. DOWN observations
still use the existing three-cycle grace and UP recovery remains immediate.

`Kuma operation failed: ... (ExceptionType)` identifies session opening, login,
monitor/notification fetching, monitor creation/update or the Push HTTP call.
These messages deliberately omit exception text, request URLs and credentials.
The ordinary integration/global failure summary follows the stage diagnostic.
Successful cycles also log the duration of session opening, login and the initial
Kuma reads, followed by one compact timing summary for all enabled integrations.
This makes slow stages visible without logging Push URLs, tokens or credentials.

## Homematic IP physical devices in 1.6.0

`discover_homematic_ip_infrastructure` retains its existing name and now covers
physical HCU integration devices with an enabled native Connectivity binary
sensor. Enable that entity in Home Assistant if you want the device monitored.
The HCU remains `Homematic IP: HCU` via Ping. HAP access points and physical child
devices use one `Homematic IP: <HA device name>` Push monitor each.
Existing HAP monitor names and the debounce state are reused. No monitor is
automatically deleted, and there is no separate HAP discovery path.

Native `unreach` entities are preferred; native Connectivity device-class metadata
is the fallback. HA `on` means connected; `off`, `unavailable`, `unknown` or a
missing live state count as DOWN observations. The shared three-observation grace
and immediate UP recovery apply. Disabled entities/devices, service entries,
virtual/logical devices, groups, rooms and helpers are excluded. Hardware model
prefixes follow the upstream integration; unrecognized models are skipped.
Keep HA device names unique, as the existing Kuma lookup is name-based.

Sources: [HCU binary sensor semantics](https://github.com/Ediminator/homematicip-hcu/blob/main/custom_components/hcu_integration/binary_sensor.py),
[registry metadata](https://github.com/Ediminator/homematicip-hcu/blob/main/custom_components/hcu_integration/entity.py)
and [physical model prefixes](https://github.com/Ediminator/homematicip-hcu/blob/main/custom_components/hcu_integration/const.py).

## Optional integrations in 1.6.0

Discovery options may remain enabled when their HA integrations are not installed.
Empty entry/device/entity lists are normal where no supported source exists;
they do not create monitors or report a failed integration. Empty host lookups
also avoid touching HA config-entry storage or warning about a missing mount.
Malformed responses and API failures still follow integration fault isolation;
they are not silently interpreted as an absent integration.

## AirGradient in 2.0.0

Native Home Assistant AirGradient devices receive one Ping monitor each using
the integration's explicit `data.host` (read from HA storage when the WebSocket
entry omits it). The physical device's HA name is used with `AirGradient: `.
Without a name, the entry title and native serial identify the device; duplicate
names are serial-qualified. No address is derived from entity names or guessed.
Missing/invalid hosts are skipped with an informational message. An absent
integration or empty device registry is a normal no-op, even when enabled.

```yaml
discover_airgradient_devices: true
airgradient_ping_interval: 60
airgradient_max_retries: 2
airgradient_monitor_prefix: "AirGradient: "
```

Existing same-name Ping monitors are reused and their hosts updated when HA
changes the address. Default notification assignment follows the other Ping
integrations. As elsewhere, renaming a device can leave an old monitor for manual
review; the app does not delete monitors. Keep user-assigned device names unique.

Sources: [native entry host](https://github.com/home-assistant/core/blob/dev/homeassistant/components/airgradient/config_flow.py)
and [physical registry identifiers](https://github.com/home-assistant/core/blob/dev/homeassistant/components/airgradient/entity.py).
