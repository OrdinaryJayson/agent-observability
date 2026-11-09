# AI Agent 执行轨迹管理与可观测性分析系统

基于 PostgreSQL 的 AI Agent 执行轨迹管理与可观测性分析系统，支持 Agent 管理、任务执行、Trace/Span 记录、执行链路可视化、运行日志查询、性能统计和数据库优化实验。

## 主要功能

- Agent 和任务管理、执行模拟与轨迹记录。
- Trace/Span 链路展示、运行日志查询与性能统计。
- 数据库事务、索引及性能优化实验。

## 技术栈与环境

前端采用 Vue 3，后端采用 FastAPI，数据库采用 PostgreSQL；开发需要相应的 Node.js、Python 和 PostgreSQL 环境。具体版本和配置参见设计文档并在实施时确认。

## 目录结构

```text
frontend/             前端
backend/app/          后端
 database/migrations/ 数据库迁移
 database/benchmarks/ 性能实验
scripts/              辅助脚本
docs/                 设计与分工文档
```

## 启动方式

项目处于初始化阶段，启动方式将在实现后补充。

## 设计文档

- [项目总体设计方案](docs/01-overall-design.md)
- [数据库设计与 API 接口规范](docs/02-database-api-spec.md)
- [工程开发规范与原型实施指南](docs/03-development-guide.md)
- [团队成员任务分工](docs/04-team-tasks.md)
- [开发与联调契约（实施依据）](docs/05-integration-contract.md)

## 团队协作

负责人负责架构、数据库及接口设计、审查与集成；成员 A 负责前端，成员 B 负责后端与数据库，成员 C 负责模拟器、数据采集和测试。开发前阅读文档并确认职责；公共契约调整须与负责人确认并同步文档，按工程指南协作。
