# v2 算法与评测方法

执行入口为 `app.execution_v2`，分析入口为 `app.analysis_v2`。本目录的执行证据来自独立内存适配器，数据库实验结果表在获取真实导出后填充。

## 算法与口径

| 算法 | 方法和复杂度 | 检查与边界 |
|---|---|---|
| 拓扑排序 | Kahn 队列，O(V+E) | 引用、唯一 START/END、可达性、普通节点单入边 |
| 条件汇合 | 逆拓扑后支配集合及最近公共后支配 MERGE，保守上界 O(V(V+E)) | 分支交叉反例、结构化嵌套最多四层；节点上限 50 |
| 并发调度 | 稳定 node_key 就绪顺序，最多四个在途步骤，操作和退避共用离散计时队列 | 未选分支 SKIPPED，无虚构 Span；失败后闭合已运行的独立分支 |
| 随机结果 | SHA256(seed,node_key,attempt_no) 派生节点随机源 | 并行度变化保持各尝试结果可复现 |
| 理论关键路径 | 选中 DAG 拓扑动态规划，O(V+E) | 小图枚举全部路径的独立 oracle；权重为操作尝试耗时及退避 |
| 自耗时 | 直接子区间裁剪、排序及并集，总体 O(S log S) | 重叠、包含、零长、越界、缺失区间；缺失返回 unavailable |
| 跨 Run 对齐 | 相同版本及模式，按 node_key 对齐全部尝试 | 2–5 Run；SKIPPED 耗时为 null，零分母相对变化为 null |
| 稳健阈值 | 至少 20 个可比较样本，median/MAD；MAD 为零使用显式绝对阈值 | 同版本、同节点及模式的基线筛选由调用适配器负责 |

REALTIME 使用真实异步等待、UTC 时间和高分辨率单调计时器。VIRTUAL 使用注入模拟时钟，恢复时延续原时间原点。容量等待从 ready_at 到开始计算，重试退避单列。根与角色容器从关键路径权重中排除。恢复停顿使用 journal 可观测提交间隔并集估计。

退避期间独立分支可继续完成。失败尝试的闭合和下一尝试的开始在同一批提交，退避中检查点保留未确认尝试为 RUNNING。Worker 丢失后该尝试闭合为 WorkerLost，随后生成新 attempt_no。确认提交的成功节点保留，未知提交结果重发相同 batch/event ID。

## 数据生成与摘要

BENCH 记录流采用每 Run 一个 bundle，键为 ordinal、agents、tasks、runs、spans、span_events、span_links。Span/Event 复用原五表的单 Run 数据字段，run_id 由 bundle 中的 Run 提供。B 的 Loader 负责该流到隔离表的映射。

100K 为 200 个 Run，1M 为 2000 个 Run，每 Run 500 Span，覆盖 90 个 UTC 日期。分布参数支持均匀和 80% 集中于 20% 实体、三档操作失败概率、四档目标选择率和三档 JSONB 大小。报告保存实际分布，操作失败概率与所有 Span 的实际错误比例分别核对。

内容摘要包括生成器版本、seed、配置及规范化逻辑记录。摘要排除随机资源 UUID 和墙钟时间，保留逻辑节点次序、身份序号、属性、结果和关系。隔离加载先计算预期摘要，再由 Loader 消费相同流，并在 finalize 时由服务端核对。离线检查输出 persisted=false。

## 数据库实验统计

每方案保留三次预热和 15 或 30 次正式测量。顺序由服务端按 seed 随机化配对，B 保存全部原始样本、计划和环境。C 读取导出并计算 median、type-7 P95、IQR、配对差值中位数和 1000 次配对 bootstrap 的 95% 区间，seed 为 42。差值方向为当前方案减该实验首个 ordinal 参考方案。

错误、超时及正确性失败保留在原始数据中，相关失败单列。15 个样本的尾部分位数估计不稳定。客户端耗时与 EXPLAIN 插桩执行耗时分别记录。默认缓存条件为 warm-cache，空间、插入成本、刷新代价及数据新鲜度随结果报告。

`report_experiments.py` 从完整实验导出重建 CSV、Markdown、JSON 和 Matplotlib SVG/PNG。含 synthetic 标记的协议样例会被拒绝作为性能证据。报告绘图使用 Matplotlib 3.10.7，本地协议交叉校验使用 jsonschema 4.23.0，工具依赖的集中锁定由 B 负责。

## 重现入口

```powershell
backend/.venv/Scripts/python.exe -m pytest -q backend/tests/engine_v2
backend/.venv/Scripts/python.exe scripts/v2/evaluate_engine.py --output reports/v2
backend/.venv/Scripts/python.exe scripts/v2/generate_dataset.py --offline --profile BENCH_100K --seed 42
backend/.venv/Scripts/python.exe scripts/v2/generate_dataset.py --offline --profile BENCH_1M --seed 42
$env:ALLOW_FAULT_TESTS='true'
backend/.venv/Scripts/python.exe scripts/v2/fault_suite.py --memory --scenario all
```

真实集成时使用已启用的专用服务运行 16 号文档中的五条工具命令。进程故障工具接受运维驱动模块的 `run_scenario(name, client, processes)`，只通过本次 ManagedProcesses 启动的进程句柄执行停止。资源采样模块提供有界 `sample_resources()`，返回 database_connections、api_rss_bytes、worker_rss_bytes。事务驱动采用 `_mechanisms.py` 中的屏障日程，SQL 和数据库权限由 B 的适配器提供。
