# Unified Assignment 2 Dashboard entry point

Run `python main_ass_2.py`. The program starts exactly one broker (inline by
default), two subscribers registered side by side (`database-update`, which
stores events, and `dashboard-update`, which feeds the dashboard), and NiceGUI on
`http://127.0.0.1:8081/`. Once NiceGUI has started, the generator runs once in a
background thread: it generates the requested dataset, waits `--dashboard-delay`
seconds (10 by default) so the dashboard can be opened first, and publishes each
event once. The broker delivers that one message to both subscribers. If the
generator fails, the dashboard stops and `main_ass_2.py` raises the error.

The generator reads the Assignment 1 stations through the process's shared
DuckDB connection, which the dashboard and the event store also use: DuckDB will
not open the same file read-only in a process that already has it open read-write.

The port comes from the `DASHBOARD_PORT` environment variable (default 8081),
which the standalone dashboard also reads; `--dashboard-port` overrides it for
one run. If another program already listens on it, `main_ass_2.py` stops before
generating data and names the port.

Without generator arguments, each run replaces the previous demo dataset in
`data/ass2_demo/` but keeps its `aemo_cache/`, so prices are not downloaded again.
Explicit generator arguments such as `--out` keep the generator's refusal to
overwrite an existing dataset; add `--replay` to reuse one instead.

A page opened without `run_id` shows the run this process most recently started
receiving, so a browser opened after the replay has begun still follows it.

Storage and the dashboard subscribe independently. `main_ass_2.py` starts both
subscribers at once and waits until each has subscribed before NiceGUI serves
pages; the broker then delivers its own copy of every event to each:

```text
                     +-> database-update subscriber -> sub_database_update -> save_event, the sole writer
MQTT broker -- evc/# |
                     +-> dashboard-update subscriber -> DashboardDaemon.receive -> DashboardLiveService
                            -> each open page's DashboardRunModel -> NiceGUI update
```

The dashboard never writes DuckDB and never waits for storage: every page update
starts at the `dashboard-update` subscriber. When a page opens it reads its
stations and its run's stored history through `EVChargerInfoDAO` and
`EVChargerEventDAO`; after that it applies the run's MQTT events to its own
`DashboardRunModel`, with no database query per event. Each event must pass the
same `EVChargerState` transition rules as the event store, repeated deliveries
are ignored by event id, and recent MQTT events that storage has not saved yet are
replayed into a page as it opens. If storage fails, every page shows
"LIVE synchronization FAILED".

To run the dashboard on its own, use `python -m view.dashboard_daemon`. It reads
the database and follows an already-running broker, but stores nothing.

For an already running broker use `--external-broker`. The forwarded generator
arguments may not include `--inline-broker`: the unified entry point owns the
broker. The dashboard remains open after publishing finishes; stop it with
Ctrl+C. Stopping it while events are still being published ends the run there.

The upstream schema's mutable state rows contain only the latest Run for a
charger/connector. Dashboard historical Run views therefore replay
`charger_event`, the immutable event log, and do not query those rows by
`run_id`.
