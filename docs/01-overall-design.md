# 面向 AI Agent 的执行轨迹管理与可观测性分析系统

> 实施说明：本文件保留原设计和历史示例；开发范围、接口、模块归属及冲突处理以 [开发与联调契约 V1.0](05-integration-contract.md) 为准。
## 项目设计方案 V1.0

**项目英文名称：** AI Agent Trace Management & Observability System

**项目类型：** 数据库应用系统设计与实现

**开发周期：** 2～3 周

**团队规模：** 4 人

---

## 1. 项目概述

### 1.1 项目背景

随着大语言模型和 AI Agent 技术的发展，智能体逐渐具备任务规划、工具调用、自主执行以及多智能体协作能力。

在 Agent 执行任务的过程中，会产生大量运行数据，包括任务信息、模型调用记录、工具调用记录、执行步骤、任务状态、Token 消耗、执行时间和异常信息等。

当 Agent 执行任务的数量增加时，如何对这些数据进行统一管理、快速检索、关联分析和性能统计，成为 AI Agent 系统工程化过程中需要解决的问题。

传统日志文件难以方便地支持复杂的关联查询、条件筛选和统计分析。因此，本项目计划设计并实现一个基于关系数据库的 AI Agent 执行轨迹管理与可观测性分析系统。

系统借鉴 OpenTelemetry 的 Trace/Span 数据组织方式，将一次 Agent 任务执行表示为一条 Trace，将执行过程中的各个操作表示为 Span，并通过父子关系还原任务执行链路。

### 1.2 项目目标

本项目主要实现以下目标：

1. 建立统一的 Agent 运行数据管理机制，实现不同 Agent 运行数据的结构化存储。
2. 实现 Agent 执行轨迹管理，支持查看一次任务执行过程中的完整调用链。
3. 实现 Agent 运行状态监控，支持查看执行次数、成功率、失败率等指标。
4. 实现 Agent 性能分析，支持分析执行耗时、Token 消耗和工具调用情况。
5. 实现运行日志检索，支持按 Agent、任务、时间、状态和错误类型进行查询。
6. 结合数据库课程知识，开展事务管理、索引设计、查询优化和并发测试。
7. 为真实大模型调用和后续数据库内核技术扩展预留接口。

### 1.3 项目边界

| 项目内容 | 实现要求 |
|---|---|
| Agent 注册与管理 | 必须 |
| 模拟 Agent 执行 | 必须 |
| 执行轨迹采集与存储 | 必须 |
| 执行链路可视化 | 必须 |
| 运行状态与性能分析 | 必须 |
| 日志查询与筛选 | 必须 |
| 数据库索引与查询优化实验 | 必须 |
| 少量真实大模型任务 | 尽量实现 |
| 自动异常分析 | 选做 |
| OpenTelemetry OTLP 接入 | 扩展 |
| HuaDB 内核实验 | 加分项 |

本项目不负责实现完整的 Agent 调度框架，不开发复杂的多智能体自主规划算法，也不要求自行实现数据库引擎。

---

## 2. 用户需求分析

### 2.1 系统使用者

主要面向 AI Agent 系统开发者和运行分析人员。

系统提供两类基本使用场景：

- 管理人员：查看 Agent、任务和执行实例，了解系统运行情况。
- 分析人员：查询执行轨迹，分析性能指标，定位异常并比较不同运行策略。

第一版不需要实现复杂的用户权限系统，可以使用简单的演示账号或直接进入管理界面。

### 2.2 核心需求

| 需求编号 | 需求名称 | 需求说明 |
|---|---|---|
| R01 | Agent 管理 | 查看和管理系统中的 Agent |
| R02 | 任务管理 | 创建、查看和管理 Agent 执行任务 |
| R03 | 数据生成 | 模拟 Agent 执行过程并产生运行数据 |
| R04 | 数据采集 | 接收并保存 Agent 执行轨迹 |
| R05 | 轨迹查询 | 根据任务和 Trace ID 查询执行记录 |
| R06 | 链路展示 | 展示父子 Span 关系及执行时间线 |
| R07 | 性能监控 | 统计执行时间、Token 和调用次数 |
| R08 | 异常分析 | 统计失败任务、错误类型及异常步骤 |
| R09 | 数据库优化 | 展示索引优化和查询性能对比 |
| R10 | 真实任务接入 | 支持少量真实模型调用并采集其执行数据 |

---

## 3. 系统功能模块设计

系统划分为六个主要业务模块和一个可选扩展模块。

### 3.1 Agent 管理模块

负责管理系统中参与任务执行的 Agent。

主要功能：

- Agent 注册。
- Agent 基本信息管理。
- Agent 角色管理。
- Agent 运行状态管理。
- Agent 模型信息管理。
- Agent 历史执行记录查询。

Agent 属性包括：

- Agent ID
- Agent 名称
- Agent 角色
- 模型提供商
- 模型名称
- 创建时间
- 当前状态

### 3.2 任务与执行管理模块

负责管理 Agent 执行的任务及每一次任务运行实例。

主要功能：

- 创建任务。
- 查看任务列表。
- 启动模拟任务。
- 启动真实任务。
- 查看任务执行状态。
- 查看历史执行实例。
- 查看执行开始时间和结束时间。

需要区分 Task 和 Run：

- Task 表示一个待执行的任务定义。
- Run 表示该任务的一次实际执行。

同一个 Task 可以产生多个 Run，以便比较不同执行策略下的性能表现。

### 3.3 执行轨迹管理模块

这是系统的核心模块。

负责记录 Agent 执行过程中产生的调用链信息。

一次任务执行对应一条 Trace，一条 Trace 包含多个 Span。

例如：

```text
Trace: research_task_001
|
|-- Span 1: 主 Agent 启动
|   |
|   |-- Span 2: 调用 LLM
|   |
|   |-- Span 3: 调用搜索工具
|   |
|   |-- Span 4: 调用分析 Agent
|       |
|       |-- Span 5: 分析 Agent 调用 LLM
|       |
|       |-- Span 6: 分析 Agent 返回结果
|
|-- Span 7: 主 Agent 整理结果
|
|-- Span 8: 返回最终结果
```

主要功能：

- Trace 创建与管理。
- Span 数据采集。
- Span 父子关系管理。
- Span 执行状态记录。
- 执行耗时计算。
- Agent 调用关系展示。
- Trace 历史查询。

Span 需要记录：

- Trace ID
- Span ID
- Parent Span ID
- Agent ID
- 操作类型
- 操作名称
- 开始时间
- 结束时间
- 执行耗时
- 执行状态
- Token 消耗
- 扩展属性

### 3.4 运行日志与异常管理模块

负责管理 Agent 执行过程中的事件及异常。

主要功能：

- 执行事件记录。
- 错误日志记录。
- 按错误等级筛选。
- 按错误类型筛选。
- 按时间范围查询。
- 根据 Trace ID 查询关联事件。
- 查看异常发生位置及上下文。

典型事件：

- Agent 启动。
- Agent 任务完成。
- 工具调用开始。
- 工具调用成功。
- 工具调用失败。
- Agent 之间的任务交接。
- 模型调用超时。
- 任务执行失败。

### 3.5 性能监控与数据分析模块

负责从数据库中提取运行指标并进行统计分析。

主要指标：

| 指标 | 说明 |
|---|---|
| 总任务数 | 系统执行的任务总量 |
| 成功任务数 | 成功完成的任务数量 |
| 失败任务数 | 执行失败的任务数量 |
| 成功率 | 成功任务数 / 总任务数 |
| 平均执行时间 | 所有任务的平均耗时 |
| P50 / P95 耗时 | 任务执行时间分位数 |
| Token 消耗 | 输入和输出 Token 数量 |
| 工具调用次数 | 各类工具的调用数量 |
| Agent 调用次数 | 各 Agent 的执行次数 |
| 异常数量 | 执行过程中产生的异常数量 |

主要展示内容：

- 任务执行数量变化趋势。
- Agent 成功率对比。
- Agent 平均执行时间对比。
- 模型 Token 消耗对比。
- 工具调用频率统计。
- 异常类型分布。

### 3.6 数据库性能分析模块

该模块是课程项目的重要特色，用于展示数据库技术实践成果。

主要功能：

1. 展示当前数据库数据规模。
2. 展示主要数据表及索引结构。
3. 展示典型 SQL 查询。
4. 对比建立索引前后的查询性能。
5. 展示查询执行计划。
6. 展示不同查询条件下的性能变化。

重点实验：

- 无索引与有索引的查询性能比较。
- 普通索引与组合索引比较。
- 普通索引与部分索引比较。
- JSONB 查询与 GIN 索引比较。
- 不同数据规模下的查询性能变化。

### 3.7 可选扩展：智能异常分析

在基础功能完成后，可以增加一个轻量级智能分析功能。

例如：

- 识别某个 Agent 执行时间异常增长。
- 发现某个工具调用失败率较高。
- 分析 Token 消耗异常的任务。
- 根据历史运行数据生成异常摘要。

第一版可以采用阈值规则和统计方法实现，不需要专门训练模型。

---

## 4. 系统总体架构设计

### 4.1 架构设计

采用前后端分离架构。

整体划分为五个层次：

1. 数据产生层
2. 数据采集层
3. 后端业务服务层
4. 数据存储层
5. 前端展示层

架构示意：

```text
                 数据产生层
        +-----------------------+
        |                       |
   模拟 Agent             真实 Agent
        |                       |
        +-----------+-----------+
                    |
                    v
                 数据采集层
        +-----------------------+
        | Trace / Span Recorder |
        | 数据格式标准化         |
        | 批量数据提交           |
        +-----------+-----------+
                    |
                    v
                后端服务层
        +-----------------------+
        | Agent 管理服务        |
        | 任务与执行管理服务    |
        | Trace 查询服务        |
        | 日志管理服务          |
        | 性能分析服务          |
        | 数据库实验服务        |
        +-----------+-----------+
                    |
                    v
                 数据存储层
        +-----------------------+
        |       PostgreSQL      |
        |                       |
        | Agent / Task / Run    |
        | Span / Span Event     |
        | Index / JSONB         |
        +-----------+-----------+
                    |
                    v
                 前端展示层
        +-----------------------+
        | 运行监控大屏           |
        | 执行轨迹详情           |
        | 日志检索               |
        | 性能分析               |
        | 数据库优化实验         |
        +-----------------------+
```

### 4.2 数据流设计

以一次模拟 Agent 执行为例：

1. 用户在前端选择任务并启动模拟执行。
2. 后端创建 Run，并生成唯一 Trace ID。
3. 模拟 Agent 执行不同操作。
4. Trace Recorder 为每个操作生成 Span。
5. Span 数据经过统一格式处理。
6. 后端通过批量写入接口保存数据。
7. PostgreSQL 持久化任务、Span 和事件。
8. 前端通过查询接口获取运行记录。
9. 系统构建 Span 父子关系并展示执行时间线。
10. 性能分析模块通过 SQL 聚合得到统计结果。

### 4.3 架构设计原则

- 模拟 Agent 与真实 Agent 使用统一的数据格式。
- 数据采集与数据展示相互独立。
- 业务数据与执行轨迹数据分离管理。
- 数据库查询通过统一后端接口完成。
- 性能统计尽可能通过 SQL 聚合实现。
- 不引入不必要的分布式中间件。

---

## 5. 数据库设计

### 5.1 数据库选型

采用 PostgreSQL 作为主要数据库。

选择原因：

1. 支持标准关系数据库功能。
2. 支持 JSONB，可存储不同 Agent 的扩展属性。
3. 支持 GIN 索引，适合 JSONB 属性检索。
4. 支持组合索引和部分索引。
5. 支持事务和并发访问。
6. 适合执行复杂统计 SQL。

### 5.2 核心数据表设计

第一版采用五张核心表。

#### 表 1：agents

存储 Agent 基本信息。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 主键 |
| name | VARCHAR(100) | Agent 名称 |
| role | VARCHAR(100) | Agent 角色 |
| model_provider | VARCHAR(100) | 模型提供商 |
| model_name | VARCHAR(100) | 模型名称 |
| status | VARCHAR(20) | Agent 状态 |
| created_at | TIMESTAMPTZ | 创建时间 |

#### 表 2：tasks

存储任务定义。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 主键 |
| title | VARCHAR(255) | 任务名称 |
| description | TEXT | 任务描述 |
| scenario_type | VARCHAR(50) | 任务类型 |
| created_at | TIMESTAMPTZ | 创建时间 |

#### 表 3：runs

存储任务执行实例。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 主键 |
| task_id | UUID | 关联任务 |
| trace_id | CHAR(32) | Trace 唯一标识 |
| source_type | VARCHAR(20) | SIMULATED / REAL |
| status | VARCHAR(20) | RUNNING / SUCCESS / FAILED |
| started_at | TIMESTAMPTZ | 开始时间 |
| ended_at | TIMESTAMPTZ | 结束时间 |
| duration_ms | BIGINT | 执行耗时 |
| total_input_tokens | BIGINT | 输入 Token |
| total_output_tokens | BIGINT | 输出 Token |
| error_count | INT | 异常数量 |

其中，trace_id 应建立唯一约束。

#### 表 4：spans

存储执行链路中的具体操作。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | BIGSERIAL | 主键 |
| run_id | UUID | 所属 Run |
| trace_id | CHAR(32) | 所属 Trace |
| span_id | CHAR(16) | Span 标识 |
| parent_span_id | CHAR(16) | 父 Span 标识 |
| agent_id | UUID | 执行 Agent |
| operation_name | VARCHAR(100) | 操作类型 |
| span_name | VARCHAR(255) | 操作名称 |
| status | VARCHAR(20) | 执行状态 |
| tool_name | VARCHAR(100) | 工具名称 |
| model_name | VARCHAR(100) | 模型名称 |
| start_time | TIMESTAMPTZ | 开始时间 |
| end_time | TIMESTAMPTZ | 结束时间 |
| duration_ms | BIGINT | 执行耗时 |
| input_tokens | INT | 输入 Token |
| output_tokens | INT | 输出 Token |
| error_type | VARCHAR(100) | 错误类型 |
| attributes | JSONB | 扩展属性 |

关键设计：

- trace_id 用于将属于同一任务的 Span 关联起来。
- span_id 用于唯一标识一个操作。
- parent_span_id 用于还原调用关系。
- attributes 用于保存不同类型操作的扩展数据。

operation_name 可以使用 invoke_agent、execute_tool、chat、retrieve 等标准化名称。

#### 表 5：span_events

存储执行过程中的事件。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | BIGSERIAL | 主键 |
| trace_id | CHAR(32) | 所属 Trace |
| span_id | CHAR(16) | 所属 Span |
| event_name | VARCHAR(100) | 事件名称 |
| level | VARCHAR(20) | 日志等级 |
| occurred_at | TIMESTAMPTZ | 事件时间 |
| attributes | JSONB | 事件扩展属性 |

例如：

- agent.started
- agent.completed
- tool.started
- tool.failed
- agent.handoff
- model.timeout

不需要额外建立复杂的日志系统，第一版使用 span_events 统一管理事件。

### 5.3 数据表关系

```text
agents
  |
  | 1:N
  v
spans

tasks
  |
  | 1:N
  v
runs
  |
  | 1:N
  v
spans
  |
  | 1:N
  v
span_events
```

补充说明：

- 一个 Task 可以有多个 Run。
- 一个 Run 对应一条 Trace。
- 一条 Trace 包含多个 Span。
- 一个 Span 可以有多个事件。
- 一个 Agent 可以参与多个 Span。

### 5.4 数据完整性约束

建议建立以下约束：

1. Agent ID、Task ID、Run ID 使用主键约束。
2. Run 的 task_id 使用外键关联 tasks。
3. Run 的 trace_id 设置唯一约束。
4. Span 的 `(trace_id, span_id)` 设置联合唯一约束。
5. Span 的 run_id 关联 runs。
6. Span 的 agent_id 关联 agents，允许为空。
7. Span 的 parent_span_id 在应用层验证其所属 Trace 和父子关系。
8. Span Event 通过 `(trace_id, span_id)` 关联 Span。

特别需要注意：同一条 Trace 中不允许出现重复的 Span ID。

---

## 6. 数据库索引与优化设计

本项目不只是使用数据库存储数据，还需要通过真实查询场景展示索引的价值。

### 6.1 索引设计

建议第一版建立以下索引：

| 索引名称 | 索引字段 | 优化场景 |
|---|---|---|
| idx_runs_task_time | task_id, started_at | 查询任务执行历史 |
| idx_runs_status_time | status, started_at | 按状态和时间查询 |
| idx_spans_trace_time | trace_id, start_time | 查询完整执行链路 |
| idx_spans_agent_time | agent_id, start_time | 查询 Agent 历史操作 |
| idx_events_trace_time | trace_id, occurred_at | 查询 Trace 事件 |
| idx_spans_error_time | start_time，部分索引 | 查询失败操作 |
| idx_spans_attributes_gin | attributes，GIN | 查询 JSONB 扩展属性 |

注意：上述索引是设计候选，不代表每个索引都必然提升性能。最终应根据实际查询负载和执行计划确定。

### 6.2 核心优化实验

**实验一：普通查询与索引查询对比**

查询最近执行的任务：

```sql
SELECT *
FROM runs
WHERE task_id = '指定任务ID'
ORDER BY started_at DESC
LIMIT 20;
```

比较建立 `(task_id, started_at)` 索引前后的执行情况。

**实验二：普通索引与部分索引对比**

查询失败的 Span：

```sql
SELECT *
FROM spans
WHERE status = 'ERROR'
ORDER BY start_time DESC;
```

建立部分索引：

```sql
CREATE INDEX idx_spans_error_time
ON spans(start_time DESC)
WHERE status = 'ERROR';
```

比较两种索引策略在错误记录查询中的效果。

**实验三：JSONB 与 GIN 索引对比**

查询使用特定工具的 Span：

```sql
SELECT *
FROM spans
WHERE attributes @> '{"tool_category": "search"}'::jsonb;
```

建立 GIN 索引：

```sql
CREATE INDEX idx_spans_attributes_gin
ON spans
USING GIN(attributes jsonb_path_ops);
```

比较建立 GIN 索引前后的查询性能。

### 6.3 查询计划分析

采用：

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT ...
```

重点观察：

- Sequential Scan / Index Scan。
- 实际扫描行数。
- 估计行数与实际行数。
- Execution Time。
- Shared Buffer 命中与读取情况。

需要注意：数据量较小时，数据库可能认为全表扫描更划算。因此，性能实验必须使用足够的数据规模，并在建立索引后执行 ANALYZE。

---

## 7. Agent 数据采集与生成方案

### 7.1 模拟数据生成

模拟数据是项目的主要数据来源。

设计一个 Python 模拟 Agent 执行器，根据预设工作流产生执行轨迹。

建议设置三种 Agent 角色：

| Agent | 职责 | 模拟行为 |
|---|---|---|
| Research Agent | 信息收集 | 调用搜索工具 |
| Analysis Agent | 信息分析 | 调用模型进行分析 |
| Review Agent | 结果验证 | 检查分析结果 |

一次模拟任务产生以下操作：

```text
任务开始
  |
  v
Research Agent 启动
  |
  +-- LLM 调用
  |
  +-- Search Tool 调用
  |
  v
Analysis Agent 启动
  |
  +-- LLM 调用
  |
  v
Review Agent 启动
  |
  +-- 结果验证
  |
  v
任务完成
```

模拟器应支持：

- 设置任务数量。
- 设置 Agent 数量。
- 设置每个任务的 Span 数量。
- 设置执行成功率。
- 设置不同操作的耗时范围。
- 设置 Token 消耗范围。
- 随机生成异常。
- 生成不同类型的工具调用。

建议提供两种模式：

1. 少量任务实时模拟，用于课堂展示。
2. 大规模批量生成，用于数据库性能测试。

模拟数据使用固定随机种子，以便重复实验。

### 7.2 真实任务接入

在模拟器之外，设计一个真实 Agent Adapter。

第一版不需要实现复杂多智能体框架，只需要实现一个简单的真实任务流程：

```text
用户输入问题
    |
    v
真实 LLM 调用
    |
    v
模拟工具调用
    |
    v
LLM 生成最终结果
    |
    v
记录 Trace 和 Span
```

可以使用兼容 OpenAI API 格式的模型服务，具体服务提供商通过配置文件指定。

真实任务接入时，需要采集：

- 模型提供商。
- 模型名称。
- 调用耗时。
- 输入 Token。
- 输出 Token。
- 调用状态。
- 异常类型。

不建议默认保存完整 Prompt、模型回复和工具敏感参数，只保存必要的摘要和脱敏后的元数据。

### 7.3 统一数据格式

模拟 Agent 和真实 Agent 必须通过统一的 Trace Recorder 产生数据。

这样前端和数据库不需要区分数据来自模拟器还是真实模型。

---

## 8. 后端接口设计

采用 RESTful API。

| 接口 | 方法 | 功能 |
|---|---|---|
| /api/agents | GET | 获取 Agent 列表 |
| /api/agents | POST | 创建 Agent |
| /api/tasks | GET | 获取任务列表 |
| /api/tasks | POST | 创建任务 |
| /api/runs | GET | 查询执行实例 |
| /api/runs/simulate | POST | 启动模拟任务 |
| /api/runs/real | POST | 启动真实任务 |
| /api/runs/{id} | GET | 查询执行详情 |
| /api/traces/{trace_id} | GET | 查询完整 Trace |
| /api/ingest/spans | POST | 批量写入 Span |
| /api/analytics/overview | GET | 获取总体统计 |
| /api/analytics/agents | GET | 获取 Agent 分析数据 |
| /api/analytics/tools | GET | 获取工具调用分析 |
| /api/analytics/errors | GET | 获取异常分析 |
| /api/benchmarks | GET | 获取数据库性能实验结果 |

### 接口设计要求

1. 统一返回 JSON。
2. 统一错误码和错误信息。
3. 支持分页。
4. 时间参数统一使用 ISO 8601 格式。
5. 批量写入接口支持幂等处理。
6. 真实模型接口不允许将 API Key 返回前端。

---

## 9. 前端页面设计

建议开发五个主要页面。

### 页面一：运行监控总览

展示：

- 总任务数。
- 成功率。
- 失败率。
- 平均执行时间。
- Token 消耗。
- Agent 执行数量趋势。
- 错误类型分布。

### 页面二：Agent 与任务管理

展示：

- Agent 列表。
- Agent 角色和模型信息。
- 任务列表。
- 任务执行状态。
- 启动模拟任务入口。

### 页面三：执行轨迹详情

这是最重要的展示页面。

展示：

- Trace 基本信息。
- 所属任务。
- 参与 Agent。
- Span 调用树。
- 各 Span 执行时间。
- 每个操作的状态。
- Token 消耗。
- 异常信息。

建议采用调用树 + 时间线的组合展示形式。

### 页面四：运行日志与性能分析

展示：

- 运行日志列表。
- 时间范围筛选。
- Agent 筛选。
- 错误状态筛选。
- Token 统计。
- Agent 性能对比。
- 工具调用统计。

### 页面五：数据库性能分析

展示：

- 数据库表规模。
- 索引信息。
- SQL 查询示例。
- 优化前后执行计划。
- 查询耗时对比。
- 数据库性能实验结果。

---

## 10. 技术选型

| 技术层 | 推荐技术 | 用途 |
|---|---|---|
| 前端 | Vue 3 + TypeScript | 页面开发 |
| UI 组件 | Element Plus | 页面组件 |
| 图表 | ECharts | 统计图表 |
| 后端 | Python FastAPI | API 服务 |
| ORM | SQLAlchemy | 数据库访问 |
| 数据校验 | Pydantic | 请求数据校验 |
| 数据库 | PostgreSQL 16+ | 数据存储 |
| 模拟器 | Python | 生成 Agent 执行数据 |
| 真实模型 | OpenAI 兼容 API | 少量真实任务 |
| 部署 | Docker Compose | 环境管理 |
| 版本控制 | Git | 多人协作 |

### 技术选型原则

为了控制开发时间：

- 不使用 Kafka。
- 不使用复杂消息队列。
- 第一版不引入 Redis。
- 不建设独立微服务集群。
- 不开发自定义 Agent 框架。
- 不引入独立时序数据库。
- 不引入独立向量数据库。

第一版采用单体后端 + 模块化业务结构即可。

---

## 11. 数据库技术实践与加分设计

### 11.1 必做技术实践

| 技术 | 实践内容 | 展示方式 |
|---|---|---|
| 关系建模 | Agent、Task、Run、Span 关系设计 | ER 图 |
| 事务处理 | 执行实例及批量 Span 数据写入 | 事务演示 |
| 并发控制 | 多个模拟 Agent 同时写入记录 | 并发测试 |
| 索引设计 | 组合索引和部分索引 | 查询耗时对比 |
| JSONB | 扩展属性存储 | JSON 查询 |
| 查询优化 | EXPLAIN ANALYZE | 执行计划对比 |

### 11.2 事务设计

建议设置两个重点事务场景：

**场景一：批量写入执行数据**

一次批量写入操作将 Span 和对应事件写入数据库。

通过事务保证同一批次的数据一致性。

对同一 `(trace_id, span_id)` 重复提交的数据，利用唯一约束和 `ON CONFLICT` 进行幂等处理。

**场景二：任务完成状态更新**

当任务结束时：

1. 计算任务总耗时。
2. 统计 Token 消耗。
3. 统计异常数量。
4. 更新 Run 状态。
5. 保存最终统计结果。

这些操作通过一个事务完成，避免出现任务已完成但统计信息尚未更新的情况。

### 11.3 并发测试

模拟多个 Agent 同时向数据库写入运行记录。

观察：

- 并发写入成功率。
- 重复数据数量。
- 数据库写入吞吐量。
- 查询期间的数据一致性。

通过数据库的事务与唯一约束保证数据正确性。

### 11.4 可选数据库内核实践

如果核心系统提前完成，可以进一步研究 HuaDB。

优先考虑：

**缓冲池页面替换策略扩展：LRU 与 CLOCK 对比。**

具体实施：

1. 阅读 HuaDB 的 BufferPool 和 BufferStrategy 代码。
2. 分析现有 LRU 页面替换策略。
3. 增加 CLOCK 替换策略实现。
4. 构造不同页面访问序列。
5. 比较 LRU 与 CLOCK 的缓存命中率、页面淘汰次数和执行时间。

实验场景：

- 顺序扫描。
- 固定热点页面循环访问。
- 热点与冷数据混合访问。

HuaDB 实验 1 已涉及 BufferPool 和 LRU 替换策略，实验 6 涉及 B+ 树索引，因此这两个模块可以作为后续内核实践的参考入口。

这项扩展与 PostgreSQL 主应用独立，不要求把 HuaDB 替换成项目数据库。

注意：应先保证 HuaDB 可以正常编译和运行，再进行扩展；课程实验代码按照课程文档要求放在私有仓库中，不公开上传。

---

## 12. 项目实施计划

建议按 18 天安排，前 14 天保证核心系统交付，最后 4 天进行扩展和验收。

| 时间 | 工作内容 | 阶段成果 |
|---|---|---|
| 第 1～2 天 | 需求分析、架构设计、数据库设计 | 设计文档、ER 图、接口定义 |
| 第 3～5 天 | 数据库建表、后端基础接口、模拟器 | 数据库和基础后端 |
| 第 6～8 天 | Agent 管理、任务管理、执行数据采集 | 核心数据链路 |
| 第 9～11 天 | 前端页面、Trace 查询和可视化 | 完整基础系统 |
| 第 12～14 天 | 性能分析、索引优化、并发测试 | 核心项目交付 |
| 第 15～16 天 | 真实模型接入、异常分析 | 扩展功能 |
| 第 17～18 天 | HuaDB 尝试、系统验收、汇报准备 | 最终演示版本 |

如果实际只有两周，应优先保证前 14 天的功能，HuaDB 扩展和智能异常分析可以取消。

---

## 13. 团队分工

按照一人负责设计、三人负责实现的方式进行分工。

| 成员 | 主要职责 | 具体交付物 |
|---|---|---|
| 你 | 总体架构、需求分析、数据库设计、接口规范、代码验收 | 设计文档、ER 图、接口规范、验收报告 |
| 成员 1 | 前端开发 | 五个主要页面及交互 |
| 成员 2 | 后端与数据库开发 | 数据表、API、事务、查询和索引 |
| 成员 3 | Agent 数据生成、真实任务接入、测试 | 模拟器、Trace Recorder、性能测试 |

### 协作要求

1. 由你统一确定数据表结构。
2. 由你统一确定 API 输入输出格式。
3. 成员 1 只根据 API 契约开发前端。
4. 成员 2 根据数据库设计开发后端。
5. 成员 3 根据统一数据结构实现模拟器和测试。
6. 所有人不得自行修改公共字段定义而不通知其他成员。

对于编程 Agent，建议先将接口文档和数据模型固定，再分配独立模块，避免多个 Agent 同时修改同一批文件。

---

## 14. 测试与验收方案

### 14.1 功能测试

| 测试项目 | 预期结果 |
|---|---|
| Agent 创建 | 正确保存 Agent 信息 |
| 任务创建 | 正确生成 Task |
| 模拟执行 | 正确产生 Run 和 Span |
| Trace 查询 | 正确查询完整执行链路 |
| 父子关系 | 正确还原 Span 层级 |
| 日志检索 | 能够根据条件查询事件 |
| 性能统计 | 统计结果与数据库记录一致 |
| 真实任务 | 能够采集真实模型调用信息 |

### 14.2 数据库测试

重点验证：

- 批量写入的数据完整性。
- 重复提交是否产生重复 Span。
- 并发写入是否出现数据异常。
- 索引建立前后的查询性能。
- JSONB 查询是否正确。
- 查询执行计划是否发生合理变化。

### 14.3 性能测试

建议构造至少 10 万条 Span 的测试数据，设备性能允许时增加到 20 万～50 万条。

测试以下指标：

- 批量写入吞吐量。
- 查询平均耗时。
- 查询 P50、P95 耗时。
- 索引前后的扫描行数。
- 数据库 Buffer 命中情况。

所有对比应保持相同数据集、相同查询条件和相同硬件环境，重复测试并报告中位数。

不预设性能提升比例，以实际实验结果为准。

### 14.4 项目验收标准

第一版至少满足：

1. 可以启动并运行完整系统。
2. 可以模拟生成 Agent 执行数据。
3. 可以保存并查询执行轨迹。
4. 可以展示 Span 调用关系。
5. 可以查看运行指标和异常记录。
6. 可以完成至少两项数据库性能对比实验。
7. 能够完成课堂演示。
8. 真实模型接入作为扩展验收目标。

---

## 15. 课堂汇报与演示设计

建议将汇报分成四部分。

### 第一部分：项目背景与需求

介绍 AI Agent 的发展背景，解释为什么 Agent 执行数据需要统一管理，以及传统日志方式的局限。

### 第二部分：系统架构与功能展示

现场展示：

1. 系统监控总览。
2. 模拟 Agent 执行任务。
3. Trace 执行链路。
4. Span 详情。
5. 异常记录。
6. Token 消耗和性能统计。

### 第三部分：数据库设计与技术实践

重点介绍：

- ER 图与表结构。
- Trace/Span 数据模型。
- JSONB 扩展属性。
- 组合索引和部分索引。
- 事务与并发控制。
- SQL 执行计划。
- 查询优化实验结果。

### 第四部分：总结与扩展

介绍：

- 当前系统的实现成果。
- 数据库优化实验结论。
- HuaDB 内核扩展尝试。
- 后续可扩展的 OpenTelemetry 数据接入和智能异常分析。

建议现场使用一条失败的 Agent 任务作为主线，让老师从任务执行、异常定位到数据库优化完整看到系统价值。

---

## 16. 风险与应对措施

| 风险 | 应对方案 |
|---|---|
| 真实模型 API 不可用 | 模拟数据保证演示 |
| Agent 数据格式不统一 | 统一 Trace Recorder |
| 前后端接口不一致 | 提前冻结 API 文档 |
| 索引优化效果不明显 | 扩大数据规模并检查执行计划 |
| HuaDB 修改耗时过长 | 独立扩展分支，不影响主系统 |
| 多人开发代码冲突 | 固定模块边界和公共接口 |
| 真实任务泄露敏感信息 | 默认脱敏，不保存完整提示词和密钥 |

---

## 17. 项目预期成果

最终应交付：

1. 一套可以运行的 AI Agent 可观测性分析系统。
2. 一套 PostgreSQL 数据库及完整建表脚本。
3. 一套 Agent 模拟数据生成程序。
4. 一套 Trace/Span 数据采集与查询接口。
5. 一个完整的前端可视化页面。
6. 数据库索引优化和性能测试报告。
7. 系统设计文档、ER 图和接口文档。
8. 项目演示 PPT 和演示数据。

可选成果：

- 真实大模型调用接入。
- HuaDB 缓冲池替换策略扩展。
- 智能异常分析功能。

---

## 18. 参考资料

1. [清华大学数据库管理系统课程主页](https://dbgroup.cs.tsinghua.edu.cn/ligl/courses_cn.html)
2. [HuaDB 数据库内核课程实验文档](https://thu-db.github.io/huadb-doc/)
3. [HuaDB Gitee 仓库](https://gitee.com/thu-db/huadb)
4. [OpenTelemetry Trace API](https://github.com/open-telemetry/opentelemetry-specification/blob/main/specification/trace/api.md)
5. [OpenTelemetry GenAI Agent Semantic Conventions](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md)
6. [PostgreSQL JSON Types](https://www.postgresql.org/docs/current/datatype-json.html)
7. [PostgreSQL Partial Indexes](https://www.postgresql.org/docs/current/indexes-partial.html)

---

**方案总结：**

本项目以 AI Agent 运行数据为业务场景，以 Trace/Span 执行轨迹管理为核心功能，以 PostgreSQL 为数据存储基础，通过事务、索引、并发控制和查询优化等数据库技术完成系统设计与实践。

项目采用模拟 Agent 为主、真实 Agent 为辅的数据来源，既能够在有限开发周期内保证系统完整性，又能够通过数据库实验体现课程的技术深度。

在核心系统完成后，可以进一步结合 HuaDB 开展缓冲池页面替换策略扩展，形成应用系统与数据库内核技术实践相结合的项目成果。