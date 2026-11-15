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

    pushed = skipped = failed = 0
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

        # Disabled Kuma monitors are an intentional operator decision. Kuma
        # rejects pushes to them, so leave them disabled and continue.
        if monitor.get("active", 1) in (0, False, "0", "false", "False"):
            skipped += 1
            log.info("Skipping inactive Uptime Kuma monitor: %s (%s)", monitor_name, slug)
            continue

        up = status == "started"
        try:
            sent = push_status_if_needed(
                opts["kuma_url"],
                monitor,
                up,
                f"Supervisor state: {status} | slug: {slug}",
                opts["verify_ssl"],
                state,
                opts["heartbeat_interval"],
                opts["sync_interval"],
            )
        except Exception as exc:
            failed += 1
            # Never print exception messages: HTTPError may embed Push tokens.
            response = getattr(exc, "response", None)
            code = getattr(response, "status_code", None)
            log.warning(
                "Add-on heartbeat failed: %s (%s), %s, HTTP status=%s; continuing",
                monitor_name, slug, type(exc).__name__,
                code if isinstance(code, int) else "unknown",
            )
            continue
        if sent:
            pushed += 1
        log.info("%s (%s) -> %s%s", monitor_name, slug,
                 "UP" if up else "DOWN", "" if sent else " (cached)")

    log.info("Add-on sync: %d discovered, %d heartbeats sent, %d inactive skipped, %d failed",
             len(discovered), pushed, skipped, failed)

    state["known_slugs"] = sorted(addon["slug"] for addon in discovered)
    state["names"] = {
        addon["slug"]: (addon.get("name") or addon["slug"])
        for addon in discovered
    }
