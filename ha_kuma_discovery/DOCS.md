# HA Kuma Discovery 1.5.1

Version 1.5.1 makes Push heartbeat delivery more robust.

With the default configuration:

```yaml
sync_interval: 60
heartbeat_interval: 180
push_down_grace_cycles: 3
```

the add-on now refreshes unchanged Push monitors every sync cycle (about every
60 seconds), while Uptime Kuma still keeps its 180-second heartbeat window.

This gives substantially more headroom against delayed or occasionally missed
sync cycles and avoids false `No heartbeat in the time window` alerts.

The three-cycle DOWN debounce remains unchanged.
