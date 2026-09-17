# HA Kuma Discovery

Home Assistant devices and infrastructure mirrored to Uptime Kuma.

Initial version: **1.5.1**, imported from the existing add-on archive. Supports amd64 and aarch64.

## Installation

Add this repository in the Home Assistant app/add-on store:

```text
https://github.com/holsteiner-kiel/ha-kuma-discovery
```

Install **HA Kuma Discovery**, set `kuma_url`, `kuma_username` and `kuma_password` in its configuration, then start it and check its logs. Home Assistant Supervisor is required.

[Add repository to Home Assistant](https://my.home-assistant.io/redirect/supervisor_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fholsteiner-kiel%2Fha-kuma-discovery)

## Existing local installation

Keep a backup of the existing add-on configuration and data. A repository installation has a different add-on identity from a local installation; settings and `/data/state.json` are not migrated automatically. Stop the local copy before starting the repository copy, and verify the resulting Kuma monitors before removing the old installation.

## Version 1.5.1

With the default settings, unchanged Push monitors receive a heartbeat about every 60 seconds. Kuma retains its 180-second heartbeat window and DOWN requires three consecutive unavailable cycles. Recovery is reported immediately.

The original application, configuration, Dockerfile, startup script and changelog are preserved from the supplied 1.5.1 archive.

- [Configuration and operation](ha_kuma_discovery/DOCS.md)
- [Changelog](ha_kuma_discovery/CHANGELOG.md)

## Validation

GitHub Actions checks Python compilation, shell syntax and YAML parsing on pushes and pull requests. These checks do not replace testing inside Home Assistant with a running Uptime Kuma instance.
