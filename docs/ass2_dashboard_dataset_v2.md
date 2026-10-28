# Assignment 2 dashboard 数据 v2（历史版本）

本页保留 433 站点旧版记录。当前按 charger 与 charger_connector 交集生成的版本见 [最新交接](ass2_a_to_b_handoff.md)。本页旧数据和命令不应作为当前交付；新版回放拒绝无 station_scope 的旧 manifest。

更新日期：2026-10-28。基于 Yeh `b7e56d1` 的 DAO、MQTT 路径及状态表主键。
数据目录为 `data/ass2_dc_3day/`。旧一天数据、旧十四天数据和原 Ass1 数据库均保留。

这是按最新缩量要求采用的版本：保留全部 DC 站点以避免覆盖范围歧义，缩短日期并降低 meter 频率。
此前七天版保留在 `data/ass2_dc_7day/`，不再作为默认交付。其 MQTT 测试在 6,368 条确认消息后主动中断，目录内有 INCOMPLETE 标记，不能作为完整回放证据。

## 数据与假设

| 项目 | 新版 |
|---|---:|
| 日期 | 2026-09-14 至 2026-09-16，AEST UTC+10 |
| 全部 DC 站点 / 模拟充电头 | 433 / 1,658 |
| 小时价格 | 31,176 |
| 会话 | 4,000 |
| 每两分钟 meter | 60,036 |
| 待发布事件（价格已去重） | 81,459 |
| 重点增广站点 / 充电头 | 144 / 513 |
| 没有会话的充电头 | 0 |
| 单次会话 meter 点数中位数 | 13，上一版为 5 |

`aug` 在这里指 Ass1 数据增广。重点站点必须存在于 Ass1 的 `charger` 增广表，且 SA4 名称以 `Sydney` 开头。
采用原 Ass1 的 charger_id、坐标、功率和充电头数量；没有用外部冲突值覆盖原始站点数据。
增广表中的质量提示仍应在需要使用相应外部属性时查看，进入重点名单不代表每个外部属性都完美。

为保证展示覆盖，使用明确的模拟分配规则代替原 Poisson 会话数量：重点的每个头每天 1–2 次会话，其他头整个三天至少一次。
4000 条会话中先分配覆盖要求，再把额外会话分配给重点区域。开始时刻仍随机并使用原日内分布和价格弹性，充电过程仍调用老师提供的模拟器。
这不是实际观测到的利用率，不应用来推断 NSW 真实站点需求。价格使用缓存的真实 AEMO NSW1 2026 年 9 月批发数据。
不加 `--target-sessions` 时仍使用原随机模式，原默认参数没有被更改。

| 会话开始日期（AEST） | 数量 |
|---|---:|
| 09-14 | 1402 |
| 09-15 | 1191 |
| 09-16 | 1407 |

每天相对日均值最大偏差 10.67%。跨午夜会话保留完整结束和 meter 尾部，不截断或修改能量。
`connector_coverage.csv` 逐头列出三天会话数，可直接核对覆盖；重点 ID 列表保存在 `manifest.json` 的 `settings.focus_charger_ids`。

## 给 B/C 的文件

1. `stations_input.csv`：老师要求的七列站点输入；其 station_id 等于 Ass1 charger_id。
2. `stations.csv`、`prices_hourly.csv`、`sessions.csv`、`session_metering.csv`：完整三天模拟数据。
3. `manifest.json`、`validation.json`、`connector_coverage.csv`：运行参数、验收和逐头覆盖。
4. `prepared_events.json`：完整候选事件，不能描述为已全部发布。
5. `window_09_11/prepared_events.json`：9 月 15 日 09:00–11:00 加必要上下文，共 3,692 条。
6. `mqtt_09_11/`：真实 broker 联调通过的发布记录和订阅数据库，共 3,692 条唯一事件。
7. `offline_preview/`：完整三天历史开发预览库及说明。明确为离线导入，不是 MQTT 发布证明。

生成数据和数据库位于 Git 忽略目录，交接时需要单独提供。代码运行方式见主 README。
提交作业时应明确完整生成 CSV 与实际 MQTT 回放窗口的关系，提交实际发布事件 JSON 和真实订阅数据库。
事件 JSON 建议使用 `mqtt_09_11/` 下的 prepared、published 和 duplicate_check 三份；根目录的完整候选列表仅供全量回放开发参考。
不得把离线预览数据库说成经 MQTT 收到的数据库。

## Dashboard 查询约定

- 地图可以默认展示 144 个重点站点，再提供“全部 DC”选项。这里只生成 DC 事件，Ass1 其余 AC/Upcoming 站点没有模拟数据。
- 用 `(charger_id, connector_no)` 标识模拟充电头，编号为 `1..number_of_plugs`。
- Ass1 的 `charger_connector` 是连接器类型列表（如 CCS、CHAdeMO），不是物理头清单。不可拿其主键直接关联事件端口编号。
- 页面应先列出站点所有模拟头，再 LEFT JOIN `connector_state`。尚无事件时显示“尚无事件”，不能把缺失记录当成不存在的充电头。
- `charger_state`、`connector_state` 保存最新状态；趋势曲线从 `charger_event` 读取，按 charger_id、connector_no、session_id 筛选。
- Yeh 新版状态表主键不再包含 run_id，但历史事件仍带 run_id。使用同一数据集的 run_id，并用独立数据库进行不同回放，避免不同运行的当前状态混在一起。
- 历史按事件时间统计，不能按电脑当前时间。9 月 Sydney 时间是 AEST；统一时区后再分组日期。
- 空闲期间没有 meter 是正常现象，不要跨不同会话连接 SoC/累计电量曲线，也不要用补零掩盖缺失数据。
- 完整预览库处于所有会话结束后的最终状态，因此所有头空闲；实时曲线用 MQTT 回放过程中的数据库。
- 两小时 MQTT 库只有窗口与恢复所需上下文。上下文不代表完整的前一天历史；三天历史开发使用离线预览库，正式三天 MQTT 历史则需要实际回放对应事件。

按 AEST 统计会话开始数量：

```sql
SELECT CAST(event_ts AT TIME ZONE 'Australia/Sydney' AS DATE) AS session_date,
       COUNT(*) AS sessions
FROM charger_event
WHERE run_id = ? AND event_type = 'session_start'
GROUP BY 1 ORDER BY 1;
```

## 运行与验证

```bash
# Generate into a new directory to preserve an earlier run.
python -m transaction_scripts.data_generation_and_publishing.data_generator_daemon \
  --db /path/to/shared-ass1.duckdb --out data/ass2_dc_3day \
  --start 2026-09-14 --days 3 --seed 5339 --charger-type DC \
  --target-sessions 4000 --focus-region Sydney --meter-every 2 --export-events

python -m scripts.check_generator_coverage \
  --data-dir data/ass2_dc_3day --db /path/to/shared-ass1.duckdb

# Full-history development preview, explicitly not MQTT evidence; --out must be new.
python -m scripts.build_dashboard_preview \
  --data-dir data/ass2_dc_3day --db /path/to/shared-ass1.duckdb \
  --out data/ass2_dc_3day/offline_preview

# Real MQTT check against an already running isolated broker; --out must be new.
python -m scripts.check_mqtt_storage \
  --data-dir data/ass2_dc_3day --db /path/to/shared-ass1.duckdb \
  --out data/ass2_dc_3day/mqtt_09_11 --window-start 2026-09-15T09:00 \
  --hours 2 --host 127.0.0.1 --port 18884

PYTHONPATH=tests python -m unittest test_data_generator test_dashboard_dataset \
  test_entities test_generator_publisher.PublisherTests test_station_repository -v
```

46 项离线单元测试已通过。[全量验收报告](ass2_dashboard_v2_validation.json)核对了原始站点、AEMO 价格、每日覆盖、端口不重叠、每两分钟及最后读数及全部事件 ID/JSON/状态转换。
真实两小时回放包含窗口前原始价格，以及未结束会话的开始和最新 meter，先按原事件时间发布这些上下文。
完整 81,459 条事件按 0.1 秒间隔至少需要 2.3 小时；当前演示使用两小时源数据窗口，发布约需 6–7 分钟。

[真实 MQTT 验收](ass2_dashboard_v2_mqtt_validation.json)已通过：3,692 条发布 = 接收 = 入库，ID 和内容逐条一致。
其中 522 条是窗口前的必要上下文，全部保留原始时间和 ID。价格 866 条、会话开始 221 条、meter 2,440 条、结束 165 条。
在第 1,846 条后重启订阅端与数据库连接，恢复了当时 51 个活动会话；额外重复发送四类各一条，全部去重。
窗口结束时 56 个会话仍在进行，属于正常窗口边界。此次检查约 395 秒，临时 broker 已关闭，原 LAN broker 保持运行。
三天全量数据没有通过 MQTT 全部发布。离线预览库的全部 81,459 条事件另行逐条解码对账通过，所有 1,658 个头有最终状态。

OpenAI Codex assisted with the implementation, tests, verification and documentation. Retain the code acknowledgements and complete the course AI usage report.
