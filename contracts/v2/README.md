# v2 公共设计包

状态：设计样例，非已实现API、非真实运行数据、非性能结果。

- [总体设计](../../docs/13-v2-overall-design.md)、[公共契约](../../docs/15-v2-contracts.md)、[成员任务](../../docs/17-v2-member-prompts.md)。
- `workflow.schema.json`：Draft 2020-12的工作流基础形状；循环、分支、预算等跨字段语义仍按15验证。
- `journal-batch.schema.json`：C→B增量批次、严格事件联合和检查点形状；不允许C伪造run.finished。
- `examples.json`：三类定义、发布/启动、25条有序执行日志、两批提交/ACK、运行中和终态快照、分析/比较、六类实验及各方案3预热+15测量的**合成样例**。实验全部等值占位，不表示预期加速。
- `http-manifest.json`：39个方法/路径登记、状态码、必须请求头，全部implemented=false；供OpenAPI覆盖测试使用，不能代替完整OpenAPI。
- B按Schema实现共享Pydantic适配器；A/C用样例独立开发，不能修改样例来迁就实现。

从仓库根目录运行：

```powershell
python contracts/v2/build_examples.py
python contracts/v2/validate_design.py
```

构建器只重写本目录四个JSON文件；校验器需要Python环境已有`jsonschema`（本轮使用4.23.0），没有新增项目运行依赖。它检查Schema合法性、图语义、日志/Span/样本联动、拒绝非法输入和文档链接；不能代替未来的API/PG/浏览器验收。所有文件归负责人维护，修改规范须同时更新源构建器和生成文件。

2026-11-16本轮校验：2份Schema、3种工作流、2批提交、25条日志及终态快照、6类实验样例、5项非法输入拒绝、39个唯一HTTP方法/路径检查通过。14中的13张新增表DDL骨架已在PostgreSQL16专用测试库的回滚事务内实际解析/建表，并确认回滚后验证schema不存在；没有应用v2迁移。上述只是设计自洽性检查，不是v2运行验收。
