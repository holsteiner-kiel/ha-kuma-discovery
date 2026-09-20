# HA Kuma Discovery

![HA Kuma Discovery](ha_kuma_discovery/logo.png)

Home Assistant devices and infrastructure mirrored to Uptime Kuma.

Current version: **2.0.0**. Based on the original 1.5.1 add-on. Supports amd64 and aarch64.

## Installation

Add this repository in the Home Assistant app/add-on store:

```text
https://github.com/holsteiner-kiel/ha-kuma-discovery
```

Install **HA Kuma Discovery**, set `kuma_url`, `kuma_username` and `kuma_password` in its configuration, then start it and check its logs. Home Assistant Supervisor is required.

[Add repository to Home Assistant](https://my.home-assistant.io/redirect/supervisor_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fholsteiner-kiel%2Fha-kuma-discovery)

## Existing local installation

Keep a backup of the existing add-on configuration and data. A repository installation has a different add-on identity from a local installation; settings and `/data/state.json` are not migrated automatically. Stop the local copy before starting the repository copy, and verify the resulting Kuma monitors before removing the old installation.

## Version 2.0.0

With the default settings, every successfully evaluated Push monitor sends its current state each cycle. Kuma retains its 180-second heartbeat window and DOWN requires three consecutive unavailable cycles. Recovery is reported immediately.

Version 2.0.0 installs from signed, versioned GHCR images instead of compiling the container locally and adds native AirGradient Ping monitoring. Existing configuration and state remain compatible. See the changelog for details.

- [Configuration and operation](ha_kuma_discovery/DOCS.md)
- [Changelog](ha_kuma_discovery/CHANGELOG.md)

## Validation

GitHub Actions runs 50 behavior tests and five image-publication policy tests plus Python compilation, shell syntax, YAML metadata and native amd64/aarch64 container builds. These checks do not replace testing inside Home Assistant with a running Uptime Kuma instance.

## License

Licensed under the [MIT License](LICENSE).
