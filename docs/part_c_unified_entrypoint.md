# Unified Assignment 2 Dashboard entry point

Run `python main_ass_2.py`. The program first prepares the requested generated
CSV dataset while it is the only database reader. It then starts exactly one
broker (inline by default), one `database-update` subscriber, and NiceGUI on
`http://127.0.0.1:8080/`. Once NiceGUI has started, a background thread replays
the prepared events after the configurable `--dashboard-delay`.

The event path is deliberately singular:

```text
MQTT event -> sub_database_update -> EventStore.save -> committed True
           -> sub_dashboard -> DashboardLiveService.notify_committed
           -> NiceGUI update
```

`sub_dashboard` is not a subscriber and does not write DuckDB. Duplicate,
invalid, or failed events do not reach it. In unified mode the DashboardLive
service is constructed with `start_subscriber=False`; it receives the committed
event callback from `main_ass_2.py` rather than creating a second writer.

For an already running broker use `--external-broker`. Do not use
`--inline-broker` in the forwarded generator arguments: the unified entry point
owns the broker. The Dashboard remains open after the publisher finishes; stop
it with Ctrl+C.

The upstream schema's mutable state rows contain only the latest Run for a
charger/connector. Dashboard historical Run views therefore replay
`charger_event`, the immutable event log, and do not query those rows by
`run_id`.
