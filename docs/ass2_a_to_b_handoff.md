# Assignment 2 A 到 B 交接说明

更新日期：2026-10-27。交接分支为 `dengjie`，基于 Yeh 的 `60d4587` 架构；本轮代码、测试和验收报告随仓库提供，正式数据另行交付。

A 已完成站点读取、一天全部 DC 数据生成、事件转换、JSON 导出和发布端代码。
离线验收和本机真实 MQTT 联调均已完成。使用 Yeh 的订阅、持久化、去重和当前状态代码，成功接收并存储了正式数据中 00:00-04:00 的 1,893 条唯一事件。

## 接手文件和接口

| 文件 | 用途 |
|---|---|
| [`data_generator_config.py`](../transaction_scripts/data_generation_and_publishing/data_generator_config.py) | 日期、路径、站点筛选和模拟参数 |
| [`data_generator_utils.py`](../transaction_scripts/data_generation_and_publishing/data_generator_utils.py) | 站点适配、AEMO 价格、CSV 生成、有序事件流和 JSON 保存 |
| [`data_generator_daemon.py`](../transaction_scripts/data_generation_and_publishing/data_generator_daemon.py) | A 的生成、导出和发布入口 |
| [`evc_dao.py`](../repository/evc_dao.py) | 读取 Ass1 站点，保留原 charger_id |
| [`ev_charger_state_event.py`](../repository/event/ev_charger_state_event.py) | 四类事件及 JSON 编解码 |
| [`y_mqtt_simple_repo.py`](../repository/y_mqtt_simple_repo.py) | Yeh 的 MQTT 客户端和可选 inline broker |
| [`y_mqtt_event_subscriber.py`](../repository/y_mqtt_event_subscriber.py) | B 的订阅、解码和消息处理线程 |
| [`save_subscribed_data.py`](../transaction_scripts/stateful_event_storage/save_subscribed_data.py) | B 的去重、状态恢复和事务写入 |
| [`evc_event_dao.py`](../repository/entity/evc_event_dao.py) | B 的事件及状态读写、历史事件和运行统计 |
| [`nsw_evc_events_schema.sql`](../db/schema/nsw_evc_events_schema.sql) | charger_event、charger_state、connector_state |
| [`check_mqtt_storage.py`](../scripts/check_mqtt_storage.py) | 使用真实 broker、Yeh 订阅端和独立数据库副本进行联调对账 |

`repository/evc_state_dao.py` 虽然仍是占位文件，但 B 的实际实现已经位于上表所列文件。
A 的站点连接默认只读，生成前读取完毕后关闭；B 使用共享 DuckDB 写入连接。
`EVChargerEventStore.save(event)` 已处理重复事件、状态校验、事务提交和首次访问时的历史恢复。

## 正式数据和提交文件

老师最新说明要求至少 10,000 条小时价格、约 4,000 个会话，不再要求 14 天。
当前正式数据位于 `data/ass2_dc_1day/`，日期为 2026-09-15，固定 AEST（UTC+10），种子 `5339`，会话参数 `3 2`，meter 间隔 5 分钟。

| 数据或事件 | 数量 |
|---|---:|
| 全部 DC 站点 | 433 |
| 小时价格 | 10,392 |
| 会话 | 4,724 |
| meter 记录 | 29,991 |
| 去除连续不变价格后的 price_update | 4,330 |
| 全部待发布事件 | 43,769 |

当前 `run_id` 为 `13554f045be3439d99f472bcbea147b9`。重新生成会改变运行标识；回放原文件保持不变。

- `stations_input.csv`：老师输入格式的七列 `station_id,name,lat,lon,site_type,connectors,max_kw`。
- `stations.csv`：项目站点信息，使用 `charger_id`，额外保留假设和基础价格。
- `prices_hourly.csv`、`sessions.csv`、`session_metering.csv`：完整生成数据。
- `manifest.json`：参数、来源、运行标识及数量。
- `prepared_events.json`：完整待发布消息列表，已按事件时间排序和价格去重。
- `replay_00_04/prepared_events.json`、`replay_00_04/published_events.json`：此次真实四小时回放的两份事件列表，各 1,893 条，是该次提交对应的事件 JSON。
- `replay_00_04/duplicate_check_events.json`：四类各一条的额外重复发布记录，用于去重检查。
- `replay_00_04/subscriber.duckdb`：包含原 Ass1 表和真实订阅入库结果的独立数据库。
- `acceptance.json`：最新本地离线验收记录，模拟 MQTT 传输与真实发布明确分开。

`station_id`、`charger_id`、消息的 `object_id` 表示同一 Ass1 站点；消息中使用字符串，数据库中使用整数。
已有站点名称保留，缺少名称时使用运营商和地址。旧名称备份位于 `data/ass2_smoke/station_names_before_20261027/`。
源数据、AEMO 缓存和事件 JSON 保存在本地忽略目录中，交接或提交时需要单独提供这些文件。

生成与离线导出命令（在仓库根目录运行；重新生成会覆盖所选目录中的 CSV）：

```bash
# Use the team's Assignment 1 database and a new output directory for regeneration.
python -m transaction_scripts.data_generation_and_publishing.data_generator_daemon --db /path/to/shared-ass1.duckdb --out data/ass2_dc_1day --start 2026-09-15 --days 1 --seed 5339 --charger-type DC --sessions-per-connector-day 3 2 --meter-every 5 --export-events

# Export existing CSVs without regeneration or MQTT publication.
python -m transaction_scripts.data_generation_and_publishing.data_generator_daemon --out data/ass2_dc_1day --replay --export-events
```

老师允许只回放几小时，但当前发布入口尚未提供时间窗口参数，`--replay --publish` 会发送选中目录内的全部事件。
正式数据完整回放按每条至少 0.1 秒计算，需要至少约 73 分钟，加上网络和处理时间。
未来增加窗口时，必须保留开始前的价格及未结束会话上下文，不能直接丢弃窗口前的 session_start。

## 消息约定

Topic 为 `evc/<type>/<object_id>`，例如 `evc/meter/2`。B 订阅 `evc/#`，当前默认 QoS 1、`retain=False`。

| 字段 | 含义 |
|---|---|
| `schema_version` | 当前为整数 1 |
| `run_id` | 一次生成的运行标识 |
| `id` | 稳定事件 ID；B 存入数据库的 event_id 列，用于去重 |
| `type` | price_update、session_start、meter、session_end |
| `ts` | 带时区的 ISO 时间，消息统一为 UTC |
| `object_id` | Ass1 charger_id 的规范数字字符串 |
| `connector_id` | 站点内部从 1 开始的模拟端口号，不是 Ass1 端口表的主键 |
| `session_id` | 会话标识，跨运行保存时与 run_id 一起使用 |
| `payload` | 下表中的事件属性 |

| 事件 | payload 必填字段 | 可选字段 |
|---|---|---|
| price_update | price_per_kwh | wholesale_per_kwh |
| session_start | price_per_kwh | vehicle_model |
| meter | power_kw, energy_kwh | voltage_v, current_a, soc_pct |
| session_end | charge_end_ts, charge_minutes, energy_kwh, price_per_kwh, cost_aud | avg_kw, peak_kw |

价格事件的端口和会话标识为 null。价格单位为 AUD/kWh，功率为 kW，电量为 kWh，时长为分钟，费用为 AUD，SoC 为百分数；批发价格允许负值。
meter 电量为会话累计值，不能直接累计每条 meter 的电量。`session_end.ts` 是拔枪时间，`charge_end_ts` 是停止充电时间。
同一时间的事件顺序为价格、meter、会话结束、会话开始；开始事件携带该会话固定的计费价格。

## Broker 和数据库配置

1. `YSimpleMqttRepository` 有 `is_inline_broker` 开关；A 独立入口通过 `--inline-broker` 控制，不加该参数时使用已有 broker。
2. `main_ass_2.py` 总入口目前固定使用 inline broker，并自动启动订阅端及发布端；它不是离线生成入口。使用它时不要在同一端口再启动 Mosquitto。
3. 若使用外部 Mosquitto，按 [LAN MQTT 说明](../mqtt/README.md)启动，再分别运行 B 订阅端和 A 独立发布入口。
4. A 本机连接 127.0.0.1；B 在另一台电脑上连接 A 当前的 LAN IP。历史地址 192.168.1.3 需要重新确认。
5. B 通过公共配置 `DB_DATA` 选择数据库；A 的 `--db` 只控制站点读取。总入口还没有把这个参数传给 B，联调前必须确认两边使用一致的 Ass1 站点映射。

`config.py` 和 `repository/repo_config.py` 是共享设置入口。使用 inline broker 还需要安装 amqtt。
发布前让 B 完成订阅确认；broker ACK 只代表 broker 已接收，不代表 B 已写入数据库。

## 联调验收与当前状态

正式数据的完整回放应得到 4,330 条价格变化、4,724 条开始、29,991 条 meter 和 4,724 条结束事件。
如果只回放经过正确准备的子集，以该次 `published_events.json` 的事件 ID 集合为准。
双方核对入库事件 ID、各类型数量、站点关联、当前状态，并确认重复回放不增加唯一事件数量。
发布失败时不会继续发送；已确认的消息保留在发布记录中。重新回放从头开始，B 按稳定 ID 去重。
重复导出或发布会替换相应 JSON 文件，需保留的旧发布记录应先另存。

本地[离线验收报告](ass2_a_acceptance.json)包括：38 项单元测试、全部正式数据检查、43,769 条事件通过发布代码的模拟传输、5 份 CSV 的重新生成一致性，以及两个正式 DC 站点的 192 条事件直接入库、状态恢复和去重。
上述离线模拟没有联网；后续已完成独立的真实 MQTT 联调，见 [真实入库对账报告](ass2_mqtt_storage_validation.json)。

在安装项目依赖后，可在仓库根目录重跑这 38 项离线测试：

```bash
PYTHONPATH=tests python -m unittest test_data_generator test_entities test_generator_publisher.PublisherTests test_station_repository -v
```

此命令不包括需要 amqtt 的四项 inline broker 测试；真实联调使用外部 Mosquitto。

| 实际回放事件 | 数量 |
|---|---:|
| price_update | 1,299 |
| session_start | 75 |
| meter | 453 |
| session_end | 66 |
| 唯一事件合计 | 1,893 |

真实 broker 为本机隔离端口上的 Mosquitto 2.1.2。QoS 1，逐条至少间隔 0.1 秒，整个检查约 204 秒。
第 946 条后重启 B 的订阅线程和数据库连接，当时 9 个会话仍在进行，恢复后继续接收成功。
额外重发四类各一条事件，B 全部识别为重复；共收到 1,897 条消息，保留 1,893 条唯一事件。
发布记录与数据库的 ID 和内容逐条一致，433 个站点的当前状态正确，每站有三条历史价格；窗口结束时保留 9 个活动会话。
副本中的 Ass1 原始 1,958 个站点完整保留，事件站点关联无缺失，源数据库未改动。

这次按老师允许的几小时回放完成实际发布，没有发布完整一天的 43,769 条候选事件。
提交时将完整源 CSV 与四小时回放的事件 JSON、订阅数据库对应起来，在报告中说明回放窗口。
测试在 A 的电脑上调用 Yeh 的实际订阅和入库类完成；B 自己电脑的网络连通性及 C 的 dashboard 界面不属于本次验证。
临时测试 broker 已关闭，原 LAN broker 保持运行。代码、测试和两份验收报告纳入 Git；生成的 CSV、事件 JSON 和 DuckDB 保留在本地忽略目录，需要单独交付给 B。

历史记录保留在 [旧全量验证](ass2_full_validation.json)、[旧 MQTT 验证](ass2_mqtt_validation.json)和[旧 LAN 验证](ass2_mqtt_lan_validation.json)中。
其中 4,191 条样本的真实收发发生于旧版代码，不能替代新版联调。旧 14 天数据仍保存在 `data/ass2_generated/`，使用旧 station_id CSV 列名，不能直接作为新版 charger_id 回放输入。

OpenAI Codex assisted with the implementation, tests and this handoff document. Retain the code acknowledgements and complete the course AI usage report for submission.
