# Step 3.3K — Parallel Task B and Task C MQTT processing

> **Superseded.** The `MqttCommitCoordinator` described below has been removed.
> Dashboard pages now follow their own `dashboard-update` subscriber directly, and
> no longer wait for Task B's commit; see
> [part_c_unified_entrypoint.md](part_c_unified_entrypoint.md).

## Root cause

The former unified callback called Dashboard processing directly after
`event_store.save(event)`. Task C was therefore a synchronous child of Task B, not an
independent MQTT consumer.

## Actual runtime flow

```text
                         +-> database-update subscriber (Task B)
MQTT broker -- same topic |      -> sole EventStore writer -> committed(event id)
                         |
                         +-> dashboard-update subscriber (Task C)
                                -> dashboard_received(event id), no DuckDB writes

              MqttCommitCoordinator joins both facts by event ID
                                -> DashboardLiveService.notify_committed(event)
```

Both subscribers are independent `YMqttEventSubscriber` threads and MQTT clients.
The coordinator is a bounded in-memory consistency barrier, not a callback chain: it
records either arrival order and releases exactly one notification only when both Task B
has committed and Task C has independently received that stable event ID.

It retains at most 10,000 pending/notified IDs, expires entries after five minutes, and
is cleared at shutdown. Rejected persistence removes pending state. Duplicate deliveries
cannot schedule another UI update. `DashboardLiveService(start_subscriber=False)`
remains UI-only, so Unified mode has exactly two subscribers and one writer.

## Evidence

`tests/test_parallel_mqtt_coordination.py` uses `threading.Event` to block Task B
inside `save()` while Task C completes its own callback. It asserts no notification
before release and exactly one after commit. The suite also covers reverse order,
rejection, duplicates, interleaved IDs, high frequency bounded state, two-subscriber
lifecycle, startup failure cleanup, and no Dashboard-owned subscriber/writer.
