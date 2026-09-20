"""Home Assistant add-on discovery and Push monitor synchronization."""


def sync(
    opts,
    api,
    monitors,
    default_notification_ids,
    state,
    supervisor_get,
    ensure_push_monitor,
    push_status_if_needed,
    log,
):
    addons = supervisor_get("/addons") or {}
    addon_list = addons.get("addons", addons if isinstance(addons, list) else [])

    discovered = []
    for addon in addon_list:
        slug = str(addon.get("slug", ""))
        name = str(addon.get("name", slug))
        if not slug:
            continue
        if slug in opts["ignore_slugs_set"]:
            log.info("Ignoring %s (%s)", name, slug)
            continue
        if slug.endswith("_ha_kuma_discovery") or name == "HA Kuma Discovery":
            continue
        discovered.append(addon)

    log.info("Supervisor returned %d monitored add-ons", len(discovered))

    for addon in discovered:
        slug = addon["slug"]
        name = addon.get("name") or slug
        status = str(addon.get("state") or "unknown").lower()
        monitor_name = f'{opts["monitor_prefix"]}{name}'

        monitor = ensure_push_monitor(
            api,
            monitors,
            monitor_name,
            opts["heartbeat_interval"],
            default_notification_ids,
            state=state,
            identity=f"addon:{slug}",
        )

        up = status == "started"
        push_status_if_needed(
            opts["kuma_url"],
            monitor,
            up,
            f"Supervisor state: {status} | slug: {slug}",
            opts["verify_ssl"],
            state,
            opts["heartbeat_interval"],
            opts["sync_interval"],
        )
        log.info("%s (%s) -> %s", monitor_name, slug, "UP" if up else "DOWN")

    state["known_slugs"] = sorted(addon["slug"] for addon in discovered)
    state["names"] = {
        addon["slug"]: (addon.get("name") or addon["slug"])
        for addon in discovered
    }
