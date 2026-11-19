# v2 实验执行记录

当前交付阶段为成员 C 独立模块验收。可复验的执行案例见 engine-evidence.json，离线数据生成与摘要见 dataset-validation.json，算法与统计方法见 methods.md。

| 实验 | 基准规模和参数 | 真实 PostgreSQL 执行状态 |
|---|---|---|
| INDEX_SELECTIVITY | 100K/1M，TRACE/ERROR，四档选择率 | 待 B 隔离服务集成 |
| JSONB_GIN | 100K/1M，四档选择率，1M 大 JSON 敏感性 | 待 B 隔离服务集成 |
| PAGINATION | 100K/1M，rank 0/10000/100000；不可达位置标 N/A | 待 B 隔离服务集成 |
| AGGREGATION | 100K/1M，1/7/30/90 天窗口及刷新代价 | 待 B 隔离服务集成 |
| MVCC_ISOLATION | 两事务屏障，RC/RR/SERIALIZABLE | 驱动在内存 oracle 上验证，真实 PG 待集成 |
| QUEUE_CONTENTION | 1000 作业，1/2/4/8 领取者，两种策略 | 驱动在内存 oracle 上验证，真实 PG 待集成 |

1M 热点及大 JSON 敏感性分析、真实 300 Run/档 HTTP 负载、资源峰值和全部跨进程故障组合均待集成执行。当前 results.csv 只含列定义，exports.json 为空样本清单。取得真实导出后，通过报告命令重建结果、计划附件和曲线。

故障矩阵中的提交前断连、提交后丢 ACK、短时提交不可用、在途 Worker 丢失、旧 epoch 续写及恢复保留失败尝试，已有明确 MemorySink 注入点和检查。API 重启、双恢复者数据库竞争、取消完成事务竞争、真实数据库不可用、实验 SQL 超时及真实 SSE 重连由负责人在真实服务上验收。

独立执行证据包含并行与顺序、不可恢复失败、seed=1 的恢复成功、PASS/FAIL 分支、真实等待和取消。VIRTUAL 案例用于验证语义。REALTIME 内存案例反映本机模拟器等待，数据库实验结论需结合对应的 PostgreSQL 原样本、环境和正确性结果评估。
