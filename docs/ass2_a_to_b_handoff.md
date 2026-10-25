# Assignment 2 A 到 B 交接说明

更新日期：2026-10-25。交接分支：`dengjie`。

A 的站点读取、实体类、数据生成和 MQTT 发布代码已完成，全量数据与事件流已通过离线检查。本机 Mosquitto 已配置，4,191 条样本消息已通过真实 broker 收发验证。B 接下来实现订阅、解码、去重和入库，A 配合启动发布端；B 正式入库联调与全量实际发布仍待完成。

## 接手文件

| 文件 | 用途 |
|---|---|
| [`data_generator_config.py`](../data_generator/data_generator_config.py) | 日期、随机种子、采样间隔和模拟参数 |
| [`data_generator_utils.py`](../data_generator/data_generator_utils.py) | 站点转换、AEMO 价格读取、CSV 生成、排序并构造事件 |
| [`data_generator_daemon.py`](../data_generator/data_generator_daemon.py) | 生成和发布的命令行入口 |
| [`ev_charger.py`](../repository/entity/ev_charger.py) | Ass1 站点实体 |
| [`ev_charger_state_event.py`](../repository/event/ev_charger_state_event.py) | 四种事件的统一结构与 JSON 编解码 |
| [`ev_charger_state.py`](../repository/entity/ev_charger_state.py) | 单站点、单次运行的当前状态；不保存完整历史 |
| [`duckdb_repo.py`](../repository/duckdb_repo.py) 和 [`evc_dao.py`](../repository/evc_dao.py) | 共用数据库连接及站点读取 |

`EVChargerDAO` 已提供 `list_chargers()`、`get_charger(charger_id)`、`count_chargers()`。生成端按 Ass1 的 `charger_id` 排序读取，不重新编号；不依赖 `repository/utils`。

B 负责扩展事件表、写入接口和查询接口，`repository/evc_state_dao.py` 仍是待实现的占位文件。现有 `DuckDBRepository` 默认只读；B 写入已有数据库时需要显式使用 `read_only=False`，并自行实现建表和写入逻辑。生成端读取完成后会关闭 Ass1 数据库，`--replay` 发布不访问 Ass1 数据库。

## 先跑通小样本

仓库已附上 [`examples/ass2_mqtt`](../examples/ass2_mqtt) 的两站点数据和 `manifest.json`。回放这些文件不需要下载 AEMO 数据，也不需要生成端持有 Ass1 数据库。请保留样本的 CSV 和 `run_id`，方便双方使用同一批数据对账。

所有命令在仓库根目录执行。已验证环境为 Python 3.12、DuckDB 1.5.5；发布端使用 Paho MQTT 2.1.0。本机 broker 的启动、检查和停止方式见 [MQTT 说明](../mqtt/README.md)。以下联调约定 A、B 都在同一台电脑直接运行 Python，使用 `127.0.0.1:1883`。

```bash
# Install the generation and publishing dependencies in a virtual environment.
python3 -m venv .venv-mqtt
.venv-mqtt/bin/python -m pip install duckdb==1.5.5 paho-mqtt==2.1.0

# Run the existing automated tests without a broker.
.venv-mqtt/bin/python -m unittest discover -s tests -v
```

联调顺序：

1. 打开 Docker Desktop，执行 `docker compose -f compose.mqtt.yaml up -d`。B 连接 `127.0.0.1:1883`，先启动订阅端并等待 `evc/#`、QoS 1 的订阅确认。
2. B 对照样本中的 `stations.csv` 确认站点对应关系：ID `1` 是 AC，ID `2` 是 DC；同时核对坐标。不同 Ass1 数据库重新分配过 ID 时，必须先统一映射，不能只看数字相同。
3. A 运行下面的发布命令。本配置只开放本机连接；日后换到不同电脑时，需要另行调整 broker 的监听和连接地址。

```bash
.venv-mqtt/bin/python -m data_generator.data_generator_daemon \
  --out examples/ass2_mqtt --replay --publish \
  --host 127.0.0.1 --port 1883
```

当前命令行支持普通 MQTT 的 host 和 port，未配置用户名、密码或 TLS 参数。消息使用 QoS 1、`retain=False`，所以 B 要先完成订阅再开始发布。发布端逐条等待 broker 确认，并在下一条发布前至少间隔 0.1 秒。broker 确认接收不代表 B 已经成功入库，最终以 B 的数据库对账为准。

## 消息接口

Topic 为 `evc/<event_type>/<station_id>`，例如 `evc/meter/2`。消息是 UTF-8 JSON，四种完整示例见 [`mqtt_check.json`](../examples/ass2_mqtt/mqtt_check.json)。

| 公共字段 | 含义 |
|---|---|
| `schema_version` | 当前固定为整数 `1` |
| `run_id` | 一次数据生成的标识；重新生成会改变，回放原文件不会改变 |
| `event_id` | 事件唯一标识；同一批文件重复回放保持一致，供 B 去重 |
| `type` | `price_update`、`session_start`、`meter`、`session_end` |
| `ts` | 带时区的 ISO 时间；发出的事件统一为 UTC |
| `station_id` | 字符串，来自 Ass1 的 `charger_id` |
| `connector_id` | 站点内从 1 开始的模拟端口号；不是 Ass1 `charger_connector` 表的主键 |
| `session_id` | 会话标识；跨运行保存会话时使用 `(run_id, session_id)` 区分 |
| `payload` | 事件属性，见下表 |

价格事件的 `connector_id`、`session_id` 为 `null`；其余三种事件必须携带这两个字段。

| 事件 | payload 必填字段 | 可选字段 |
|---|---|---|
| `price_update` | `price_per_kwh` | `wholesale_per_kwh` |
| `session_start` | `price_per_kwh` | `vehicle_model` |
| `meter` | `power_kw`, `energy_kwh` | `voltage_v`, `current_a`, `soc_pct` |
| `session_end` | `charge_end_ts`, `charge_minutes`, `energy_kwh`, `price_per_kwh`, `cost_aud` | `avg_kw`, `peak_kw` |

价格单位为 AUD/kWh，功率为 kW，电量为 kWh，时长为分钟，费用为 AUD，SoC 为 0–100 的百分数。`wholesale_per_kwh` 允许为负值。

以下语义会影响 B 的统计和后续 dashboard：

- 电表的 `energy_kwh` 是本次会话的累计电量，不能把所有电表记录直接相加作为总电量。
- `session_end.ts` 表示拔枪时间，`payload.charge_end_ts` 表示停止充电时间；两者之间可能有占位闲置时间。
- `session_start` 的价格是本次会话的计费价格，不能用结束时的站点价格替换。
- 发布端发送每个站点的首条价格及后续实际零售价格变化；只有批发价格变化时不会发布新的 `price_update`。
- 源数据使用固定 AEST（UTC+10），事件转换为 UTC。不要把源时间按悉尼夏令时重新解释。

## B 的接收与状态处理

使用共用类解码，避免再次维护另一套字段格式：

```python
from repository.event.ev_charger_state_event import EVChargerStateEvent
from repository.entity.ev_charger_state import EVChargerState

event = EVChargerStateEvent.from_json(message.payload)
```

`message` 是 Paho 回调中的消息对象。B 应先校验并按 `event_id` 去重、持久化，仅对新插入的事件更新当前状态。以 `(run_id, station_id)` 管理状态对象，并调用 `state.apply(event)`。重复事件不要再次调用 `apply()`，否则重复的会话开始或结束会报状态错误。

事件按时间升序发布；同一时间的处理顺序为价格、电表、会话结束、会话开始，使最后电表读数和端口交接顺序正确。保存接收顺序，重建状态时也要保留这个顺序。`EVChargerState` 只保存当前价格、活动会话和最近电表读数；历史曲线、历史统计仍需 B 保存原始事件并查询数据库。

发布错误会停止本次运行，没有自动断点续传。再次使用 `--replay` 会从头发送相同事件 ID，B 必须能够跳过已经存储的事件。B 重启后需要从已存事件重建内存状态，不能把后续电表消息直接应用到空状态。

## 联调验收

样本的 `run_id` 为 `c05c73c603d643ee9806faeef2224021`。B 按这个运行标识、去重后的事件统计：

| 事件 | 应有数量 |
|---|---:|
| `price_update` | 386 |
| `session_start` | 278 |
| `meter` | 3,249 |
| `session_end` | 278 |
| 总计 | 4,191 |

一次完整回放的发送间隔下限约为 7 分钟，实际还包括处理和网络时间。完成时确认：

- 四种事件都能解码、写入，并正确关联到 Ass1 站点。
- 去重后的数量与上表一致；两个站点最终均无活动会话。
- 重放同一批文件不会增加独立事件数量，也不会重复计算电量或费用。
- 记录发布端完成输出，以及 B 侧按 `run_id` 查询的数量、站点关联结果，交给报告负责人。

截至交接时，26 项现有自动测试通过；另使用 Mosquitto 2.1.2 完成了真实 broker 收发检查：发布和接收均为 4,191 条，重复 0 条，四类数量、主题和 JSON 内容全部匹配，最终无活动会话，耗时 447.3 秒。记录见 [真实 MQTT 验证结果](ass2_mqtt_validation.json)，复现命令为 `.venv-mqtt/bin/python -m scripts.check_mqtt`。

这个脚本使用独立验证接收器，不写 B 的数据库；上面的 B 端入库、站点关联和重放去重验收仍需双方完成。不要在运行验证脚本时同时启动第二个发布端。

## 全量数据与正式发布

已完成离线检查的数据覆盖 Ass1 的全部 1,958 个站点，使用 NSW1 的真实 AEMO 价格，生成日期为 2026-09-15 至 2026-09-28，共 14 天。随机种子为 `5339`，电表采样间隔为 5 分钟；最后一次读数始终保留，期间开始但跨出期间结束的会话也保留完整尾部事件。

| 数据或事件 | 数量 |
|---|---:|
| 站点 | 1,958 |
| 小时价格记录 | 657,888 |
| 充电会话 | 214,860 |
| 电表记录 | 5,639,747 |
| 去除不变价格后的待发布事件总数 | 6,447,361 |

站点包含 1,427 个 AC、433 个 DC 和 98 个 Upcoming。Upcoming 按假设 AC 站点模拟；缺失功率、端口数量以及站点类型默认值记录在 `stations.csv` 的 `assumptions` 中，模型假设见根目录 README。

全量检查涵盖站点 ID 集合、每站两周价格覆盖、会话和电表关联、端口会话无重叠、电量单调累计、末次电表与会话结束匹配，以及全部事件的时间顺序和状态转换。检查摘要见 [`ass2_full_validation.json`](ass2_full_validation.json)，其 `mqtt_integration_tested` 和 `mqtt_publication_completed` 均为 `false`。

全量 CSV 约 532 MiB，保存在 A 的本地 `data/ass2_generated/`，没有纳入 Git。B 接收 MQTT 流即可完成入库；如需重新生成，可指定双方一致的 Ass1 数据库快照：

```bash
# Replace the path with the shared Ass1 database; omit --limit for all stations.
python3 -m data_generator.data_generator_daemon \
  --db /path/to/shared-ass1.duckdb --out data/ass2_generated \
  --start 2026-09-15 --days 14 --seed 5339 --meter-every 5

# After generation, start B's subscriber before publishing the full dataset.
python3 -m data_generator.data_generator_daemon \
  --out data/ass2_generated --replay --publish \
  --host BROKER_IP --port 1883
```

重新生成会得到新的 `run_id`，应使用新的 `manifest.json` 对账。全量数据按每条至少间隔 0.1 秒计算，单是发送间隔就约需 179 小时，即 7.46 天；团队需要安排运行时间。小样本验收只证明联调通路，不能代替全量实际发布与收齐验证。

本次交接包含全量排序修复：CSV 先写入临时 DuckDB 表再排序，避免直接读取多个 CSV 并排序时发生内存不足。暂存文件在正常结束或生成器关闭时清理。
