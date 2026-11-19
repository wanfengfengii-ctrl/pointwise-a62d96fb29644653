# 涂布线双谱段巡检采集站

班长按试片测点登记触发清册。采集员从两路记录器接管原板，质检员按触发号领取完整双谱段成果。交班时遇到待签测点，可以重开数据库继续读板，也可以用已接管的原板重投签发。

项目使用 Python 3.11 标准库和 SQLite。在项目根目录运行完整回归及演示。`check_project.py` 由运行环境提供。

```sh
python3 -B check_project.py
python3 -B -m review.reconciliation --sample samples/shift.json
```

演示使用独立临时库。样例按 A、B 登记。左路依次读 A 的 31 和 B 的 29，原序号为 11、14。右路先读 B 的 43，再读 A 的 47，原序号为 11、18。接管左 A 和右 B 后，两路都可以继续读。B 先签发，交班清单仍将待签 A 列在前面。重开后接管右 A，演示用 SQLite 写入约束阻止第一次签发，再重开并用原证据重投。最终 A 的差值为 16，B 的差值为 14。

## Python 接口

导入下列模块时不会打开数据库。`reopen_shift(path)` 初始化并打开本地库，退出上下文时关闭连接。重复初始化保留清册、录制进度、原板及成果。

| 用途 | 调用 | 返回 |
| --- | --- | --- |
| 登记 | `batch.registration.register(shift.catalog, batch_id, triggers)` | 不可变清册，`ordered_triggers` 为原顺序元组 |
| 挂接 | `source.recording.attach(shift.catalog, shift.progress, batch_id, ports)` | 双路绑定，`lane(LaneId.LEFT)` 取得左路槽端口 |
| 接管并放行 | `capture.control.step(binding, shift.evidence, lane_id)` | 单板交接、本路下一位置及耗尽标记，空槽返回 `None` |
| 恢复采集视图 | `capture.resume.resume_capture(binding, shift.evidence)` | 两路当前位置、当前板及可复用交接确认 |
| 签发 | `archive.release.publish(shift.catalog, shift.evidence, shift.results, batch_id, trigger_id)` | 完整成果及成果号，缺板返回 `None` |
| 领取 | `review.lookup.lookup(shift.catalog, shift.results, batch_id, trigger_id)` | 左右原值、差值、两路出处及成果号，待签返回 `None` |
| 清单 | `review.checklist.checklist(shift.catalog, shift.results, batch_id)` | 按登记顺序排列的 `pending` 或 `published` 条目 |
| 续办 | `review.reconciliation.reconcile_shift(shift, batch_id, binding=binding, lanes=())` | 依调用者指定线路完成有限次采集，重投本批签发并返回清单及可领成果。无现场读板时可省略绑定 |

批次号、触发号、录制号使用非空白且可按 UTF-8 编码的字符串，不含 NUL，保留原值。清册接受有序序列，触发号必须唯一。完全相同的重复登记沿用原记录，调换顺序属于异参。未知批次或登记内不存在的触发抛出 `LookupError` 的子类。挂接拒绝异批、重复或无效线路，以及尝试把已绑定批次换成另一份录制。

录制模拟器接受两份 `RecordingPort`。一份端口持有批次、录制标识、线路和固定的 `RecordedPlate` 序列。每个输入项包含槽信封的原序号及独立的 `RawPlate`，采集会核对两者。重开时提供同一固定录制，两路已经释放的位置由库恢复。`read_current()` 只能从当前槽取板。每次释放推进本路一次，过期凭据抛出 `StaleSlot`。`binding.trace` 记录本次挂接实际读板和放行的顺序。

```python
from batch.identity import LaneId, TriggerKey
from batch.registration import register
from source.plate import PlateOrigin, RawPlate
from source.recording import RecordingPort, attach
from source.slot import RecordedPlate
from capture.control import step
from review.reconciliation import reopen_shift, reconcile_shift

batch = "coating-day"
key = TriggerKey(batch, "A")
left = RecordedPlate(11, RawPlate(key, PlateOrigin(batch, LaneId.LEFT, 11), 31))
right = RecordedPlate(18, RawPlate(key, PlateOrigin(batch, LaneId.RIGHT, 18), 47))
ports = (
    RecordingPort(batch, "scan-1", LaneId.LEFT, (left,)),
    RecordingPort(batch, "scan-1", LaneId.RIGHT, (right,)),
)
with reopen_shift("coating.sqlite3") as shift:
    register(shift.catalog, batch, ("A",))
    binding = attach(shift.catalog, shift.progress, batch, ports)
    step(binding, shift.evidence, LaneId.LEFT)
    step(binding, shift.evidence, LaneId.RIGHT)
    review = reconcile_shift(shift, batch)
    print(review.results[0].difference)
```

原读数和线路原序号为严格整数，空值、布尔值和浮点读数会被拒绝。两路可使用同一原序号。差值按右减左计算，单位为设备原始计数，保留负数、零及超出 SQLite 有符号整数范围的值。证据接纳按批次、线路、原序号保留来源，并约束同批同触发每路只有一块原板。相同重试可以续办，原身份或内容冲突会被拒绝。

接管和签发各有独立事务。非法原板抛出 `InvalidPlate`，本路槽位不推进。SQLite 失败向调用者报告原错误。若接管已提交而槽位推进失败，重试可用同一块板继续。即使双板已齐备，正式提交前领取仍为待签。重投已签触发沿用原成果。交班条目从原清册生成，B 先签时 A 仍排在 B 之前。
