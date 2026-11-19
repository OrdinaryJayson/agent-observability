# 12 分钟演示路线

| 时间 | 操作 | 证据入口 |
|---|---|---|
| 0–1 分钟 | 展示架构、六类实验问题和数据清单 | 13–16 文档、dataset-validation.json |
| 1–3 分钟 | 运行并行模板和 QUALITY_GATE 的两种路由，查看节点身份、归属树与依赖边 | engine-evidence.json 的 parallel、pass、fallback；集成后使用 DEMO_V2 页面 |
| 3–5 分钟 | 比较并行 600ms 与串行 900ms 的虚拟语义案例，解释理论路径 600ms；展示 seed=1 恢复成功 | engine-evidence.json 的 serial、recovered |
| 5–7 分钟 | 展示确认批次、丢 ACK 重发、WorkerLost 保留及恢复 | MemorySink 故障记录；集成后使用双 Worker 和审计 |
| 7–10 分钟 | 展示六类实验矩阵、原样本和计划，选两个实际完成的案例深入解释 | 集成后由 report_experiments.py 生成的 CSV、计划及图表 |
| 10–12 分钟 | 重现一条检查命令，说明异常阈值、数据水位、适用范围和待验收组合 | methods.md、correctness.json、C-v2.md |

当前可离线演示执行器案例和数据生成检查。真实服务演示使用已登记的工作流、Run、数据集及实验资源 ID。历史实测附件应保留执行日期和版本，现场重新执行的结果另行记录。
