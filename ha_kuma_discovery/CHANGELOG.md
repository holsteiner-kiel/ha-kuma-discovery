# Changelog

## 1.6.0

### Added
- Discover physical Homematic IP Local/HCU devices through enabled native
  Connectivity entities and create one Push monitor per physical device.
- Keep the HCU itself as the only Ping-based Homematic IP monitor; HAP access
  points now use the same Connectivity-based Push path as other physical devices.
- Add the MIT license, project URL and supplied icon/logo artwork.

### Fixed
- Send the current state for every successfully evaluated managed Push monitor
  during every sync cycle, removing the elapsed-time refresh edge case that could
  lead to `No heartbeat in the time window` after a missed cycle.
- Preserve immediate state changes, three-cycle DOWN debounce and immediate UP
  recovery without fabricating heartbeats for failed integrations.
- Treat an enabled discovery option with no installed matching Home Assistant
  integration as a normal no-op while still surfacing malformed data and API errors.

### Improved
- Identify whether Kuma failures occurred while opening the API session, logging
  in, fetching monitors/notifications, changing a monitor or sending a Push call.
  Logs continue to omit passwords, tokens, Push URLs and exception payloads.
- Replace installation-specific documentation examples with neutral examples.
- Expand automated behavior coverage from 19 to 41 tests.

### Compatibility
- Existing configuration, monitor prefixes, notification assignment, persisted
  state and backup recovery remain compatible; no new settings are required.
- Default 60-second sync, 180-second heartbeat window and three-cycle DOWN grace
  are unchanged. Existing monitors are reused and stale monitors are not deleted.

## 1.5.2

### Fixed
- A failed integration no longer skips the remaining enabled integrations.
- Successful Push timestamps and debounce counters are saved even after partial failures.
- Broken Home Assistant WebSocket transports are reopened for the next integration.
- State writes use a flushed temporary file and atomic replacement. The previous
  valid state is kept in `/data/state.json.bak` and recovered if the primary is missing
  or unreadable. Invalid primary files never overwrite a valid backup.

### Improved
- Supervisor requests and Kuma Push requests reuse HTTP connections through a
  shared session; authorization headers remain local to each request.
- Partial failures identify the integration and exception type without logging
  exception text that may contain secret Push URLs.
- Added 19 automated behavior tests, including real HTTP keep-alive verification.

### Compatibility
- Existing configuration and state format are retained; no new settings required.
- Default 60-second sync, 180-second heartbeat window and three-cycle DOWN
  debounce are unchanged. A failed integration remains subject to Kuma's normal
  heartbeat timeout; the add-on does not invent healthy status for missing data.

## 1.5.1

### Fixed
- Push monitors now receive a refresh heartbeat every sync cycle with the
  default 60-second sync interval.
- This prevents Uptime Kuma `No heartbeat in the time window` events caused by
  the previous ~120-second refresh cadence being too close to the heartbeat window.
- The Kuma Push monitor heartbeat window remains unchanged, preserving safety headroom.
- The 3-cycle DOWN debounce from 1.5.0 remains unchanged.

### Default behavior
```text
Healthy device      -> UP heartbeat about every 60 seconds
1st unavailable     -> stays UP
2nd unavailable     -> stays UP
3rd unavailable     -> DOWN
Available again     -> immediately UP
```

## 1.5.0

### Changed
- Generalized the MQTT-only DOWN debounce to all Home Assistant state-based Push monitors.
- New shared option: `push_down_grace_cycles: 3`.
- DOWN is sent only after three consecutive failed/unavailable sync cycles.
- UP is still sent immediately and resets the counter.

### Covered Push monitors
- MQTT / Zigbee2MQTT
- Matter
- Somfy / Overkiz child devices
- Philips Hue child devices
- Homematic IP access points

### Not affected
- Hue Bridge, TaHoma base, Homematic HCU and all other Ping-based monitors.

## 1.4.3

### Added
- Three-cycle DOWN debounce for MQTT and Zigbee2MQTT monitors.
- UP transitions are still reported immediately.
- A device is only reported DOWN after three consecutive sync cycles where
  Home Assistant reports it unavailable.
- The consecutive-DOWN counter is persisted in the add-on state across sync cycles.

### Default
- `mqtt_down_grace_cycles: 3`

With the default 60-second sync interval, a real MQTT/Zigbee2MQTT outage is
reported after roughly three minutes instead of immediately.

## 1.4.2

### Fixed
- Zigbee2MQTT battery remotes/buttons that only expose an enabled `event` entity
  are monitored again.
- Event-only fallback is restricted to physical Zigbee2MQTT devices.
- Generic MQTT devices with only button/event entities remain excluded.
- Zigbee2MQTT diagnostic-only devices with diagnostic-only entities remain excluded.

### Expected effect
- `Zigbee2MQTT: Example Remote` is included again.
- `MQTT: Example Bridge` remains skipped.
- `Zigbee2MQTT: Example Router` remains skipped.

## 1.4.1

### Fixed
- Generic MQTT devices that only expose button/event entities are no longer monitored.
- Zigbee2MQTT configuration/diagnostic entities such as `linkquality`, `last_seen`,
  `light_indicator_level` and `power_on_behavior` are no longer accepted as the
  sole device availability signal.
- Devices without a reliable enabled stateful availability entity are skipped
  instead of being created as permanently false DOWN monitors.

### Expected effect
- `MQTT: Example Bridge` is skipped.
- `Zigbee2MQTT: Example Router` is skipped when only diagnostic entities exist.

## 1.4.0

### Added
- MQTT physical-device monitoring via Home Assistant availability.
- Zigbee2MQTT devices and other MQTT devices are separated into two monitor namespaces.
- Physical Zigbee2MQTT devices are identified by IEEE-address MQTT identifiers (`zigbee2mqtt_0x...`).
- Zigbee2MQTT Bridge and Group objects are excluded.
- Generic MQTT devices such as water meters and heating controllers are supported.
- Devices with stateful entities use those entities for availability.
- MQTT devices that only expose button/event-style entities use a safe fallback where only explicit `unavailable` means DOWN.
- Existing cycle cache and Push-heartbeat throttling are reused, so the additional MQTT discovery does not re-download HA registries/states.

### New options
- `discover_zigbee2mqtt_devices` (default: true)
- `discover_mqtt_devices` (default: true)
- `zigbee2mqtt_monitor_prefix` (default: `Zigbee2MQTT: `)
- `mqtt_monitor_prefix` (default: `MQTT: `)

## 1.3.0

### Added
- Native ESPHome device monitoring.
- One Ping monitor per native ESPHome config entry with an explicit host.
- Monitor names come from the ESPHome config-entry title.
- Duplicate Bluetooth-proxy helper devices from other HA integrations are ignored.
- The ESPHome Device Builder add-on device is ignored.
- Default monitor prefix: `ESPHome: `.
- Default monitoring method: Ping.

## 1.2.0

### Added
- Native Synology DSM monitoring.
- Only the physical root NAS device is monitored.
- Drive, M.2, USB-disk and volume child devices are excluded.
- The Ping target is read directly from the native `synology_dsm` config entry.
- Old/stale Synology DSM entries without a host are skipped.
- Default monitor prefix: `Synology: `.

### Example
- `Synology: Example NAS` -> Ping `device.example`

## 1.1.0

### Added
- Native Stiebel Eltron ISG monitoring.
- The ISG host is read directly from the `stiebel_eltron_isg` config entry.
- The native physical device name/model is used for the Kuma monitor name.
- HACS metadata and UPnP representations are ignored.
- Default monitor prefix: `Stiebel Eltron: `.
- Default monitoring method: Ping.

### Example
- `Stiebel Eltron: Heat Pump` -> Ping `device.example`

## 1.0.1

### Fixed
- SMLIGHT host discovery now falls back to Home Assistant's local `core.config_entries` storage.
- This fixes installations where `config_entries/get` returns SMLIGHT entries without their `data.host` field.
- Native SMLIGHT config entries remain the source of truth; UniFi/Uptime Kuma/Zigbee2MQTT duplicates are still ignored.

## 1.0.0

### Added
- SMLIGHT support.
- Physical SMLIGHT coordinators are discovered directly from native Home Assistant `smlight` config entries.
- Each SMLIGHT device with an explicit `data.host` gets one Ping monitor.
- Default monitor prefix: `SMLIGHT: `.
- Duplicate representations from UniFi, Uptime Kuma and Zigbee2MQTT are ignored by design.
- Legacy/stale SMLIGHT config entries without an explicit host are skipped.

### Current SMLIGHT behavior
- `SLZB-Ultima3` -> Ping to its native SMLIGHT integration host.
- `SLZB-06P10` -> Ping to its native SMLIGHT integration host.
- `SLZB-06P7` is skipped when its SMLIGHT config entry does not expose a host.

## 0.10.2

### Performance
- One shared authenticated Home Assistant WebSocket connection is used for the complete sync cycle.
- Identical Home Assistant WebSocket requests are cached during the cycle.
- Large Device Registry, Entity Registry and state responses are downloaded once and reused by the discovery modules.
- Hue bridge-only mode no longer loads Device Registry, Entity Registry or all HA states.
- Unchanged Push monitor heartbeats are rate-limited; UP/DOWN changes are still pushed immediately.
- With the default 180 s heartbeat and 60 s sync interval, unchanged Push monitors are refreshed about every 120 s.
- Added WebSocket request/cache statistics to the log.

## 0.10.1

### Fixed
- Hue child-device discovery now includes only physical devices.
- Hue `Room` and `Zone` objects are excluded explicitly.
- Logical Hue devices without their own MAC connection are excluded.
- Hue scenes are not considered for availability and do not create monitors.
- Physical Hue-compatible devices from other manufacturers remain supported when they have a native Hue identifier and MAC address.

## 0.10.0

### Added
- Philips Hue support.
- Hue Bridge monitoring via Ping using the native Hue integration's `data.host`.
- Optional Hue child-device monitoring via Push monitors based on native Hue entity availability.
- Hue child-device monitoring is disabled by default.
- Duplicate/non-native network-discovery representations of Hue devices are ignored.
- Default monitor prefix: `Hue: `.
- Default Uptime Kuma notifications are assigned automatically.

### New options
- `discover_hue_bridge` (default: true)
- `discover_hue_devices` (default: false)
- `hue_ping_interval`
- `hue_max_retries`
- `hue_monitor_prefix`

## 0.9.3

### Fixed
- The TaHoma Switch / Overkiz base is monitored **only by Ping**.
- No additional Push monitor is created for the hub/base.
- Somfy child devices such as awnings, outdoor lights and light sensors keep their own Push monitors.

## 0.9.0

### Added
- Somfy/Overkiz monitoring.
- `Somfy: Tahoma Switch` is monitored by Ping using the local Overkiz config-entry host.
- Physical Overkiz child devices are monitored with Push monitors based on native Overkiz entity availability.
- No dependency on UniFi, FRITZ!Box or another network integration.
- Buttons and disabled diagnostic entities are ignored for availability.
- Default monitor prefix: `Somfy: `.
- Default Uptime Kuma notifications are assigned automatically.

### New options
- `discover_overkiz_devices`
- `overkiz_ping_interval`
- `overkiz_max_retries`
- `overkiz_monitor_prefix`

## 0.8.1

### Fixed
- E3/DC discovery now excludes Battery Pack and Battery Module child devices.
- The physical E3/DC controller must have a MAC connection and must not be a child (`via_device_id`).
- This leaves exactly one monitor for the actual S10E controller.

## 0.8.0

### Added
- E3/DC monitoring via the `e3dc_rscp` integration.
- Creates one Ping monitor for the physical E3/DC controller.
- Uses the integration's own `data.host` as the ping target.
- Battery packs and battery modules are intentionally ignored.
- No dependency on UniFi, FRITZ!Box or other network integrations.
- Default monitor prefix: `E3DC: `.
- Default Uptime Kuma notifications are assigned automatically.

### New options
- `discover_e3dc_devices`
- `e3dc_ping_interval`
- `e3dc_max_retries`
- `e3dc_monitor_prefix`

## 0.7.0

### Added
- Matter device monitoring.
- Discovers only physical devices from Home Assistant's native `matter` integration.
- Creates one `Matter: ...` Push monitor per Matter device.
- Uses Home Assistant/Matter entity availability rather than ICMP Ping, so
  Thread and battery-powered Matter devices can be monitored correctly.
- A device is UP when at least one enabled stateful Matter entity is available.
- A device is DOWN when all suitable enabled Matter entities are unavailable or unknown.
- `name_by_user` is preferred for monitor names.
- Default Uptime Kuma notifications are assigned automatically.

### New options
- `discover_matter_devices`
- `matter_monitor_prefix`

## 0.6.0

### Added
- Homematic IP infrastructure monitoring using only the `hcu_integration` integration.
- No dependency on UniFi, FRITZ!Box or other network integrations.
- `Homematic IP: HCU` is monitored by Ping using the HCU integration's own `data.host`.
- `Homematic IP: Access Point` is monitored through the HCU integration's own Connectivity binary sensor.
- Only infrastructure devices `HmIP-HCU1` and `HmIP-HAP` are included; normal Homematic IP actors, sensors and groups are ignored.
- Default Uptime Kuma notifications are assigned automatically.

### New options
- `discover_homematic_ip_infrastructure`
- `homematic_ip_ping_interval`
- `homematic_ip_max_retries`
- `homematic_ip_monitor_prefix`

## 0.5.0

### Added
- Fully Kiosk Browser discovery.
- Creates exactly one Ping monitor per Fully Kiosk config entry / physical tablet.
- Uses the Fully Kiosk config-entry `data.host` as the ping target.
- Uses the matching Home Assistant device name and area for friendly, unique monitor names.
- Default monitor prefix: `Fully Kiosk: `.
- Default Uptime Kuma notifications are assigned automatically.

### Example devices
- Wall-mounted tablets with a native Fully Kiosk config entry and local host.

## 0.4.0

### Added
- FRITZ!Box Tools network-infrastructure discovery.
- Creates Ping monitors only for native FRITZ! network products:
  - `FRITZ!Box`
  - `FRITZ!Repeater`
  - `FRITZ!Powerline`
- Explicitly excludes FRITZ!DECT, FRITZ!Smart Energy, groups, normal network clients, call-monitor devices and UPnP duplicates.
- Uses the FRITZ!Box Tools config-entry `data.host` as the management/ping address when no router `device_tracker` exists.
- Deduplicates physical FRITZ! network devices using MAC address where available.
- Uses the existing default Uptime Kuma notification assignment.

### New options
- `discover_fritz_network_devices`
- `fritz_ping_interval`
- `fritz_max_retries`
- `fritz_monitor_prefix`

## 0.3.7

### Fixed
- Cloud Gateway host discovery now reads the matching UniFi config entry from Home Assistant's local `.storage/core.config_entries`.
- Home Assistant's `config_entries/get` WebSocket response does not provide the private `data.host` value, which is why 0.3.6 could not see `device.example`.
- The Home Assistant configuration directory is mounted read-only at `/homeassistant`; the app reads only the UniFi entry's `data.host`.
- Public gateway tracker addresses are still rejected. If present, they are replaced by the private/local UniFi config-entry host.

### Example result
- `UCG Fiber` tracker: `203.0.113.10`
- UniFi config entry host: `device.example`
- Kuma target: `device.example`

## 0.3.6

### Added
- Cloud Gateway local-management IP fallback via the Home Assistant UniFi config entry.
- If a UniFi gateway tracker exposes a public WAN IP, HA Kuma Discovery now uses the matching UniFi config entry `data.host` instead.
- This keeps switches/APs on their own tracker IPs while allowing the UniFi console/gateway itself to be monitored on its local management address.

### Example
For the UniFi config entry used by the gateway:
- tracker IP: `203.0.113.10` (public WAN)
- config entry host: `device.example` (local management)
- resulting Kuma ping target: `device.example`

## 0.3.5

### Fixed
- UniFi monitor names now come from the UniFi `device_tracker` entity registry `original_name`.
- This is the field where Home Assistant stores the real UniFi controller device name, e.g. `Office AP`, `Core`, `UCG Fiber`, etc.
- MAC addresses remain used only for matching the infrastructure device to its tracker/IP.
- Previous fallback naming remains in place only if the tracker does not expose a usable name.

### Illustrative registry data
Example:
- device registry name: `02:00:00:00:00:01`
- tracker unique_id: `02:00:00:00:00:01`
- tracker original_name: `Office AP`

The app now uses `Office AP`.

## 0.3.4

### Fixed
- UniFi monitor names no longer use action-button labels such as `<MAC> Neu starten`.
- Device-registry names are now authoritative and preferred first (`Core`, `USW-Flex-...`, `U6-Pro-...`, `UCG Fiber`, etc.).
- Fallback naming now uses only stable infrastructure status sensors such as `State/Zustand`, `Uptime/Betriebszeit`, `Clients`, CPU and memory sensors.
- Button, update, light and port-switch friendly names are excluded from naming.

### Existing incorrect monitors
- Remove the old MAC / `Neu starten` / `Firmware` monitors after the correctly named replacements are visible.

## 0.3.3

### Fixed
- UniFi monitor naming no longer falls back to the generic `Firmware` label.
- Friendly names are now taken from the HA device registry and live entity `friendly_name` attributes, especially the UniFi `State` / `Zustand` sensor.
- Generic names such as `Firmware`, `Update`, and MAC-address labels are rejected.
- Duplicate friendly names can no longer overwrite one another; the IP is appended only when two distinct devices still resolve to the same display name.
- Public IP addresses from gateway trackers are rejected, preventing a Cloud Gateway WAN IP from being used as its management ping target.
- Generic ping-monitor log messages no longer incorrectly say `Shelly` for UniFi monitors.

### Existing bad monitors
- Remove the old `UniFi: Firmware` monitor after 0.3.3 creates the correctly named monitors.
- Any old MAC-named UniFi monitors from 0.3.1/0.3.2 can also be removed once the replacements are verified.

## 0.3.2

### Fixed
- UniFi monitor names no longer use MAC addresses such as `02:00:00:00:00:01`.
- Friendly infrastructure names from the Home Assistant UniFi device registry are preferred.
- MAC-shaped `name_by_user` / tracker labels are explicitly rejected.
- Firmware/update suffixes are stripped when an update-entity name is used as a fallback.

### Existing monitors
- Uptime Kuma monitors created by 0.3.1 with MAC-address names are not deleted automatically.
- After 0.3.2 creates the correctly named monitor, delete the old MAC-named monitor once.

## 0.3.1

### Fixed
- UniFi infrastructure IP discovery now uses Home Assistant's dedicated UniFi `device_tracker` entities.
- The physical UniFi device MAC from the HA device registry is matched to the tracker unique ID, then the tracker's live `ip` attribute is used for the Kuma ping monitor.
- Added a clear log message when **Track network devices** is not enabled in the Home Assistant UniFi Network integration.

### Required Home Assistant setting
In **Settings â†’ Devices & services â†’ UniFi Network â†’ Configure**, enable:

**Track network devices**

This creates device tracker entities for Ubiquiti network devices such as switches and access points. You do **not** need to enable tracking of ordinary network clients.

## 0.3.0

### Added
- Automatic UniFi Network infrastructure discovery.
- Creates one Uptime Kuma ping monitor for each UniFi gateway/cloud gateway, switch, and access point found through the Home Assistant UniFi Network integration.
- Ordinary wired and wireless network clients are intentionally excluded.
- Infrastructure devices are identified by the UniFi integration's firmware-update entities, which are created for managed UniFi network devices rather than normal clients.
- UniFi monitor IP/hostname is taken from live Home Assistant entity-state attributes.
- UniFi monitors automatically receive the active default Uptime Kuma notifications.
- Existing UniFi monitor hostnames/IPs are updated automatically when Home Assistant reports a changed address.

### Configuration
- `discover_unifi_network_devices: true`
- `unifi_ping_interval: 60`
- `unifi_max_retries: 2`
- `unifi_monitor_prefix: "UniFi: "`

### Notes
- If Home Assistant does not expose an IP attribute for a managed UniFi device, the app logs that device and skips it rather than guessing.
- UniFi clients such as phones, TVs, computers and IoT devices are not added.

## 0.2.2

### Fixed
- Fixed Shelly discovery crash caused by a missing Python `re` import.
- Shelly deduplication by IP/hostname from 0.2.1 now runs correctly.

## 0.2.1

### Fixed
- Shelly discovery now deduplicates devices by IP/hostname instead of Home Assistant device ID.
- Multi-channel Shellys now create exactly one Uptime Kuma ping monitor per physical device.
- Common Home Assistant subdevice suffixes such as `Output 0`, `Energy Meter 1`, `Channel 0`, `Switch 0`, `Input 0`, `Relay 0`, `Light 0`, and `Cover 0` are removed when choosing the monitor name.
- When multiple Home Assistant device entries share one Shelly IP, the app chooses a stable base device name and logs the collapsed entries.

### Notes
- Existing duplicate Shelly monitors created by 0.2.0 are not deleted automatically. Remove those one time from Uptime Kuma after verifying the new consolidated monitor.
- Add-on discovery, default Uptime Kuma notifications, 60-second sync cadence, and 180-second push heartbeat tolerance are unchanged from 0.1.2/0.2.0.

## 0.2.0

### Added
- Automatic Shelly discovery through the Home Assistant device registry.
- One Uptime Kuma ping monitor per discovered Shelly host.
- Automatic IP/hostname updates for existing Shelly ping monitors.
- Automatic assignment of Uptime Kuma default notifications.
