# v2 数据库实验、数据集与评测协议

状态：实验设计，本文没有实测结果。B负责白名单SQL、隔离执行和数据库证据；C负责数据分布、HTTP负载、正确性对账、统计与报告；A负责实验工作台。三人共享本协议，不能各自改测量口径。

## 1. 标准数据集与隔离

| 数据集 | 规模与结构 | 用途 / 必须验证 |
|---|---|---|
| DEMO_V2 | 8个有语义的Agent、3类模板、至少6个Task、至少60个Run，其中同一版本至少30个可比较终态，含成功、失败、恢复、取消、并行与分支 | 页面非空、同Task多Run、对比和回放；通过业务API生成 |
| BENCH_100K | 100000 Span，200个500 Span Run，90天UTC跨度 | 快速回归与实验趋势 |
| BENCH_1M | 1000000 Span，2000个500 Span Run，90天UTC跨度 | 规模效应、深分页、JSONB与聚合 |
| LOAD_V2 | 固定20节点工作流，1/4/8/16个HTTP并发客户端，各300次已接受运行 | 端到端队列、SSE、资源与正确性；有界并发 |

独立实验数据库使用`*_lab`或`*_test`，与开发数据库物理库名不同；环境显式配置EXPERIMENT_DATABASE_URL，API只返回无凭据的别名。B在专用库创建`lab_{dataset_id去连字符}`schema，名称由服务端UUID生成并经SQLAlchemy Identifier引用，客户端不能上传标识符或SQL。实验角色不得拥有业务public的DDL权限。

BENCH数据为结构合法的离线克隆：每Run单根、Agent引用和父子关系合法、非LLM Token为空、事件关联存在。临时实验表是否省略外键必须记录，并明确不能代替业务写入完整性测试。默认构造带完整约束的基准表，索引实验仅切换所研究索引，固定其余约束/基础索引。不要把删除所有约束后的加载速度当作真实服务吞吐。

分布manifest冻结：seed=42，Agent/工具均匀与热点80%集中于20%实体两档；失败率1%/10%/50%；属性过滤目标选择率0.1%/1%/10%/50%；每条记录attributes包含tool_category、region、payload_size。实际选择率与计数由SQL验证，目标值不直接当实际值。JSONB负载大小固定三档128B/1KiB/4KiB，测量存储和写入代价。

标准矩阵采用明确子集而非无边界全笛卡尔积：必测全部六类实验；每类至少100K/1M两规模，INDEX和JSONB另测上述四选择率，倾斜/大JSON只做在1M上的敏感性分析。每份报告列出实际执行组合与未运行组合，不能以少数组合推断所有分布。

## 2. 实验请求与状态

`POST /api/v2/experiments`：

```json
{
  "dataset_id":"66666666-6666-4666-8666-666666666666",
  "case_code":"JSONB_GIN",
  "parameters":{"selectivity":0.01},
  "seed":42,
  "warmups":3,
  "repetitions":15
}
```

case_code只允许下表六种，parameters按案例判别联合检查，未知键422。warmups固定3、repetitions允许15或30；不让前端用1次测量获得“正式结果”。RUNNING期间UI展示phase=PREPARING/WARMUP/MEASURING/VERIFYING/EXPORTING，progress可null，避免虚构百分比。QUEUED→RUNNING→SUCCESS/FAILED/CANCELLED终态不可逆。

每实验排队上限300秒、运行上限900秒，单SQL30秒、锁等待3秒，LOAD单档最多180秒。SQL超时先取消并回滚当前trial，实验FAILED/EXPERIMENT_TIMEOUT并保留已完成样本；不把部分结果标SUCCESS。每专用实验库同时1个破坏布局的实验，用PostgreSQL advisory lock跨进程互斥；最多10个排队实验，超出429。暂停/进程崩溃的RUNNING实验标FAILED，不自动从中点补采样改变实验顺序；允许新建实验重跑。

B提供独立`python -m app.lab.worker --runner-id lab-1`消费实验队列。持有专用实验库的session级全局advisory lock后才可领取/恢复实验；无锁者等待，不由API启动时一律标FAILED。新执行器获得锁说明前任session已消失，此时把遗留RUNNING实验标FAILED再领取新作业。实验库布局与主库中的manifest/sample跨库不承诺分布式原子事务：先完整登记一个样本再发布trial汇总，崩溃后保留已提交样本并整体标失败。UI按500ms–2s有退避轮询实验状态，不复用Run journal协议。

## 3. 六类必须实验

| case_code | 假设、方案与控制变量 | 正确性与必须输出 |
|---|---|---|
| INDEX_SELECTIVITY | trace查询无候选索引/单run_id/组合(run_id,start_time)；错误查询无候选/全索引/ERROR部分索引；统一数据与参数 | 同一有序结果hash一致；实际行数/扫描方式/排序/索引大小/插入开销；小数据不强制加速 |
| JSONB_GIN | attributes @> 查询，对比无GIN/jsonb_ops/jsonb_path_ops；四选择率与大JSON敏感性 | 结果hash与SQL等价性；Bitmap/Seq Scan、recheck、索引大小、写入与ANALYZE时间 |
| PAGINATION | OFFSET与keyset；limit=50，rank=0/10000/100000（100K档不可达rank标N/A） | 冻结快照下相同rank返回相同ID；游标定位的预先成本单列；总时间/扫描行数/并发插入语义 |
| AGGREGATION | 原始Span多表聚合/终态run_summaries/日MV；1/7/30/90天窗口；另测完整刷新成本 | 可结合指标一致；平均值用sum/count；P95仍从逐Run数据计算；显示新鲜度、水位、刷新和存储代价 |
| MVCC_ISOLATION | 两独立事务按屏障交错，READ COMMITTED与REPEATABLE READ；写偏斜另用SERIALIZABLE检测及有限重试 | 两次查询可见性、预期异常、40001 SQLSTATE、重试计数；不以sleep碰碰运气，不把隔离级别优劣简单排名 |
| QUEUE_CONTENTION | 普通FOR UPDATE等待与SKIP LOCKED；1/2/4/8个领取者；每次短事务+提交后模拟工作；相同1000个作业 | 领取延迟/吞吐/重复完成数/等待公平性；附租约过期/旧epoch/ACK丢失/取消竞争的故障表 |

INDEX、JSONB、PAGINATION和AGGREGATION由B注册固定SQL及参数；MVCC的交错屏障由C提供场景驱动，B提供受控事务操作；QUEUE的两策略只在隔离队列表运行，不能为对比关闭实际业务幂等保护。

parameters闭集：INDEX_SELECTIVITY={query:TRACE|ERROR,selectivity:0.001|0.01|0.1|0.5}；JSONB_GIN={selectivity:同上}；PAGINATION={rank:0|10000|100000,limit:50}；AGGREGATION={window_days:1|7|30|90}；MVCC_ISOLATION={schedule:NON_REPEATABLE_READ|WRITE_SKEW}；QUEUE_CONTENTION={claimers:1|2|4|8,jobs:1000}。同一case可创建多次实验覆盖矩阵，实验内部按注册的variant自动运行，不允许前端指定SQL或任意索引名。QUEUE/MVCC沿用3预热/15轮屏障试验，机制结果以异常/不变量为主，不强行套查询耗时排名。

variant代码冻结：TRACE为no_candidate/single_run/composite_run_start，ERROR为no_candidate/full_status_time/error_partial；JSONB为no_gin/gin_ops/gin_path_ops；分页为offset/keyset；聚合为raw/summary/daily_mv；MVCC为read_committed/repeatable_read/serializable；队列为blocking/skip_locked。“no_candidate”保留基础主键/外键支持索引，不等同于没有任何索引；例如(run_id,span_id)唯一索引已可能支持run_id过滤，应把候选索引的增量收益与冗余风险一起报告。

SERIALIZABLE写偏斜案例固定为“两条值班记录至少保留一条active”：T1/T2各读两行再更新自己行；REPEATABLE READ可提交破坏约束（跨行断言未用单行CHECK假装保障），SERIALIZABLE应中止至少一方；重试需重新读并保留至少一条。记录确切SQL/屏障/事务结果，说明应用不变量与数据库隔离的关系。

KEYSET公平性：实际浏览下一页时已有cursor，比较一次分页查询；随机跳到第N页时cursor构造成本必须另计。禁止预存全部cursor却宣称支持任意页O(1)跳转。并发插入下READ COMMITTED的OFFSET偏移属于预期行为，不将keyset描述为任意修改下绝对不重漏。

## 4. 测量、统计与证据

1. 记录CPU、内存、操作系统、PostgreSQL版本、连接数、磁盘类型（无法识别写unknown）、shared_buffers/work_mem、表/索引大小、统计信息时间、代码与协议版本、seed、查询参数、隔离级别、是否并发负载。
2. 数据准备、COPY、建索引、ANALYZE、刷新MV和正式查询分别计时。每方案3次预热，15次测量；随机化成对方案执行顺序，seed保存，避免总是先无索引后有索引受缓存影响。结构切换使用两个等价克隆或重新构建，记录各自缓存条件。
3. 默认报告warm-cache；没有OS级清缓存证据时不写cold-cache。EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)含执行插桩成本，另记录无EXPLAIN的客户端端到端时间；二者分别成列。
4. 原始样本不可丢弃；报告median、P95、IQR。P95统一连续分位数type-7，即h=(n-1)p线性插值；n=15须说明尾部估计不稳定。配对比较使用median成对差值及1000次配对bootstrap 95%区间，seed保存；不预设显著性和提升比例。
5. 慢样本不随意删；超时/错误独列，不能把超时当0ms参与平均。只在明确污染原因时附“含全部样本/排除污染”两套结果与理由。
6. 每个方案验证count与按稳定主键排序的内容hash一致；写入实验另查约束、孤儿、Token重复累计、重复终态和未结束作业数。结果更快但错误则该方案失败。
7. 查询计划以完整原始JSON保存；可解析节点树用于前端，但不得只保存提取后的扫描类型。Buffers区分Shared/Local/Temp，记录实际rows/loops与估计误差。
8. 结论包括性能、空间、写放大、一致性、新鲜度和复杂度。性能更差也保留，解释优化器选择率、排序和缓存；不得用enable_seqscan=off制造正式加速证据（仅诊断附录可用并标明）。

## 5. HTTP负载、故障与算法评测

HTTP负载由C标准库工具驱动，客户端数1/4/8/16，POST带幂等键且未知响应只复用原键。记录接受延迟、排队时长、执行时长、完成吞吐、SSE传播延迟、失败/超时、数据库连接峰值、RSS采样。业务注入失败与基础设施错误分列。单机资源不足时降低并发并记录，不能隐去失败样本。

故障矩阵至少包含：提交前断连、COMMIT后ACK丢失、API重启、Worker领取后崩溃、并行步骤中崩溃、重复恢复领取、旧Worker复活、取消与完成竞争、数据库短时不可用、实验SQL超时、SSE断线后补齐。用明确故障点/进程控制/屏障，不用随机等待冒充复现。

正确性不变量：

- 同幂等键只创建一个资源；同Run至多一个终态；已完成Span不被覆盖。
- journal seq连续、event_id唯一；同batch异内容被拒；检查点水位与日志一致。
- 完整终态Span树唯一根/无环/无孤儿，依赖DAG无环，引用与角色身份正确。
- 失效epoch不能续写或完成；已确认成功节点恢复后不重跑，未确认调用保留至少一次语义说明。
- 成功/失败/取消数与SQL对账；Token只累计LLM所有真实尝试；MV允许滞后但水位可解释。

算法验证：拓扑排序O(V+E)；关键路径与合法图暴力枚举的小图oracle对比；自耗时以重叠/包含/零长/越界区间验证；同版本比较覆盖跳过分支；重试随机源不受并发调度影响；MAD覆盖n<20、MAD=0、真正离群与不同工作流不可比。测试预期不能简单复制被测实现。

## 6. 数据生成与报告命令接口

C实现以下新工具，保留v1 generate_data.py原入口：

```text
python scripts/v2/seed_demo.py --base-url URL --seed 42 --profile full
python scripts/v2/generate_dataset.py --base-url URL --profile BENCH_1M --seed 42
python scripts/v2/load_test.py --base-url URL --clients 1,4,8,16 --runs-per-level 300
python scripts/v2/fault_suite.py --base-url URL --scenario all
python scripts/v2/report_experiments.py --input exports/ --output reports/v2/
```

每个命令有--help、参数校验、有限超时、非零失败退出码、JSON摘要、可恢复资源ID；POST不换键盲重试。fault_suite仅允许专用测试服务，需显式ALLOW_FAULT_TESTS=true；进程控制限制在本次启动并登记的API/Worker PID，不杀其它项目进程。

B提供`app.lab.loader`的受控内部适配器（非公开HTTP）：`load_dataset(dataset_id, records, expected_manifest)`，仅实验库、按dataset_id建schema、受控COPY、回滚/失败manifest。C生成逻辑记录流，不直接拼B的SQL。A只能调用登记/状态/实验API，不通过浏览器上传百万JSON。

交付 `reports/v2/experiment-report.md`、`methods.md`、`results.csv`、`environment.json`、`correctness.json` 和完整导出JSON；图表由C标准绘图库生成SVG/PNG（B合并新增依赖），不使用AI生成曲线。报告保留对原样本的可追溯链接，不能只交截图。

报告至少给出：六类实验问题与假设、数据及控制变量、测量协议、结果与不确定性、失败反例、威胁与外推边界。性能图至少包括规模/选择率、深分页、聚合窗口、并发领取四组；同时给空间与写入成本表。实测前只提交模板，不填预计提升数字。
