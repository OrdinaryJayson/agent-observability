# AI Agent 执行轨迹管理与可观测性分析系统

> 实施说明：本文件保留原设计和历史示例；开发范围、接口、模块归属及冲突处理以 [开发与联调契约 V1.0](05-integration-contract.md) 为准。
# 工程开发规范与原型实施指南 V1.0

**文档性质：** 工程协作规范、原型实施规范

**适用对象：** 项目负责人、前端开发人员、后端开发人员、数据采集与测试开发人员

**项目周期：** 2～3 周

**文档目的：** 统一项目工程结构、开发环境、数据规范、接口行为、协作流程，并指导团队完成最小可运行原型。

---

# 第一章 文档体系与开发原则

## 1.1 项目文档体系

项目统一使用以下文档：

| 编号 | 文档名称 | 主要用途 |
|---|---|---|
| DOC-01 | 项目总体设计方案 | 确定项目目标、功能、架构和技术路线 |
| DOC-02 | 数据库设计与 API 接口规范 | 确定数据库结构、索引、接口定义 |
| DOC-03 | 工程开发规范与原型实施指南 | 统一开发环境、代码规范、协作流程和原型要求 |
| DOC-04 | 测试与验收记录 | 记录功能测试、性能实验和验收结果 |

所有开发人员必须以这些文档为共同依据。

如需修改公共数据结构、数据库字段或 API 接口，必须先与项目负责人确认，并同步更新相关文档。

## 1.2 项目核心开发原则

1. 数据库是系统的核心，Agent 只是数据产生者。
2. 模拟 Agent 和真实 Agent 使用统一的数据采集结构。
3. 所有数据库访问通过后端服务完成。
4. 前后端通过统一 API 通信。
5. 第一版优先实现完整业务闭环，不追求复杂技术架构。
6. 不引入不必要的中间件和基础设施。
7. 所有功能必须具有明确的验收标准。
8. 数据库性能优化必须通过实际实验验证。

## 1.3 第一版明确不做的事情

- 不开发完整的多 Agent 自主规划框架。
- 不开发独立消息队列。
- 不开发分布式微服务。
- 不开发实时流式 Trace 采集。
- 不实现复杂的用户权限体系。
- 不开发自定义数据库引擎。
- 不要求所有 Agent 都接入真实大模型。

---

# 第二章 技术环境与版本规范

## 2.1 统一技术栈

| 技术 | 版本约定 | 使用范围 |
|---|---|---|
| Python | 3.11 | 后端和模拟器 |
| FastAPI | 0.115 系列 | 后端 API |
| SQLAlchemy | 2.0 系列 | ORM |
| Pydantic | 2.x | 数据校验 |
| PostgreSQL | 16 | 数据存储 |
| Vue | 3.x | 前端 |
| TypeScript | 5.x | 前端开发 |
| Node.js | 22 LTS | 前端环境 |
| Element Plus | 2.x | UI 组件 |
| ECharts | 5.x | 数据可视化 |
| Docker Compose | V2 | 数据库环境管理 |
| Git | 2.x | 版本控制 |

实际安装版本以项目锁定文件为准。

开发期间不得随意升级主要依赖版本。

## 2.2 环境要求

所有开发人员需要准备：

- Git
- Docker Desktop 或 Docker Engine
- Python 3.11
- Node.js 22 LTS
- npm
- IDE 或代码编辑器

推荐使用 VS Code。

## 2.3 数据库配置

统一数据库配置：

| 配置项 | 约定值 |
|---|---|
| 数据库名称 | agent_observability |
| 数据库用户 | agent_user |
| 数据库端口 | 5432 |
| 数据库 | PostgreSQL 16 |
| 字符编码 | UTF-8 |
| 时区 | UTC |

数据库连接字符串通过环境变量配置。

---

# 第三章 项目目录与模块边界

## 3.1 统一目录结构

```text
agent-observability/
│
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   ├── components/
│   │   ├── views/
│   │   ├── router/
│   │   ├── types/
│   │   └── utils/
│   ├── package.json
│   └── vite.config.ts
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── agents.py
│   │   │   ├── tasks.py
│   │   │   ├── runs.py
│   │   │   ├── traces.py
│   │   │   └── analytics.py
│   │   │
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── repositories/
│   │   ├── services/
│   │   ├── recorder/
│   │   ├── simulator/
│   │   ├── adapters/
│   │   ├── analytics/
│   │   ├── core/
│   │   └── main.py
│   │
│   ├── tests/
│   └── requirements.txt
│
├── database/
│   ├── migrations/
│   │   └── 001_init.sql
│   ├── seed.sql
│   └── benchmarks/
│       ├── index_test.sql
│       ├── jsonb_test.sql
│       └── query_test.sql
│
├── scripts/
│   ├── generate_data.py
│   ├── benchmark.py
│   └── reset_database.py
│
├── docs/
│   ├── overall-design.md
│   ├── database-api.md
│   ├── development-guide.md
│   ├── prototype-acceptance.md
│   └── test-report.md
│
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

## 3.2 各目录职责

### frontend

负责所有前端页面和交互。

- api：统一封装 HTTP 请求。
- components：公共组件。
- views：业务页面。
- router：页面路由。
- types：API 数据类型定义。
- utils：时间格式化、状态映射等公共工具。

前端不得直接连接 PostgreSQL。

### backend

负责所有后端业务逻辑。

- api：处理 HTTP 请求。
- models：SQLAlchemy 数据库模型。
- schemas：Pydantic 请求和响应模型。
- repositories：数据库访问。
- services：业务逻辑。
- recorder：Trace 和 Span 数据记录。
- simulator：模拟 Agent 执行器。
- adapters：真实模型适配器。
- analytics：统计分析服务。
- core：配置、数据库连接和公共组件。

### database

保存数据库结构和实验 SQL。

数据库结构变更必须通过版本化 SQL 文件管理。

### scripts

保存独立的数据生成和性能测试程序。

---

# 第四章 模块开发责任与文件所有权

## 4.1 人员分工

| 角色 | 主要工作 | 责任范围 |
|---|---|---|
| 项目负责人 | 总体设计、数据库审查、接口协调、验收 | 公共规范、数据库设计、集成 |
| 开发成员 1 | 前端开发 | frontend/ |
| 开发成员 2 | 后端与数据库开发 | backend/、database/ |
| 开发成员 3 | 模拟器、真实模型适配、测试 | backend/simulator/、backend/adapters/、scripts/ |

## 4.2 文件修改约定

| 文件或模块 | 主要负责人 |
|---|---|
| frontend/ | 成员 1 |
| backend/api/ | 成员 2 |
| backend/models/ | 成员 2 |
| backend/repositories/ | 成员 2 |
| backend/services/ | 成员 2 |
| backend/recorder/ | 成员 2，成员 3 配合 |
| backend/simulator/ | 成员 3 |
| backend/adapters/ | 成员 3 |
| scripts/ | 成员 3 |
| database/ | 成员 2，负责人审批 |
| docs/ | 项目负责人 |

其他成员需要修改不属于自己负责的文件时，必须先沟通。

## 4.3 模块调用关系

```text
Frontend
   |
   v
API Router
   |
   v
Service Layer
   |
   +------------------+
   |                  |
   v                  v
Repository         Recorder
   |                  |
   v                  v
PostgreSQL       Simulator / Adapter
                      |
                      v
                 TraceRecorder
                      |
                      v
                 Service Layer
```

注意：

模拟器和真实模型适配器都属于后端业务的一部分，不允许各自实现一套独立的数据存储逻辑。

---

# 第五章 公共数据与业务语义规范

## 5.1 ID 生成规范

| 字段 | 格式 | 生成方式 |
|---|---|---|
| agent_id | UUID | 后端生成 |
| task_id | UUID | 后端生成 |
| run_id | UUID | 后端生成 |
| trace_id | 32 位小写十六进制 | 随机生成 16 字节 |
| span_id | 16 位小写十六进制 | 随机生成 8 字节 |
| event_id | UUID | Recorder 生成 |

同一 Run 内 Span ID 不允许重复。

Event ID 在重试提交时必须保持不变。

## 5.2 时间规范

所有后端和数据库时间统一使用 UTC。

格式：

```text
2026-11-09T10:00:00Z
```

数据库使用 TIMESTAMPTZ。

前端可以转换为用户本地时间展示，但不得改变提交给后端的时间语义。

## 5.3 状态规范

### Run 状态

```text
RUNNING
   |
   +----> SUCCESS
   |
   +----> FAILED
   |
   +----> CANCELLED
```

规则：

- 创建时必须是 RUNNING。
- 终态只能是 SUCCESS、FAILED 或 CANCELLED。
- 终态不可逆。
- 重新执行任务必须创建新的 Run。
- 任务执行失败不代表 Span 数据全部失败。

### Span 状态

```text
SUCCESS
ERROR
```

第一版只在 Span 执行结束后保存，因此不需要 RUNNING 状态。

### Event Severity

```text
TRACE
DEBUG
INFO
WARN
ERROR
```

## 5.4 Operation Type

统一使用：

```text
AGENT
LLM
TOOL
RETRIEVAL
WORKFLOW
OTHER
```

不允许开发成员自行增加不一致的操作类型。

## 5.5 Token 统计约定

- 只有 LLM 调用 Span 记录 Token。
- Token 未知时为 null。
- 不允许未知 Token 使用 0 代替。
- 非 LLM Span 不记录 Token。
- Agent 父 Span 不重复汇总子 Span Token。
- 总 Token 数量由 SQL 聚合计算。

## 5.6 Span 结构约定

一个 Run 对应一个 Trace。

每条 Trace 必须满足：

1. 至少包含一个 Span。
2. 必须且只能有一个根 Span。
3. 根 Span 的 parent_span_id 为 null。
4. 非根 Span 的父节点必须存在。
5. 父子 Span 必须属于同一个 Run。
6. 不允许出现循环引用。
7. 所有 Span 必须能够沿父节点关系追溯到根 Span。

推荐的根 Span：

```text
operation_type = WORKFLOW
span_name = Task Execution
agent_id = null
parent_span_id = null
```

## 5.7 数据扩展属性规范

attributes 用于存储不适合固定成数据库字段的扩展信息。

例如：

```json
{
  "tool_category": "search",
  "request_id": "req_001",
  "retry_count": 1,
  "scenario": "research"
}
```

固定的查询字段优先设计成数据库列。

不允许把所有字段都塞入 JSONB。

---

# 第六章 Trace Recorder 与数据一致性约定

这是整个系统最重要的工程约定。

## 6.1 第一版采集策略

第一版采用：

**执行期间内存记录，执行结束后批量持久化。**

不实现实时流式 Span 写入。

执行流程：

```text
创建 Run
   |
   v
初始化 TraceRecorder
   |
   v
模拟 Agent 执行
   |
   +----> 创建 Span
   |
   +----> 记录 Event
   |
   +----> 维护父子关系
   |
   v
执行结束
   |
   v
完整 Trace 数据校验
   |
   v
数据库事务
   |
   +----> 插入 Spans
   |
   +----> 插入 Events
   |
   +----> 更新 Run 最终状态
   |
   v
提交事务
```

## 6.2 Recorder 责任

TraceRecorder 负责：

- 创建 Trace ID。
- 创建 Span ID。
- 记录 Span 开始和结束时间。
- 维护父子关系。
- 记录操作状态。
- 记录 Token 信息。
- 记录异常信息。
- 记录 Event。
- 在 Run 结束后提交完整数据。

模拟器和真实模型适配器不得自行拼接 SQL。

## 6.3 数据写入事务

推荐将完整 Trace 保存和 Run 结束操作封装为一个业务服务方法：

```python
complete_run(
    run_id,
    spans,
    events,
    final_status,
    error_summary
)
```

该方法在一个数据库事务内完成：

1. 查询并锁定 Run。
2. 确认 Run 当前为 RUNNING。
3. 校验 Span ID 和父子关系。
4. 插入全部 Span。
5. 插入全部 Event。
6. 更新 Run 最终状态。
7. 提交事务。

任何一步失败，全部回滚。

这样可以避免出现 Run 已经 SUCCESS，但 Span 数据还未完整保存的情况。

## 6.4 第一版规模限制

| 项目 | 限制 |
|---|---:|
| 单个 Run 的 Span 数量 | 最多 500 |
| 单个 Run 的 Event 数量 | 最多 2000 |
| 单批 Span 提交数量 | 最多 500 |
| 单批 Event 提交数量 | 最多 2000 |

性能测试的大规模数据通过多个 Run 生成，不通过单个 Run 无限扩展。

## 6.5 幂等性

对于同一 Run：

- 相同 span_id、相同内容：重复提交视为成功，不重复插入。
- 相同 span_id、不同内容：返回 409 冲突。
- 相同 event_id、相同内容：重复提交视为成功。
- 相同 event_id、不同内容：返回 409 冲突。

禁止直接使用无条件覆盖方式处理重复数据。

## 6.6 故障恢复约定

第一版不实现后台任务持久化队列。

因此，如果后端进程在任务运行期间重启，内存中的未提交 Trace 可能丢失。

系统重新启动时，应将上一次进程遗留的 RUNNING Run 标记为 FAILED，并记录：

```text
error_summary = "Backend restarted before trace persistence"
```

这属于第一版可接受的工程限制。

后续可以通过持久化任务队列和增量 Span 写入解决。

---

# 第七章 API 与前后端通信规范

## 7.1 基础规范

统一接口前缀：

```text
/api/v1
```

字段命名统一使用 snake_case。

时间采用 ISO 8601 UTC 格式。

JSON 使用 UTF-8。

## 7.2 API 返回格式

成功：

```json
{
  "data": {},
  "message": "success"
}
```

列表：

```json
{
  "data": [],
  "meta": {
    "page": 1,
    "page_size": 20,
    "total": 100
  }
}
```

失败：

```json
{
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "Resource not found",
    "details": {}
  }
}
```

## 7.3 HTTP 状态码

| 状态码 | 使用场景 |
|---|---|
| 200 | 查询或操作成功 |
| 201 | 资源创建成功 |
| 202 | 异步任务已接受 |
| 400 | 请求不合法 |
| 404 | 资源不存在 |
| 409 | 状态或数据冲突 |
| 422 | 参数校验失败 |
| 500 | 服务内部错误 |

## 7.4 分页约定

默认：

```text
page = 1
page_size = 20
```

最大：

```text
page_size = 100
```

## 7.5 时间查询约定

所有时间范围使用左闭右开区间：

```text
[start_time, end_time)
```

例如：

```text
2026-11-01T00:00:00Z
2026-11-02T00:00:00Z
```

这样相邻时间窗口不会重复统计。

## 7.6 MVP 接口范围

第一版必须实现：

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | /api/v1/agents | Agent 列表 |
| POST | /api/v1/agents | 创建 Agent |
| GET | /api/v1/tasks | Task 列表 |
| POST | /api/v1/tasks | 创建 Task |
| GET | /api/v1/runs | Run 列表 |
| POST | /api/v1/tasks/{task_id}/runs | 启动 Run |
| GET | /api/v1/runs/{run_id} | Run 详情 |
| GET | /api/v1/traces/{trace_id} | Trace 详情 |
| GET | /api/v1/traces/{trace_id}/events | Event 查询 |
| GET | /api/v1/analytics/overview | 总览统计 |
| GET | /api/v1/analytics/agents | Agent 统计 |
| GET | /api/v1/analytics/tools | 工具统计 |
| GET | /api/v1/analytics/errors | 异常统计 |

第一版模拟器和真实模型适配器都运行在后端内部，因此通过 TraceRecorder 和统一 Service 完成数据持久化。

此前设计的外部 `/spans/batch` 数据采集接口暂不列入 MVP 必做范围。未来需要支持独立 Agent 服务或 OpenTelemetry OTLP 接入时再增加。

## 7.7 Run 异步执行

启动 Run：

```http
POST /api/v1/tasks/{task_id}/runs
```

返回：

```json
{
  "data": {
    "run_id": "uuid",
    "trace_id": "32位十六进制字符串",
    "status": "RUNNING"
  },
  "message": "run accepted"
}
```

HTTP 状态码：202。

前端通过：

```http
GET /api/v1/runs/{run_id}
```

定期查询状态。

建议每 1.5～2 秒查询一次。

当 Run 进入终态后，再调用 Trace 查询接口。

第一版使用 FastAPI BackgroundTasks 即可，不引入 Celery 或消息队列。

## 7.8 OpenAPI 规范

FastAPI 自动生成：

```text
/docs
```

前后端开发以实际 OpenAPI Schema 为接口实现依据。

接口变更必须同步更新 Schema。

---

# 第八章 前端交互与页面规范

## 8.1 页面范围

第一版只开发四个主要页面。

### 页面一：运行监控总览

展示：

- 总任务数。
- 成功率。
- 失败率。
- 平均执行时间。
- Token 消耗。
- 执行趋势。
- 异常分布。

### 页面二：Agent 与任务管理

展示：

- Agent 列表。
- Agent 角色。
- 模型信息。
- Task 列表。
- 创建 Task。
- 启动模拟任务。
- 启动真实任务。

### 页面三：Trace 执行轨迹

展示：

- Run 基本信息。
- Trace ID。
- Span 数量。
- 调用树。
- Span 时间线。
- Span 详细信息。
- Event 和异常信息。

### 页面四：性能分析与数据库实验

展示：

- Agent 性能排名。
- 工具调用统计。
- 失败率分析。
- Token 消耗统计。
- SQL 查询耗时对比。
- 执行计划分析。

## 8.2 前端统一状态样式

| 状态 | 展示方式 |
|---|---|
| RUNNING | 蓝色标签 |
| SUCCESS | 绿色标签 |
| FAILED | 红色标签 |
| CANCELLED | 灰色标签 |
| ERROR | 红色标签 |

## 8.3 Trace 树构建规范

后端返回扁平 Span 数组。

前端根据 parent_span_id 构建树。

不允许后端和前端同时各自维护不同版本的树形数据。

## 8.4 页面公共状态

所有页面需要考虑：

- 加载中。
- 请求失败。
- 无数据。
- 正常显示。
- 分页状态。
- 时间筛选状态。

---

# 第九章 Docker 与环境启动规范

## 9.1 Docker Compose

项目根目录创建 docker-compose.yml：

```yaml
services:
  db:
    image: postgres:16-alpine
    container_name: agent-observability-db
    restart: unless-stopped

    environment:
      POSTGRES_DB: ${POSTGRES_DB:-agent_observability}
      POSTGRES_USER: ${POSTGRES_USER:-agent_user}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?Set DB password}

    ports:
      - "5432:5432"

    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./database/migrations:/docker-entrypoint-initdb.d:ro

    healthcheck:
      test:
        - CMD-SHELL
        - pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}
      interval: 5s
      timeout: 5s
      retries: 10

volumes:
  postgres_data:
```

数据库迁移脚本按照文件名顺序执行，例如：

```text
001_init.sql
002_add_field.sql
003_add_index.sql
```

注意：初始化脚本只在数据库首次创建时自动执行。已经存在的数据库需要手动执行新增迁移。

## 9.2 环境变量

创建 `.env.example`：

```env
POSTGRES_DB=agent_observability
POSTGRES_USER=agent_user
POSTGRES_PASSWORD=change_me

DATABASE_URL=postgresql+psycopg://agent_user:change_me@localhost:5432/agent_observability

API_HOST=0.0.0.0
API_PORT=8000

CORS_ORIGINS=http://localhost:5173

MODEL_BASE_URL=
MODEL_API_KEY=
MODEL_NAME=
```

每个成员复制为本地 `.env`。

真实 API Key 不允许提交到 Git。

前端另设：

```env
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

## 9.3 启动步骤

### 第一步：启动数据库

```bash
docker compose up -d db
```

检查：

```bash
docker compose ps
```

### 第二步：启动后端

```bash
cd backend

python -m venv .venv
```

激活虚拟环境后：

```bash
pip install -r requirements.txt
```

启动：

```bash
uvicorn app.main:app --reload
```

后端地址：

```text
http://localhost:8000
```

接口文档：

```text
http://localhost:8000/docs
```

### 第三步：启动前端

```bash
cd frontend

npm install
npm run dev
```

前端地址：

```text
http://localhost:5173
```

## 9.4 数据库重置

开发环境需要彻底清空数据库时：

```bash
docker compose down -v
docker compose up -d db
```

注意：`down -v` 会删除数据库持久化数据，仅允许在开发或测试环境使用。

---

# 第十章 Git 与代码协作规范

## 10.1 分支结构

```text
main
  |
  +-- develop
        |
        +-- feature/frontend
        |
        +-- feature/backend
        |
        +-- feature/simulator
```

## 10.2 分支约定

- main：稳定可运行版本。
- develop：集成开发分支。
- feature/frontend：前端功能开发。
- feature/backend：后端功能开发。
- feature/simulator：模拟器及测试开发。

禁止直接向 main 提交代码。

## 10.3 提交信息

统一使用：

```text
feat: add trace detail page
feat: implement agent simulator
fix: correct span parent validation
test: add trace ingestion tests
docs: update database schema
refactor: simplify recorder service
```

## 10.4 合并要求

合并前必须：

1. 能正常运行。
2. 不破坏已有接口。
3. 不擅自修改数据库公共结构。
4. 通过相关模块测试。
5. 更新必要文档。

项目负责人负责公共接口和数据库结构的最终审核。

---

# 第十一章 代码质量与测试规范

## 11.1 Python 规范

- 使用类型注解。
- 使用 Pydantic 进行数据校验。
- 数据库操作统一通过 Repository。
- 业务逻辑统一放在 Service。
- 不在 API Router 中堆积复杂业务代码。
- 使用参数化 SQL。
- 捕获异常时不得直接吞掉错误。

建议使用 Ruff 和 Pytest。

## 11.2 TypeScript 规范

- 公共 API 类型统一放在 types。
- API 请求统一封装。
- 页面不得直接拼接 API 地址。
- 组件不得重复实现相同的数据格式化逻辑。
- 处理接口空数据和请求失败。

## 11.3 后端测试

至少覆盖：

- Agent 创建。
- Task 创建。
- Run 启动。
- Span 数据验证。
- 父子关系验证。
- Trace 查询。
- 幂等写入。
- Run 状态更新。
- 数据库事务回滚。

## 11.4 前端测试

至少验证：

- 页面能够打开。
- API 请求成功。
- 表格能够显示数据。
- Trace 树结构正确。
- Run 状态能够刷新。
- 图表能够展示统计数据。
- 空数据和异常状态正常显示。

## 11.5 Definition of Done

每个模块只有满足以下要求才算完成：

1. 主要功能可以运行。
2. 输入输出符合接口约定。
3. 正常情况测试通过。
4. 异常情况有合理处理。
5. 没有明显的硬编码测试数据。
6. 相关文档已更新。
7. 可以与其他模块正常集成。

---

# 第十二章 最小可运行原型设计

## 12.1 原型目标

原型不是为了做完整系统，而是为了验证整个技术架构能否跑通。

原型必须实现：

**创建任务 → 启动 Run → 模拟 Agent 执行 → 生成 Span → 写入 PostgreSQL → 查询 Trace → 前端展示。**

这是正式开发的前置条件。

## 12.2 原型功能范围

只实现以下内容：

### 前端

一个简单页面，包括：

- 任务名称输入框。
- 启动模拟任务按钮。
- Run 状态显示。
- Trace 执行树。
- Span 详细信息。

### 后端

实现：

- 创建 Task。
- 启动 Run。
- 查询 Run。
- 查询 Trace。
- TraceRecorder。
- complete_run 事务。

### 模拟器

实现三个模拟 Agent：

| Agent | 职责 |
|---|---|
| Research Agent | 模拟信息搜索 |
| Analysis Agent | 模拟信息分析 |
| Review Agent | 模拟结果验证 |

## 12.3 原型测试数据

建议使用：

- 1 个 Task。
- 1 个 Run。
- 3 个 Agent。
- 1 个根 Span。
- 6～8 个子 Span。
- 2～3 个 Event。

执行过程：

```text
Task: AI Agent 技术调研
  |
  +-- Workflow Root
       |
       +-- Research Agent
       |     |
       |     +-- LLM Call
       |     |
       |     +-- Search Tool
       |
       +-- Analysis Agent
       |     |
       |     +-- LLM Call
       |
       +-- Review Agent
             |
             +-- Validation
```

其中可以让一个 Tool Span 执行失败，然后由模拟流程重试成功，以验证 Span 状态和 Run 状态的区别。

## 12.4 原型验收标准

| 编号 | 验收内容 | 通过条件 |
|---|---|---|
| P01 | 数据库启动 | PostgreSQL 正常运行 |
| P02 | 创建 Task | 数据正确写入 |
| P03 | 创建 Run | 状态为 RUNNING |
| P04 | 模拟 Agent | 能生成完整执行过程 |
| P05 | Recorder | Span 和 Event 数据正确 |
| P06 | 事务提交 | 所有记录正确保存 |
| P07 | Trace 查询 | 能查询完整 Span |
| P08 | 父子关系 | 能还原调用树 |
| P09 | 前端展示 | 页面正确展示 Trace |
| P10 | 异常场景 | 失败 Span 和 Run 状态正确 |

十项全部通过后，原型验收完成。

---

# 第十三章 原型两天实施计划

## 第一天上午：环境搭建

成员 2：

- 创建后端项目。
- 配置 PostgreSQL。
- 执行建表脚本。
- 实现数据库连接。

成员 1：

- 创建 Vue 项目。
- 配置 Element Plus。
- 创建简单页面布局。

成员 3：

- 创建模拟器。
- 设计统一 Span 数据结构。
- 实现 TraceRecorder。

项目负责人：

- 检查数据库字段。
- 检查公共接口。
- 统一环境配置。

## 第一天下午：完成数据链路

成员 2：

- 实现 Task 创建。
- 实现 Run 创建。
- 实现 Trace 查询。
- 实现 complete_run。

成员 3：

- 生成三个模拟 Agent。
- 生成父子 Span。
- 生成 Event。
- 调用 Recorder 完成数据提交。

成员 1：

- 完成任务输入和启动按钮。
- 接入 Run 查询接口。

## 第二天上午：完成前端展示

成员 1：

- 实现 Trace 树。
- 实现 Span 详情。
- 实现 Run 状态展示。

成员 2：

- 检查事务。
- 检查外键约束。
- 修复 API 问题。

成员 3：

- 检查 Span 数据完整性。
- 验证失败场景。
- 编写原型测试数据。

## 第二天下午：联调和设计冻结

所有成员：

- 完成端到端演示。
- 检查数据库数据。
- 检查前后端接口。
- 修正设计问题。
- 更新 API 文档。

项目负责人：

- 验收原型。
- 确定是否需要修改数据库设计。
- 冻结正式开发接口。

---

# 第十四章 原型通过后的正式开发计划

| 阶段 | 时间 | 主要工作 |
|---|---|---|
| 原型 | 2 天 | 打通端到端链路 |
| 第一阶段 | 3 天 | 完成核心管理功能 |
| 第二阶段 | 4 天 | 完成 Trace、日志和分析 |
| 第三阶段 | 3 天 | 完成数据库优化实验 |
| 第四阶段 | 2 天 | 真实模型接入和集成 |
| 收尾 | 2～3 天 | 测试、验收和汇报 |

如果实际只有两周，优先保证：

1. 完整系统。
2. Trace 展示。
3. 数据库索引实验。
4. 查询优化对比。
5. 课堂演示。

真实模型接入和 HuaDB 内核扩展均可降级为选做。

---

# 第十五章 最终交付要求

项目完成时必须交付：

## 工程文件

- 前端源代码。
- 后端源代码。
- 模拟 Agent 程序。
- 数据库 SQL 脚本。
- Docker Compose 配置。
- 环境变量模板。

## 项目文档

- 项目总体设计方案。
- 数据库设计与 API 规范。
- 工程开发规范。
- 系统测试报告。
- 数据库性能实验报告。

## 演示材料

- 完整系统。
- 测试数据。
- 演示任务。
- 项目汇报 PPT。
- 系统架构图。
- ER 图。
- 数据库优化实验结果。

---

# 第十六章 项目启动检查清单

正式开发开始前，由项目负责人逐项检查：

- [ ] 所有成员已阅读三份核心设计文档。
- [ ] Git 仓库已建立。
- [ ] 项目目录已创建。
- [ ] Docker Compose 已配置。
- [ ] PostgreSQL 可以正常启动。
- [ ] 数据库建表脚本已提交。
- [ ] 前端环境可以运行。
- [ ] 后端环境可以运行。
- [ ] API 基础地址已统一。
- [ ] 数据字段规范已统一。
- [ ] Span 状态和 Run 状态已明确。
- [ ] TraceRecorder 数据格式已统一。
- [ ] 三个成员的文件责任范围已确定。
- [ ] 原型任务已经分配。

**原型通过后，再正式启动并行开发。**

---

# 文档结束

本指南是项目工程实施的统一约定。任何涉及数据库结构、公共接口、Trace 数据模型和模块边界的修改，必须经过项目负责人确认并同步更新文档。

第一阶段的核心目标不是开发尽可能多的功能，而是验证系统架构、数据模型和端到端数据链路的正确性。