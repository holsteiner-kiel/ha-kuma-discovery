# HA Kuma Discovery 1.5.2

Home Assistant infrastructure and physical devices mirrored to Uptime Kuma.

## Setup and update

Add `https://github.com/holsteiner-kiel/ha-kuma-discovery` to the Home Assistant
app/add-on store, install HA Kuma Discovery and configure `kuma_url`,
`kuma_username` and `kuma_password`. Start the add-on and inspect its logs.
Home Assistant Supervisor is required. Architectures: amd64 and aarch64.

Existing repository installations can update from 1.5.1 through the store.
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

Unchanged Push monitors are refreshed about every 60 seconds. Kuma keeps its
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

Version 1.5.2 has automated regression tests. A live HA installation test remains
necessary after updating; the test suite does not replace that check.

## Optional integrations

Discovery options may remain enabled when their HA integrations are not installed.
Empty entry/device/entity lists are normal where no supported source exists;
they do not create monitors or report a failed integration. Empty host lookups
also avoid touching HA config-entry storage or warning about a missing mount.
Malformed responses and API failures still follow integration fault isolation;
they are not silently interpreted as an absent integration.
