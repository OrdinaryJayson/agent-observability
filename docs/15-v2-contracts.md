# v2 HTTP、工作流与执行公共契约

状态：设计冻结基线，未实现。新增路径前缀`/api/v2`；`/api/v1`继续遵守05/08。负责人拥有本文件和 `contracts/v2/`；B负责将协议实现为共享Pydantic模型、API和数据库边界，C不另建有差异的数据类，A的TS类型必须与Schema核对。

机器可读核心Schema见 [workflow.schema.json](../contracts/v2/workflow.schema.json)、[journal-batch.schema.json](../contracts/v2/journal-batch.schema.json)；联动样例见 [examples.json](../contracts/v2/examples.json)，路由登记见 [http-manifest.json](../contracts/v2/http-manifest.json)。样例是合成协议数据，不能当性能证据。Schema管基础形状，本文管跨字段、状态、时间和幂等；实现时二者都必须通过。

## 1. 通则、分页与错误

- 普通对象仍为`{data, message:"success"}`；创建Run/实验返回202、message=`accepted`；创建工作流201；查询/PATCH/取消请求200。
- 普通请求15秒客户端超时；创建异步作业不等待实验完成；SSE为长连接，不沿用15秒。数据库实验受16的服务端预算限制。
- UTC、snake_case、时区必填、时间窗口左闭右开、未知字段/查询参数422；文本拒绝空字节和非有限数。UUID/hex/枚举格式非法422，合法但路径资源不存在404。
- 基础列表使用`{data:[],meta:{limit:50,next_cursor:null,has_more:false}}`；limit 1–100。工作流按created_at DESC/id DESC，Run按queued_at DESC/run_id DESC，日志按occurred_at DESC/event_id DESC，journal按seq ASC。相等时间用ID打破平局。
- Cursor是带格式版本、排序键、过滤条件哈希的base64url JSON；条件/排序/版本不匹配422。它不是授权凭据。普通列表是连续查询的读已提交视图，不声称多页强快照；同一静态数据集保证不重不漏，实时新增的语义另行说明。Trace快照和journal续传使用严格seq水位。
- `Idempotency-Key`：创建Run、创建实验必填，8–100字符`[A-Za-z0-9_-]`，按方法/资源scope唯一。规范化请求JCS（RFC8785）UTF-8 SHA256用于一致性检查；同键同内容返回原202/资源，不创建新任务；不同内容409 IDEMPOTENCY_CONFLICT。前端点击时生成键，网络未知结果时保留键重试，用户明确“再次执行”才换新键。
- PATCH草稿与发布需要`If-Match: "{revision}"`；缺失428 PRECONDITION_REQUIRED，过期412 REVISION_MISMATCH。不能以最后写入覆盖并发编辑。
- error结构沿用v1；新增码：WORKFLOW_INVALID、REVISION_MISMATCH、PRECONDITION_REQUIRED、IDEMPOTENCY_CONFLICT、LEASE_LOST、CHECKPOINT_CONFLICT、CURSOR_EXPIRED、BUDGET_EXCEEDED、EXPERIMENT_DISABLED、EXPERIMENT_TIMEOUT、AGGREGATE_REFRESH_TIMEOUT。分别用422/412/428/409/409/409/410/422/409/504/504。跨模块不能私自改码。
- CORS增加`Idempotency-Key`、`If-Match`、`Last-Event-ID`请求头，保持GET/POST/PATCH；SSE跨源通过实际浏览器测试。

## 2. 工作流定义

```json
{
  "schema_version": "2.0",
  "scenario": "PARALLEL_RETRIEVAL",
  "roles": [{"role_key":"researcher","name":"检索角色"}],
  "nodes": [
    {"node_key":"start","type":"START","name":"开始","role_key":null,"config":{}},
    {"node_key":"search_a","type":"RETRIEVAL","name":"检索A","role_key":"researcher","config":{"duration_ms":300,"failure_probability":0,"max_retries":1}},
    {"node_key":"search_b","type":"RETRIEVAL","name":"检索B","role_key":"researcher","config":{"duration_ms":600,"failure_probability":0,"max_retries":1}},
    {"node_key":"merge","type":"MERGE","name":"合并","role_key":null,"config":{}},
    {"node_key":"end","type":"END","name":"结束","role_key":null,"config":{}}
  ],
  "edges": [
    {"source":"start","target":"search_a","route":"ALWAYS"},
    {"source":"start","target":"search_b","route":"ALWAYS"},
    {"source":"search_a","target":"merge","route":"ALWAYS"},
    {"source":"search_b","target":"merge","route":"ALWAYS"},
    {"source":"merge","target":"end","route":"ALWAYS"}
  ]
}
```

每个node_key/role_key为1–50位小写字母开头的`[a-z][a-z0-9_]*`，保留`sys_`前缀。角色最多8个，定义不含Agent UUID；Run启动时用`agent_bindings:{role_key:agent_id}`绑定。允许unbound=true的纯模拟，未绑定身份为空；默认unbound=false且角色完整绑定。AGENT容器按角色生成，根WORKFLOW为空身份，LLM/TOOL/RETRIEVAL继承所属角色，不能伪造Agent。

强语义验证：

1. 恰好一个START、一个END；节点/边去重、引用存在、无自环和环；全部节点从START可达并能到END，拒绝孤立分支。
2. START只有出边，END只有入边；只有MERGE允许多个入边，其它步骤至多一个入边；普通边只用ALWAYS。CONDITION恰好两条出边，route分别PASS/FAIL；config仅`result:"PASS"|"FAIL"|"SEEDED"`，不可执行代码。每个条件的两路必须在唯一最近公共后支配MERGE处汇合，汇合前分支之间不能交叉连边；支持结构化嵌套，深度最多4。不能仅因某个MERGE“可达”就认为覆盖所有退出路径。
3. 节点状态为PENDING、RUNNING、SUCCESS、ERROR、SKIPPED、CANCELLED；状态是节点投影，不复用数据库Span状态枚举。未选分支递归标SKIPPED，没有假Span。
4. MERGE等全部入边“已决”：ALWAYS上游成功/选中路由成功为满足，未选分支为inactive；至少一条active且其上游成功才可执行。active上游终态ERROR则阻塞失败并将下游SKIPPED；所有入边inactive则MERGE也SKIPPED。避免一条未选分支阻塞汇合。
5. 一个运行内同node_key可有多次尝试；`attempt_no`从1递增、首次重试为2。单节点max_retries为0–2；恢复WorkerLost造成的重新尝试计入独立的recovery_count，仍受全Run Span/时间预算限制。每次操作都保留原失败Span；不修改失败为成功。
6. LLM/TOOL/RETRIEVAL config固定为`duration_ms`(100–1500)、`failure_probability`(0–1)、`max_retries`(0–2)；LLM可有`input_tokens`/`output_tokens`(0–100000)，省略时固定默认50/20，显式0必须保留。重试退避100ms、200ms（对应第1/2次重试），计入逻辑预算并可取消。START/END/MERGE不等待，config={}。CONDITION只含result。未知config字段拒绝。
7. 默认4个并行步骤，上限4；条件决定图中就绪集合，调度按node_key稳定打破平局。seed按`(seed,node_key,attempt_no)`派生随机源，不能因线程调度改变失败结果。

8. 所选节点重试耗尽即令本次Run最终FAILED；尚未开始的受影响下游标SKIPPED，其它已运行独立分支允许闭合，不再启动与最终结果无关的新步骤。取消已有Run时根最终ERROR/RunCancelled，Run业务状态CANCELLED；未执行节点标CANCELLED。根与角色容器不作为关键路径权重。每个DAG步骤最多一个归属父Span；有role_key时归角色AGENT容器，否则归根。

预算预估包括1根、最多8个AGENT容器、每个可执行节点全部尝试及两次恢复余量。启动时若最坏情况超过500 Span/2000 Event/5000 journal或60秒逻辑执行预算返回422；运行中仍设硬上限，journal预留64条给闭合/控制/恢复，Span Event预留16条给失败收尾。取消只第一次追加请求事件，重复取消不消耗无限日志；heartbeat不进journal。初版编辑器不提供嵌套子工作流和循环。

## 3. HTTP接口登记

| 方法 / 路径（均为/api/v2） | 请求 / 行为 / 核心响应 |
|---|---|
| GET /capabilities | 协议版本、启用开关、预算、场景、算法/实验版本；不泄露凭据 |
| GET /overview | from/to/mode=REALTIME默认；v1历史独列LEGACY；指标、队列、活跃运行、聚合水位 |
| GET、POST /workflows | 列表；创建{name,description,draft}，返回Workflow |
| GET、PATCH /workflows/{id} | 详情；修改name/description/draft/archived，需If-Match；返回新revision |
| POST /workflows/{id}/validate | {draft}；200返回{valid,errors:[{code,node_key,edge_index,path,message}]}；非法JSON形状422，语义不合法valid=false |
| POST /workflows/{id}/versions | {expected_definition_hash}、If-Match；发布当前草稿，201返回Version |
| GET /workflows/{id}/versions | 游标列表；版本不可变 |
| GET /workflow-versions/{id} | 完整定义、definition_hash、version_no |
| POST /tasks/{task_id}/runs | RunStart见下；202返回{run_id,trace_id,execution_state,status,version_id} |
| GET /runs | task_id/version_id/status/execution_state/mode/from/to、游标；RunView |
| GET /runs/{run_id} | RunView：业务状态、队列/执行状态、计数、租约公开摘要、最后seq |
| POST /runs/{run_id}/cancel | body={}；200返回{accepted,already_terminal,run}；不承诺请求返回时已经停完 |
| GET /runs/{run_id}/snapshot | 200 Envelope[Snapshot]，单一seq水位，不分页截断图 |
| GET /runs/{run_id}/journal | after_seq=0、limit=100；200 {data:[JournalEvent],meta:{next_after_seq,has_more,snapshot_seq}} |
| GET /runs/{run_id}/stream | SSE；断线续传见第4节 |
| GET /runs/{run_id}/analysis | 终态分析；运行中409；LEGACY返回supported=false和原因 |
| POST /comparisons | {run_ids:[2–5 UUID]}；200比较结果；版本/时钟模式不同422；非终态409 |
| GET /search/spans | task_id/run_id/agent_id/status/type/error_type/from/to、attributes(JSON object<=2KB)、q<=200、游标 |
| GET /search/events | v1事件筛选+mode；游标；过滤条件哈希绑定cursor |
| GET /analytics/series | metric=RUNS或TOKENS、granularity=DAY、from/to必填<=366天、mode；完整最多366行 |
| GET /analytics/agents | from/to、mode、游标；AGENT容器与LLM Token分开聚合 |
| GET /analytics/aggregate-status | MV水位、snapshot_at、最后刷新状态 |
| POST /analytics/refresh | body={}；同步200返回刷新后的aggregate-status；10秒SQL预算，超时504保留旧MV；跨进程锁防并发刷新；审计 |
| GET、POST /datasets | 登记见第7节；返回manifest，不开放SQL上传 |
| GET /datasets/{id} | 实际计数、分布和摘要 |
| POST /datasets/{id}/finalize | {actual_counts,content_hash}；服务端核对后200返回manifest |
| GET、POST /experiments | 历史列表；请求见16，202返回Experiment |
| GET /experiments/{id} | 状态、阶段、progress(0–1或null)、环境、试验summary |
| POST /experiments/{id}/cancel | 异步取消、保留完成样本 |
| GET /experiments/{id}/trials | 方案/参数/汇总，游标 |
| GET /experiments/{id}/samples | trial_id必填、游标；原始测量/plan |
| GET /experiments/{id}/export | format=json或csv；终态才可导出，CSV为原始样本扁平列、JSON含清单与计划 |
| GET /database/catalog | 白名单表/列/约束/索引/视图说明及实际大小 |
| GET /database/query-templates | 已登记SQL模板、参数、索引映射；不执行请求SQL |
| GET /audit | action/resource_type/resource_id/from/to、游标 |

没有实现的HTTP不能出现在capabilities为enabled。Task/Agent管理沿用v1已实现接口，A不复制第二套管理接口。

RunStart固定字段：`version_id:UUID, agent_bindings:object, unbound:boolean=false, seed:int32=42, mode:REALTIME|VIRTUAL=REALTIME, max_parallelism:1..4=4, priority:-10..10=0, retry_of_run_id:UUID|null=null, dataset_id:UUID|null=null`。seed范围-2147483648至2147483647，避免JS不精确大整数。retry_of须是同Task同版本终态Run，仅记录关系，不自动复用旧结果。REALTIME为真实等待的模拟，不是真实模型。VIRTUAL仅允许显式TESTDATA_ENABLED、专用`*_test`/`*_lab`库且提供dataset_id；生产/普通开发服务返回409。

RunView固定含原v1全部Run字段以及version_id、workflow_name、version_no、mode、execution_state、queued_at、execution_started_at、execution_ended_at、queue_duration_ms、execution_duration_ms、logical_duration_ms、last_seq、cancel_requested_at、recovery_count、span_count、error_count、progress（完成/已决节点数除总逻辑节点数，0–1）。不公开worker私有token。Run.status仍是RUNNING/SUCCESS/FAILED/CANCELLED，QUEUED不能冒充runs新增状态。

Workflow={workflow_id,name,description,draft,revision,archived_at,created_at,updated_at}；Version={version_id,workflow_id,version_no,definition,definition_hash,created_at}。Overview含total_runs、running_runs、queued_runs、success_runs、failed_runs、cancelled_runs、success_rate、avg/p50/p95_execution_duration_ms、input/output_tokens、total_spans、dataset_counts、recent_runs、aggregate_status。success_rate只以SUCCESS+FAILED为分母；取消单列，队列时长不混入执行耗时；VIRTUAL默认不进入REALTIME统计。

Capabilities固定为{protocol_version:"2.0",features:object,limits:object,scenarios:[enum],algorithm_version,experiment_protocol_version}；features布尔值只有实际已完成才能true。AggregateStatus={snapshot_at:UTC|null,watermark_max_seq:int,stale:boolean,refreshing:boolean}，stale以最新可见终态汇总与MV快照的精确检查判断，不仅比较max序号。

Dataset响应为14表字段完整投影；Experiment为14实验表字段及trial_count/sample_count，phase/progress未可知时null；Trial={trial_id,experiment_id,ordinal,variant,parameters,summary}；Sample={trial_id,repetition,is_warmup,measured_at,metrics,plan,correctness}。metrics固定公共列execution_ms/client_ms/returned_rows/scanned_rows/shared_hit_blocks/shared_read_blocks/local_hit_blocks/temp_read_blocks/index_bytes/insert_ms，适用项为有限数字，不适用null；机制实验可另有extra对象。summary={n,median_ms,p95_ms,iqr_ms,paired_difference_ms,bootstrap_ci95_ms:[low,high]|null,failed_samples}，无测量时相关值null。correctness={passed:boolean,checks:object,result_hash:string|null}。Catalog={tables:[{name,columns,constraints,indexes,size_bytes}],views:[{name,definition}]}；QueryTemplate={code,sql,parameters,index_names,description}。Audit投影14表完整字段，不回显凭据。

## 4. Journal、实时快照与SSE

JournalEvent：`{run_id,seq,producer_event_id,kind,payload,occurred_at,recorded_at}`。B分配seq，严格单Run递增；时间不是排序依据。kind闭集：run.queued、run.started、span.started、span.finished、span.event、link.created、node.skipped、checkpoint.saved、cancel.requested、run.recovering、run.finished。kind与payload通过Schema/共享模型的判别联合校验。

关键payload：

- span.started：完整SpanOpen={span_id,parent_span_id,agent_id,operation_type,span_name,node_key,role_key,attempt_no,start_time,attributes}；node_key/role_key可null仅用于根/角色容器；开始事件不填最终状态和end_time。
- span.finished：`{span_id,status:SUCCESS|ERROR,end_time,input_tokens,output_tokens,provider,model_name,tool_name,error_type,error_message}`；只关闭已开始Span，Token仅LLM允许。其它字段从open合成原SpanData。
- span.event：原EventData结构；每个event_id唯一。link.created={source_span_id,target_span_id,link_type}，方向为“前驱/原尝试→后继/新尝试”；DEPENDS_ON形成DAG，RETRY_OF单独展示不参与定义DAG环判断。
- node.skipped={node_key,reason}。checkpoint.saved={checkpoint_version:1}，实际checkpoint保存在execution元数据，不将256KB检查点逐条发给浏览器。
- run.finished={status,error_summary,projection_complete:boolean,final_seq}，final_seq必须等于本事件seq。

Snapshot：`{run:RunView,seq,nodes:[NodeState],spans:[LiveSpan],links:[Link],event_count,projection_complete}`。NodeState={node_key,state,attempt_no,span_ids:[hex]}；LiveSpan是SpanOpen加state=RUNNING|SUCCESS|ERROR、end_time可null及Span最终字段可null。最多500 Span，响应上限2MiB。v1 SpanData仍只允许闭合SUCCESS/ERROR，不能给v1塞RUNNING。

客户端先GET snapshot获取seq=S，再stream?after_seq=S。B在同一读快照内重建snapshot；后续stream从持久journal读取，不因订阅晚而漏事件。SSE：`id: {seq}`、`event: {kind}`、`data: {JournalEvent JSON}`；默认每500ms批查已提交记录，每15秒发送注释heartbeat。LISTEN/NOTIFY只能作为唤醒优化，不能成为唯一事实源。

重连Last-Event-ID优先于after_seq；若二者都给且不等422。重复seq客户端去重，发现跳号先补journal，不直接画假进度。超出保留窗口410 CURSOR_EXPIRED并重新snapshot；当前默认不清理仍实现该分支。>last_seq的cursor422。收到run.finished后关闭；若从终态最后seq开始订阅，服务器发不带id的stream.end控制事件并关闭。stream.end只表示传输结束，不是持久业务事实。读取错误发stream.error控制事件后关闭并允许重连；HTTP头发出前的错误用统一JSON。

## 5. B/C内部接口与持久化边界

这些是Python内部调用，不开放任意客户端上报Span的HTTP接口。C不能连接数据库或导入B业务服务。

```python
# 公共类型由B依据本文件/Schema实现于 app/contracts/v2/。
def validate_workflow(definition: dict) -> ValidationReport: ...  # C纯函数

async def execute_workflow(*, context: ExecutionContext,
                           sink: ExecutionSink) -> None: ...  # C

class ExecutionSink(Protocol):
    async def commit(self, batch: JournalBatch) -> BatchAck: ...
    async def control(self) -> ControlState: ...

def reduce_journal(*, events: list[dict]) -> SnapshotProjection: ...  # C纯函数
def seal_interrupted(*, events: list[dict], reason: str,
                     ended_at: datetime) -> ClosedProjection: ...  # C纯函数
def analyze_run(*, definition: dict, projection: ClosedProjection,
                algorithm_version: str = "2.0") -> dict: ...  # C纯函数
def compare_runs(*, inputs: list[ComparisonInput]) -> dict: ...  # C纯函数
```

ExecutionContext={run_id,trace_id,definition,definition_hash,config,agent_bindings,lease_epoch,checkpoint,last_seq,clock}。clock为C可注入的RealtimeClock或VirtualClock；B只选择mode、传入恢复上下文，不重复实现模拟算法。

JournalBatch={protocol_version:"2.0",run_id,batch_id,lease_epoch,expected_last_seq,events:[ProducerEvent],checkpoint,terminal:null|{status,error_summary}}。ProducerEvent={producer_event_id,kind,payload,occurred_at}；C仅可产生span.started/finished/event、link.created、node.skipped、checkpoint.saved，系统run.*由B生成。批次至少1条、最多100条，JSON UTF-8<=512KiB，checkpoint<=256KiB。若terminal非null，批次必须使投影完整且根闭合；B在同一事务完成第14文档终态投影。ACK={run_id,batch_id,first_seq,last_seq,duplicate:boolean,terminal_committed:boolean}。

ControlState={cancel_requested:boolean,lease_valid:boolean,deadline_at:UTC,last_seq:int}。续租由B的Worker后台负责；C每次可中断等待最多100ms查询本地Control缓存，B不为每100ms开一次数据库事务。SQL心跳5秒，取消标志数据库检查最多500ms，用户取消到引擎响应目标<=2秒。失租立即停止，不再尝试以旧epoch提交。

cancel.requested等系统日志可能在C两次提交之间推进seq。CHECKPOINT_CONFLICT需返回details.last_seq；Sink核对新增部分只有系统控制事件后可重新基于最新水位提交**同一批业务事件**，不重复执行节点。批次语义hash排除expected_last_seq/lease_epoch及服务器填入的checkpoint.journal_seq；其余内容/事件顺序必须不变。若新增部分含另一批生产者事件，禁止盲目重基，应从已提交checkpoint恢复。旧epoch在任何新写入之前仍先被拒绝。第一次提交的checkpoint.journal_seq填expected_last_seq作为占位，B原子替换为ACK水位；terminal批次的ACK水位包括B追加的run.finished。

SnapshotProjection为{nodes,spans,events,links,closed_result:null|ClosedProjection}；ClosedProjection={spans:[原SpanData],events:[原EventData],links,nodes,final_status,error_summary,time_basis,logical_duration_ms}，spans中node_key/role_key/attempt_no存入attributes，不给v1 SpanData增加字段。两个reducer接口都不操作数据库或产生随机ID；seal所需补充事件/ID必须从run_id、源水位和reason稳定派生。

检查点必含checkpoint_version、definition_hash、clock_mode、logical_time_ms、node_states、attempts、open_spans、completed_span_ids、resolved_routes、journal_seq；写入前由B将journal_seq设为本批最终seq，C提供expected_last_seq而不自行分配seq。恢复只接受hash一致、协议版本支持且与持久水位一致的checkpoint。随机结果按节点/尝试派生，无需序列化不可移植的random内部状态。

恢复时：保留成功且已经提交的逻辑节点；已开始未闭合尝试先记录WorkerLost ERROR，再按预算生成新的attempt_no。不能擦除旧尝试或重复计Token。根/角色容器继续存在直至结束；根墙钟时间包含恢复停顿，分析另列recovery_pause_ms。批次已提交但ACK丢失时，用相同batch/event ID和payload重发；B返回原ACK，C据ACK推进水位，不执行第二次逻辑操作。

## 6. 分析、回放与时间口径

- **时间**：REALTIME Span使用UTC时间，间隔测量由monotonic clock，模拟sleep确实发生；不能只修改显示值。VIRTUAL Span时间使用模拟时钟，可能与主机结束时间不同，只允许专用数据服务；队列/API墙钟和逻辑耗时分别返回，图表禁止混合模式。
- **自耗时**：Span耗时减去与其区间相交的直接子Span区间并集长度，不能减子Span耗时之和；缺失区间返回unavailable，不能随意夹成0掩盖非法数据。
- **关键路径**：在本次实际选中的调度DAG上使用操作节点的inclusive尝试耗时+重试等待作为权重；排除根与角色容器重复计时。按拓扑动态规划O(V+E)得到理论依赖关键路径；调度容量导致的额外等待另列scheduler_wait_ms，**不把理论路径时长等同于实际墙钟**。同时高亮实际长耗时节点和重试链。
- **代价**：retry_overhead_ms为所有失败尝试与退避时间的总和，可因并行大于墙钟，界面标“累计工作量”。scheduler_wait_ms为就绪后因并行度限制等待的节点时间总和，非简单wall减critical_path；C在attributes记录ready_at/attempt_no/retry_delay_ms。recovery_pause_ms采用最后一次已确认日志提交至新Worker恢复开始的可观测间隔并集，是中断估计而非精确CPU停顿，必须在limitations说明。最终运行根/角色包含等待，不据此宣称CPU利用率。
- **回放**：按seq逐条重放真实保存的运行事件，支持0.5/1/2/4倍及拖动到已记录事件；LEGACY只有结束数据，标记“静态轨迹”，不伪造执行过程动画。
- **分析输出**：algorithm_version、journal_seq、time_basis、critical_path{node_keys,duration_ms}、self_times[{span_id,duration_ms}]、retry_overhead_ms、scheduler_wait_ms、recovery_pause_ms、findings[{code,severity,node_keys,evidence,explanation}]、limitations。
- **稳健异常**：同版本同节点至少20次终态可比较样本，median/MAD，MAD=0时采用显式绝对阈值；未够样本返回INSUFFICIENT_BASELINE。仅说明统计异常，不声称因果根因。
- **比较输出**：run_ids、version_id、time_basis、summary_rows、node_rows[{node_key,per_run:[{run_id,state,attempt_count,duration_ms,input_tokens,output_tokens}]}]、deltas；缺失分支为SKIPPED/null，分母0的相对变化为null。

## 7. 数据集、导出与执行记录

数据集登记请求={name,purpose,seed,config,generator_version}，201返回BUILDING manifest。purpose BENCHMARK/LOAD仅在专用实验服务开放。C生成工具调用登记API取得dataset_id，再通过B提供的隔离Loader适配器或业务API生成，最后用`POST /datasets/{id}/finalize`提交`{actual_counts,content_hash}`；该路径同样登记在manifest。B重新查询真实计数和抽样摘要，匹配才置READY；失败FAILED并保留原因。客户端报告不能作为唯一真实性证据。

内容摘要基于生成器版本、seed、标准化逻辑记录，排除随机UUID/墙钟时间；manifest另存真实资源ID与校验SQL。相同seed结构一致不要求UUID相同。DEMO只使用业务API且不清空旧数据，BENCHMARK允许受控COPY至隔离实验schema，LOAD必须经过真实HTTP执行链路；报告明确三种路径，不能互相替代。

JSON导出包括协议版本、数据集、环境、参数、全部样本、计划和正确性检查，CSV按trial/repetition展开。HTTP以流式响应输出，最多50MiB，超限返回422并提供分页下载说明；不把API密钥、连接字符串、Prompt或数据库密码写入报告。
