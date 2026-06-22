# AInstein 系统架构设计

> 本文档描述 AInstein（硅基大脑）当前实际架构。系统已从早期"科学家/主任/研究员 + 三轮研究引擎"，演进为 **事件驱动、去层级化、博弈共识、自我调节** 的多智能体认知系统（v3.1+）。
>
> 配套阅读：[docs/ops-manual.md](./ops-manual.md)、[docs/testing.md](./testing.md)、[docs/user-manual.md](./user-manual.md)。

---

## 1. 系统概览

### 1.1 设计目标

**硅基大脑**是一个从「种子问题」出发自主思考的认知系统。用户提交一个问题（`brains.seed_question`），系统启动一个独立大脑实例：

- 多个不同视角的 Agent 自发涌现思考；
- 通过博弈、矛盾检测、共识形成，逐步演化出认知图谱；
- 当达到收敛条件时自动结束并产出总结、论文，最终精华上报**创世主脑**汇入更大的认知洪流。

它不是 chatbot，也不是研究助手——它是「在线运行的思考过程」。

### 1.2 核心理念

| 理念 | 含义 |
| --- | --- |
| **认知经济学** | 大部分 Agent 锚定「解题」（生物体不浪费能量隐喻）；发散思考由极少数 explorer 承担，且配额受限 |
| **涌现智能** | 单个 LLM 调用只是计算单元，不具备独立智能；智能从多角色思维链交织中涌现 |
| **博弈驱动** | 任何观点（包括工具调用提案）都是可被质疑、可被博弈的认知元素；裁决由加权投票而非中央调度 |
| **事件驱动** | 大脑没有预设流程，所有思考由事件总线触发；下一步取决于此刻图谱状态 |
| **自我调节** | 大脑能感知自身偏差（积压、过度共识、发散）并主动纠偏，而非被外部硬约束 |
| **客观可追溯** | 所有产出落库为 CE / CR，可重放、可审计、可证伪 |

### 1.3 关键模块体量

| 模块 | 职责 |
| --- | --- |
| [orchestrator.py](../orchestrator.py) | ATA 编排器：事件订阅 → 调度 → frontier → 收敛检查 → 自调节 |
| [agents/framework.py](../agents/framework.py) | Agent 基类、6 角色定义、AgentPool |
| [deliberation.py](../deliberation.py) | 博弈引擎（5 步流程，三轨模式） |
| [observer.py](../observer.py) | 上帝视角叙事（不参与博弈） |
| [cognitive.py](../cognitive.py) | CE / CR CRUD、置信度更新、frontier 计算、状态机 |
| [event_bus.py](../event_bus.py) | 单例事件总线（同步分发 + DB 持久化） |
| [database.py](../database.py) | SQLite Schema + DAO |
| [master_brain_tactics.py](../master_brain_tactics.py) | 创世主脑战术：内博弈 / 跨域综合 / 元认知反思 |
| [app.py](../app.py) | Flask 路由（~52 端点） |
| [wsgi.py](../wsgi.py) | Gunicorn 入口 + 文件锁 + ATA 启动 + 主脑初始化 |

---

## 2. 整体架构

```
┌────────────────────────────────────────────────────────────────┐
│  用户层                                                          │
│  React + Vite 前端 (frontend/)                                  │
│   Login / Dashboard / BrainList / CreateBrain                   │
│   BrainView (D3 力导向) / BigScreen (态势大屏 Canvas)          │
│   ObserverPanel / ProjectDetail (兼容层)                        │
└────────────────────────────────────────────────────────────────┘
                              ▲
                              │ JSON over HTTPS (Bearer Token)
                              ▼
┌────────────────────────────────────────────────────────────────┐
│  Web 层                                                          │
│  app.py (Flask)         鉴权 / 路由 / 调度入口                   │
│  auth.py                JWT + bcrypt + 强密码校验                │
│  wsgi.py                Gunicorn 入口 + flock + ATA 启动        │
└────────────────────────────────────────────────────────────────┘
                              ▲
                              │ Python 调用
                              ▼
┌────────────────────────────────────────────────────────────────┐
│  认知层                                                          │
│  orchestrator.py        ATA 编排器：brain_loop / 自调节闭环      │
│  master_brain_tactics   主脑三大战术（内博弈/跨域/元认知）       │
│  agents/framework.py    6 角色 + BaseAgent + AgentPool          │
│  deliberation.py        三轨博弈引擎（5 步流程）                 │
│  observer.py            上帝视角叙事（不参与博弈）              │
│  tools/                 11 工具 + 工具博弈分发                   │
└────────────────────────────────────────────────────────────────┘
                              ▲
                              │ create_element / publish / vote
                              ▼
┌────────────────────────────────────────────────────────────────┐
│  知识层                                                          │
│  cognitive.py           认知元素 / 关系 CRUD + 状态机            │
│  event_bus.py           事件总线（单例 + 同步分发）              │
│  database.py            SQLite WAL                               │
└────────────────────────────────────────────────────────────────┘
                              ▲
                              │ 收敛 / 终止 触发
                              ▼
┌────────────────────────────────────────────────────────────────┐
│  生成层                                                          │
│  brain_summary.py       思考总结卡片（默认折叠）                 │
│  paper_generator.py     PDF 论文（WeasyPrint + Noto CJK）        │
│  → 自动上报创世主脑                                              │
└────────────────────────────────────────────────────────────────┘
```

模块间唯一耦合点：**`event_bus.EventBus` 单例 + `database` 持久化**。Agent、博弈引擎、观察员、工具系统之间无直接依赖。

---

## 3. ATA 编排器（orchestrator.py）

ATA = **A**gent-**t**o-**A**gent。编排器是硅基大脑的「**心跳**」与「**神经递质**」系统：它不亲自思考，也不命令任何 Agent，只是监听事件、唤醒大脑循环、判定何时博弈、节律控制休眠。

### 3.1 主循环 `_brain_loop`

```
while running:
  1) 状态检查（idle/paused/stopped → 跳过 / 退出）
  2) 兜底终止检查（_check_fallback_trigger）
       CE 总数 ≥ 500 或 运行时长 ≥ 3600s → _force_synthesizer_conclusion
  3) 主轨收敛检查（_check_convergence）
       synthesizer 产出 conclusion 且 confidence ≥ 0.75 → 停止大脑
  4) _think_cycle:
     a. 事件队列消费（最多 5 个/轮）
     b. 收敛压力评估（_check_convergence_pressure）
     c. 异质性刺激评估（_should_inject_heterogeneous_stimulus）
     d. 已知问题优先解决（_follow_up_open_question, ratio>0.20）
     e. force_synthesis 脉冲（若已积累足够 CE 仍未综合）
     f. frontier 探索（无事件时）
     g. 矛盾扫描 → 自动博弈
     h. 综合博弈扫描（收敛模式下）
  5) cycle_count++
  6) 周期性置信度传播（每 10 轮）
  7) wake.wait(backoff) → 被事件唤醒或超时（指数退避 1s → 60s）
```

每个大脑一个 daemon 线程；编排器是**进程内单例**。事件来自 EventBus（同步分发）的发布器线程，处理器只做轻量入队 + 唤醒。

### 3.2 事件类型与默认派遣角色

事件类型完整定义在 [event_bus.EventTypes](../event_bus.py)，编排器订阅以下关键事件，由 `_EVENT_TO_ROLES` 决定默认派给谁：

| 事件 | 含义 | 默认派遣角色 |
| --- | --- | --- |
| `USER_SEED_QUESTION_SUBMITTED` | 用户提交种子问题 | `investigator`, `explorer` |
| `CE_OBSERVATION_CREATED` | 观察 CE 落库 | `explorer`, `investigator` |
| `CE_QUESTION_RAISED` | 新问题被提出 | `investigator`, `reasoner` |
| `CE_HYPOTHESIS_PROPOSED` | 新假设提出 | `investigator`, `critic` |
| `CE_EVIDENCE_COLLECTED` | 收集到证据/反证 | `reasoner`, `critic` |
| `CE_HYPOTHESIS_SATURATED` | 假设证据饱和 | `reasoner` |
| `CE_CONCLUSION_PROPOSED` | 结论被提出 | `critic`, `synthesizer` |
| `CE_CONSENSUS_REACHED` | 博弈共识 | `synthesizer`, `observer` |
| `CE_DISSENT_DETECTED` | 博弈分歧 | `critic`, `synthesizer` |
| `CE_INSIGHT_EMERGED` | 涌现洞察 | `synthesizer`, `observer` |
| `CE_CHALLENGED` | CE 被质疑 | `critic` |
| `DELIBERATION_CONCLUDED` | 博弈结束 | `synthesizer` |
| `DELIBERATION_REQUESTED` | 请求发起博弈 | （编排器代理执行） |
| `BRAIN_CREATED` | 大脑创建 | （初始化 Agent 池） |

### 3.3 idle 派遣优先级

无事件、且未触发收敛模式时，编排器从 frontier 拉一个低置信度元素让 Agent 思考：

```python
_IDLE_ROLE_PRIORITY = ["investigator", "reasoner", "explorer"]
```

`investigator > reasoner > explorer`：永远先派解题导向角色，找不到才退到 explorer。这是认知经济学原则的代码体现——**发散是奢侈品**。

### 3.4 收敛模式下的角色切换

`_check_convergence_pressure` 返回 `converge` 或 `force_synthesis` 时，frontier 探索改用：

```python
_CONVERGENCE_MODE_ROLES = ["reasoner", "synthesizer", "critic"]
```

并且伪事件类型由 `CE_QUESTION_RAISED`（探索语义）切换为 `CE_HYPOTHESIS_SATURATED`（推理整合语义），prompt 同时指示 LLM「不要产生新的问题或假设，请整合现有 CE」。

### 3.5 跨进程状态同步

Gunicorn 多 worker 部署下，每个 worker 是独立 Python 进程，内存中的 `BrainState` 不共享。但实际只有持有调度锁的那一个 worker（`flock /tmp/ainstein-scheduler.lock`）会运行 ATA 编排器：

- **大脑实际只在 1 个 worker 进程中运行**；
- 其它 worker 通过查询 DB 获取最新状态；
- 暂停/恢复请求由收到请求的 worker 通过 `ATAOrchestrator.instance()` 操作——但只有持锁 worker 真正持有 `BrainState`。

> 这是当前架构的已知限制，详见 [ops-manual.md](./ops-manual.md) 的"多 worker 状态同步"章节。

---

## 4. 自调节闭环（v3.1+）

大脑现在拥有完整的**自我调节系统**——像生物体一样，能感知自己的认知偏差并主动纠正。

### 4.1 三大调节维度

| 偏差信号 | 调节机制 | 触发位置 |
| --- | --- | --- |
| 积压问题太多 | 已知问题优先解决 | `_follow_up_open_question` |
| 共识太顺、无人反对 | 异质性刺激 | `_inject_heterogeneous_stimulus` |
| 发散过多 / 长时间不综合 | 收敛压力 / 强制综合脉冲 | `_check_convergence_pressure`, `_force_synthesis_pulse` |

### 4.2 已知问题优先解决（Question Resolution Priority）

**问题**：纯探索倾向下 explorer 一直产新 question，老 question 永远被搁置。

**机制**：

```python
_QUESTION_RESOLVE_PRIORITY_RATIO = 0.20   # open question 占总 CE > 20% 触发
_QUESTION_RESOLVE_PROBABILITY    = 0.6    # 触发后该轮派 agent 解答的概率
_QUESTION_RESOLVE_COOLDOWN       = 300    # 同一 question 被分派后冷却 5 分钟
```

```
每轮 think_cycle:
  open_q_ratio = _get_open_question_ratio(brain_id)
  if open_q_ratio > 0.20 and random < 0.6:
      → 选最老的 open question
      → 强制派 investigator/reasoner 去回答（不是再产新 question）
      → 答完后 _check_question_resolution 判定该 question 是否进入 confirmed
```

### 4.3 共识饱和检测 + 异质性刺激

**问题**：如果最近所有 CE 都是 consensus、没有 dissent，大脑会陷入"思维平庸"——所有人都同意，没人提反对。

**机制**：

```python
_CONSENSUS_SATURATION_WINDOW       = 15     # 检测窗口：最近 15 个 CE
_CONSENSUS_SATURATION_THRESHOLD    = 0.5    # window 内 consensus 占比阈值
_DISSENT_DROUGHT_THRESHOLD         = 0      # 同时 dissent ≤ 0
_HETEROGENEOUS_STIMULUS_COOLDOWN   = 600    # 同一大脑 10 分钟内只触发一次
```

触发条件同时满足：
1. 最近 15 个 CE 中 consensus 占比 ≥ 50%；
2. 同窗口内 dissent ≤ 0；
3. 距上次刺激 ≥ 10 分钟。

触发动作：
- **派 explorer** 用 prompt"请引入一个迄今未被讨论的全新变量或视角"；
- **派 critic** 用 prompt"请扮演魔鬼代言人，对当前共识找出最致命的反例"。

### 4.4 收敛压力机制

`_check_convergence_pressure` 返回 3 种模式：

| 模式 | 触发条件 | 行为 |
| --- | --- | --- |
| `explore` | 默认状态 | 正常派遣 investigator/explorer |
| `converge` | 探索/收敛比 > 5.0 **或** open question 占比 > 30% | 切换到 `_CONVERGENCE_MODE_ROLES`，暂停 explorer |
| `force_synthesis` | 距上次综合已积累 ≥ 20 个 CE | 在 frontier 探索前先插入综合脉冲 |

`_force_synthesis_pulse`：构造伪 `CE_HYPOTHESIS_SATURATED` 事件直接派给 synthesizer，prompt 强制要求"基于现有 CE 整合一个推论或结论"。

### 4.5 双模式收敛机制（Fast / Deep）

系统支持两种思考模式，由 `brain.config.mode` 字段控制（`'fast' | 'deep'`，默认 `deep`）：

| 模式 | CE 上限 | 置信阈值 | 最大时长 | force_synthesis 间隔 | synthesizer 最小 CE |
| --- | --- | --- | --- | --- | --- |
| **快思考（fast）** | 20 | 0.75 | 300s | 8 CE | 10 |
| **深度思考（deep，默认）** | 50 | 0.9 | 3600s | 20 CE | 30 |

阈值集中定义于 [orchestrator/constants.py](../orchestrator/constants.py)：

- **深度模式常量**：`_CONVERGENCE_CONFIDENCE_THRESHOLD = 0.9`、`_CONVERGENCE_MIN_CE_COUNT = 50`、`_FALLBACK_DURATION_SECONDS = 3600`、`_FORCED_SYNTHESIS_INTERVAL = 20`、`_SYNTHESIZER_MIN_CE_DISPATCH = 30`
- **快思考常量（`_FAST_MODE_*`）**：`_FAST_MODE_CE_LIMIT = 20`、`_FAST_MODE_CONFIDENCE_THRESHOLD = 0.75`、`_FAST_MODE_MAX_DURATION = 300`、`_FAST_MODE_FORCE_SYNTHESIS_GAP = 8`、`_FAST_MODE_SYNTHESIZER_MIN = 10`、`_FAST_MODE_FALLBACK_CE = 30`、`_FAST_MODE_MIN_CE_FOR_CONVERGENCE = 5`

切换点：

- `core.py._check_convergence`：根据 `brain.config.mode` 选用主轨置信阈值与最小 CE 门槛；
- `strategy.py._check_convergence_pressure`：根据模式调整 `_FORCED_SYNTHESIS_INTERVAL`、synthesizer 最小派遣门槛；
- 双轨终止的兜底参数（`_FALLBACK_CE_COUNT` / `_FALLBACK_DURATION_SECONDS`）在快思考下分别替换为 `_FAST_MODE_FALLBACK_CE` / `_FAST_MODE_MAX_DURATION`。

> 设计意图：让用户在「快速验证」与「严谨产出」之间显式选择，避免单一阈值在不同问题域下都不合适。

### 4.6 双轨终止策略

| 轨道 | 触发条件（深度模式） | 触发条件（快思考） | 动作 |
| --- | --- | --- | --- |
| **主轨** | synthesizer 产出 `conclusion` 且 `confidence ≥ 0.9`，且 CE 总数 ≥ 50 | `confidence ≥ 0.75`，且 CE 总数 ≥ 5 | 自动停止（state=completed） → brain_summary → paper_generator → 上报主脑 |
| **兜底轨** | CE 总数 ≥ 500 **或** 运行时长 ≥ 3600s | CE 总数 ≥ 30 **或** 运行时长 ≥ 300s | `_force_synthesizer_conclusion`（一次性，`fallback_triggered` 标志位） |

兜底轨适配开放性、哲学性问题——这类问题难以达到主轨高置信度，但也不能让大脑无限思考。

---

## 5. Agent 角色体系

### 5.1 6 个功能性角色

完整定义见 [agents/framework.py](../agents/framework.py) 的 `ROLES`。

| role_key | 思考偏好 | 偏好产出 CE | 默认配额 (min/max) | 是否参与博弈 |
| --- | --- | --- | --- | --- |
| `explorer` | 好奇心驱动，发散思维，擅长"为什么"和"如果..." | question, observation, hypothesis | 1/2 | ✅ |
| `investigator` | 严谨求证，偏向工具使用与数据收集 | evidence, counter_evidence, observation | 1/4 | ✅ |
| `reasoner` | 逻辑优先，注重因果链与论证完整性 | inference, argument, conclusion | 1/3 | ✅ |
| `critic` | 怀疑论倾向，寻找反例和逻辑漏洞 | counter_evidence, dissent | 1/2 | ✅ |
| `synthesizer` | 全局视角，**终局思维**，整合 CE 为完整回答 | insight, perspective, consensus, conclusion | 0/1 | ✅ |
| `observer` | 元认知视角，关注思考过程而非内容 | insight | 1/1 | ❌ |

### 5.2 角色 = 视角，不是层级

- 所有 Agent 完全平等；角色仅是「思维偏好」标签。
- 同一角色可有多个不同性格的 Instance（性格向量影响发言基调），从而在博弈中产生思维多样性。
- Agent 可被动态 `spawn` / `despawn` / `transform_role`。

### 5.3 BaseAgent 核心能力

```python
class BaseAgent:
    def think(context: ThinkingContext) -> ThinkingResult: ...
    def react_to_event(event: dict) -> Optional[ThinkingResult]: ...
    def participate_in_deliberation(deliberation_id, round_index) -> dict: ...
```

`react_to_event` 流程：

1. 从事件构造 `ThinkingContext`（自动注入 `brains.seed_question` 作为 `research_topic`）；
2. 调用 `think` → LLM 输出 JSON：`{new_elements, new_relations, suggested_events, deliberation_request, tool_proposal}`；
3. `_persist_result` 落库 CE / CR、发布事件、记录原始 LLM 文本；
4. 若 `tool_proposal` 非空，由 orchestrator 接管轻量级博弈与执行（详见 §7）。

### 5.4 Agent 池与配额

[AgentPool](../agents/framework.py) 是单例，按 `brain_id` 隔离：

- `spawn(brain_id, role)`：受 `roles.default_quota_max` 限制；
- `despawn(instance_id)`：标记 `agent_instances.status = 'despawned'`；
- `transform_role(instance_id, new_role)`：动态切换角色（发布 `AGENT_ROLE_CHANGED`）。

启动大脑时默认 spawn `explorer`、`investigator`、`critic`（保证至少 3 种视角）。其他角色按需在 `_dispatch_to_agent` / `_pick_or_spawn` 中动态 spawn。

---

## 6. 三轨博弈引擎（deliberation.py）

博弈是硅基大脑判定矛盾、形成共识的唯一裁决机制。v3 起，博弈引擎拥有三种模式，对应思维的三种姿态。

### 6.1 三种博弈模式

| 类型 | 触发条件 | 思维姿态 | 产出 CE |
| --- | --- | --- | --- |
| **推翻式** | `_scan_and_trigger_deliberation` 检测到 `contradicts / refutes` 关系 | 否定与质疑 | dissent / consensus（取决投票） |
| **建设性综合** | `_scan_and_trigger_synthesis_deliberation` 找到关系密集的 CE 簇（≥3 成员）| 整合与提炼 | insight / consensus |
| **建设性确认** | 高置信度 CE 已有充分证据但尚未被「正式」共识 | 正式承认 | consensus（目标 CE 进入 confirmed）|

### 6.2 5 步流程

```
1. initiate        创建 deliberation 行 + 选 3-5 名参与者 + 发出 DELIBERATION_REQUESTED
2. run_turn        每轮内每参与者依序发言；最多 3 轮（DEFAULT_MAX_ROUNDS）
3. collect_votes   每位 Agent 最后一轮的 stance → 投票 (agree/disagree/abstain)
                   权重 = agent_instances.weight
4. judge_consensus 加权赞成比 → 判定 outcome
5. conclude        生成 consensus / perspective / dissent CE，写终态，发 DELIBERATION_CONCLUDED
```

### 6.3 加权裁决

```python
DEFAULT_CONSENSUS_THRESHOLD = 0.6   # 加权赞成比 ≥0.6 且 agree 人数 ≥2 → consensus
DEFAULT_MAJORITY_THRESHOLD  = 0.5   # 0.5-0.6 区间 → majority（求同存异）
# 否则 → dissent

agree_ratio = weights["agree"] / (weights["agree"] + weights["disagree"])
if agree_ratio >= 0.6 and counts["agree"] >= 2:
    outcome = "consensus"
elif agree_ratio >= 0.5 and counts["agree"] > counts["disagree"]:
    outcome = "majority"
else:
    outcome = "dissent"
```

> 阈值由历史 0.667 调整为 **0.6**，缓解早期 dissent/consensus 严重失衡问题。

### 6.4 角色议题偏好

并非所有角色都适合参与所有议题。`_ROLE_PREFERRED_CE` 决定 initiate 阶段优先选谁：

| 角色 | 偏好 CE 类型 |
| --- | --- |
| explorer | observation / question / hypothesis |
| investigator | hypothesis / evidence / counter_evidence |
| reasoner | evidence / inference / argument / conclusion |
| critic | conclusion / consensus / perspective / argument |
| synthesizer | conclusion / perspective / insight |
| observer | （不参与） |

### 6.5 自动博弈触发条件

`_scan_and_trigger_deliberation` 每轮 think_cycle 扫描最近 ~30 个 CE：

- 出现 `contradicts` 或 `refutes` 关系；
- 目标 CE 类型属于 `{hypothesis, conclusion, perspective, counter_evidence, dissent}`；
- 没有正在进行的活跃博弈（DB 唯一索引 `uniq_active_deliberation` + 内存去重）。

每轮至多触发一场博弈，避免风暴。

---

## 7. 工具博弈机制（tool_proposal）

工具调用在 AInstein 中被设计为**可博弈的认知元素**，而不是传统 tool-use loop 的硬编码循环。

### 7.1 与传统 tool-use 的本质区别

| 传统 tool-use loop | AInstein tool_proposal |
| --- | --- |
| LLM 直接调用工具 | LLM **提议**调用工具，作为 `inference` CE 落库 |
| 工具结果直接返回给该 LLM | 工具结果作为 `evidence` CE 注入图谱，所有 Agent 可见 |
| 单 Agent 决策 | 多 Agent 轻量级投票 |
| 不可回溯 | 完整审计链：提议 CE → 投票 → 执行 → evidence CE，由 `derives_from` 关系串联 |

### 7.2 流程

```
1. Agent.think 输出 tool_proposal 字段（可选，prompt JSON Schema 显式声明）
   {"tool": "web_search", "params": {...}, "reason": "..."}
2. orchestrator._handle_tool_proposal:
   a. 落库为 inference CE，payload.tool_status = "pending_vote"
   b. 轻量级博弈：从非 observer Agent 中随机选 ≤2 个投票（LLM "support"/"oppose"）
      majority ≥1 通过；无 voter 时默认通过
   c. 通过 → tools.registry.dispatch(tool_name, params)
      → 落库为 evidence CE
      → 建立 derives_from 关系：evidence CE → 提议 CE
      → payload.tool_status = "executed"
   d. 否决 → payload.tool_status = "rejected"，提议 CE 仍保留可追溯
```

### 7.3 已注册工具（11 个）

| 类别 | 工具名 | 说明 |
| --- | --- | --- |
| 外部数据 | `web_search` | DuckDuckGo |
| | `wikipedia_search` | Wikipedia API |
| | `arxiv_search` | arXiv 论文检索（含防御性超时封装） |
| | `google_trends` | 趋势查询 |
| 统计分析 | `descriptive_stats` | 描述性统计 |
| | `correlation` | Pearson/Spearman |
| | `t_test` | 独立 t 检验 |
| | `regression` | 多元线性回归 |
| | `anomaly_detection` | z-score / IQR |
| | `distribution_fit` | 正态性检验（Shapiro） |
| | `group_stats` | 分组聚合 |

> ⚠️ **关键约束**：要让 Agent 真正能产出 `tool_proposal`，必须在 `roles.prompt_template` 的 JSON Schema 输出格式中**显式声明** `tool_proposal` 字段；否则 LLM 不会触发该能力。

### 7.4 元认知信号 `tool_gap`

当 Agent 调查时发现"我想知道某事，但所有现有工具都做不到"，可以产出 `tool_gap` 类型的 CE，作为元认知信号被沉淀，用于未来工具生态规划。

---

## 8. CE 体系（cognitive.py）

### 8.1 13 种类型

```
observation, question, hypothesis, evidence, counter_evidence,
inference, argument, conclusion, perspective, insight,
consensus, dissent, tool_gap
```

### 8.2 状态机

```
open           初始状态
testing        正在被验证
at_risk        受到反证挑战
contested      博弈分歧（dissent 后置）
refuted        被证伪
confirmed      被确认（≥2 evidence 支持，或博弈共识）
superseded     被新版本取代
```

### 8.3 状态迁移

- 博弈结束自动迁移：`consensus` → 目标 CE `confirmed`；`dissent` → `contested`；
- 收到 ≥2 条 `evidence` 的 hypothesis 自动 `confirmed`；
- 收到 `counter_evidence` 的 hypothesis 自动 `refuted` 或 `at_risk`；
- `refuted` / `contested` 的 CE 收到新 evidence 可通过 `cognitive.reactivate_element` 重新 `open`，触发新一轮博弈。

### 8.4 置信度贝叶斯更新

`cognitive.update_confidence(element_id, new_confidence, reason)`：

- 裁剪到 `[0, 1]`；
- 历史变更追加到 `payload.confidence_history`；
- `version` 自增（乐观锁简化版）。

`_propagate_confidence`（每 10 cycle 一次）按出边关系传播：

- `supports` 提升下游置信度；
- `refutes` 降低下游置信度；
- `derives_from` 同步父 CE 状态变化。

---

## 9. 事件总线（event_bus.py）

### 9.1 设计

- **单例 EventBus**，进程内唯一实例；
- 同步分发：发布事件 → 调用所有订阅者 → 持久化到 `events` 表；
- 处理器（如 ATA 编排器）只做**轻量入队 + 唤醒**，避免阻塞发布线程。

### 9.2 幂等消费

每个事件被一个 Agent 消费时，写入 `event_consumption(event_id, agent_instance_id)` 联合主键，保证同一事件不会被同一 Agent 重复消费。

---

## 10. 创世主脑（master_brain_tactics.py）

### 10.1 全局唯一性

主脑在数据库中是 `brains.id = 1`，由 `wsgi.py` 启动时检查并初始化：

```python
ensure_master_brain_exists()
# 不存在 → 创建主脑（owner_user_id = admin, name = '创世主脑'）
# 存在但未启动 → ATAOrchestrator.start_brain(MASTER_BRAIN_ID)
```

主脑**永不消亡**，归属管理员，不可删除、不可复制。

### 10.2 自动上报

任何分支大脑收敛终止（主轨或兜底轨）时：

```python
# brain_summary 生成后
精华CE = SELECT * FROM cognitive_elements
         WHERE brain_id = <branch>
           AND type IN ('conclusion', 'consensus', 'insight')
           AND confidence > 0.7

→ 整体 INSERT INTO cognitive_elements WHERE brain_id = MASTER_BRAIN_ID
→ 发布 CE_OBSERVATION_CREATED 等事件唤醒主脑
```

### 10.3 三大战术

| 战术 | 触发 | 动作 |
| --- | --- | --- |
| **主脑内博弈** | 检测到来自不同分支的 conclusion 存在 `contradicts` 关系 | 召集主脑级 deliberation 辩证审视 |
| **跨域综合** | 跨越 ≥2 个 `domain_tags` 的 CE 在主脑中聚集 | 派 synthesizer 寻找潜在共振 |
| **元认知反思** | 周期性触发 | 审视分支大脑的思维模式（"我们集体在以怎样的方式思考？"） |

### 10.4 多维节流

主脑使用 **cooldown-based** 节流，每个战术独立冷却时间，避免每个事件都触发完整战术循环——让主脑像生物一样平稳呼吸而非爆发性输出。

---

## 11. 数据模型

完整 Schema 见 [database.py](../database.py)（SQLite WAL 模式）。

### 11.1 brains

```sql
CREATE TABLE brains (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    seed_question TEXT NOT NULL,            -- 用户提交的种子问题
    owner_user_id INTEGER NOT NULL,
    state TEXT NOT NULL DEFAULT 'gestating',-- gestating/active/thinking/paused/completed/archived
    config_json TEXT DEFAULT '{}',
    frontier_score REAL DEFAULT 0.0,
    started_at TEXT,
    last_active_at TEXT,
    legacy_project_id INTEGER                -- 对接旧 projects 表
);
```

> ⚠️ 状态字段名是 **`state`** 而非 `status`。

### 11.2 cognitive_elements

```sql
CREATE TABLE cognitive_elements (
    id INTEGER PRIMARY KEY,
    brain_id INTEGER NOT NULL,
    type TEXT NOT NULL,                      -- 13 种 CE 类型之一
    content TEXT NOT NULL,
    payload_json TEXT DEFAULT '{}',          -- title / metadata / confidence_history / tool_status
    confidence REAL NOT NULL DEFAULT 0.5,
    confidence_method TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    version INTEGER NOT NULL DEFAULT 1,
    superseded_by INTEGER,
    domain_tags TEXT DEFAULT '[]',
    created_by_agent_id INTEGER,
    source_session_id INTEGER,
    created_at TEXT, updated_at TEXT
);
```

### 11.3 cognitive_relations

```sql
CREATE TABLE cognitive_relations (
    id INTEGER PRIMARY KEY,
    brain_id INTEGER NOT NULL,
    src_id INTEGER NOT NULL,
    dst_id INTEGER NOT NULL,
    relation TEXT NOT NULL,                  -- supports/refutes/contradicts/derives_from/...
    strength REAL NOT NULL DEFAULT 0.5,
    created_by_agent_id INTEGER,
    UNIQUE(src_id, dst_id, relation)
);
```

> ⚠️ 关系字段名是 **`relation`**，不是 `relation_type`。

### 11.4 agent_instances

```sql
CREATE TABLE agent_instances (
    id INTEGER PRIMARY KEY,
    brain_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    role_key TEXT NOT NULL,                  -- ⚠️ 字段名是 role_key 不是 role
    personality_json TEXT DEFAULT '{}',
    private_memory_json TEXT DEFAULT '[]',
    quality_score REAL DEFAULT 0.5,
    weight REAL DEFAULT 1.0,                 -- 投票权重
    status TEXT NOT NULL DEFAULT 'active',
    spawned_at TEXT, despawned_at TEXT
);
```

### 11.5 roles

```sql
CREATE TABLE roles (
    id INTEGER PRIMARY KEY,
    role_key TEXT NOT NULL UNIQUE,
    description TEXT,
    prompt_template TEXT NOT NULL,           -- 角色 system prompt（含 tool_proposal Schema）
    default_quota_min INTEGER DEFAULT 0,
    default_quota_max INTEGER DEFAULT 4
);
```

### 11.6 deliberations / deliberation_turns / deliberation_votes

```sql
CREATE TABLE deliberations (
    id INTEGER PRIMARY KEY,
    brain_id INTEGER NOT NULL,
    target_ce_id INTEGER NOT NULL,
    motion TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'opened',   -- opened/running/resolved
    outcome TEXT,                             -- consensus/majority/dissent
    rounds_total INTEGER DEFAULT 0,
    consensus_ce_id INTEGER,
    dissent_ce_id INTEGER,
    started_at TEXT, resolved_at TEXT
);
CREATE UNIQUE INDEX uniq_active_deliberation
    ON deliberations(target_ce_id) WHERE status != 'resolved';

CREATE TABLE deliberation_turns (
    id INTEGER PRIMARY KEY,
    deliberation_id INTEGER, agent_instance_id INTEGER,
    round_index INTEGER, stance TEXT, speech TEXT,
    cited_ce_ids TEXT, proposed_action TEXT
);

CREATE TABLE deliberation_votes (
    id INTEGER PRIMARY KEY,
    deliberation_id INTEGER, agent_instance_id INTEGER,
    vote TEXT, weight REAL,
    UNIQUE(deliberation_id, agent_instance_id)
);
```

### 11.7 events / event_consumption

```sql
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,           -- UUID
    brain_id INTEGER,
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    retry_count INTEGER, consumed_at TEXT
);

CREATE TABLE event_consumption (
    event_id TEXT NOT NULL,
    agent_instance_id INTEGER NOT NULL,
    PRIMARY KEY (event_id, agent_instance_id)
);
```

### 11.8 observer_logs / brain_snapshots

```sql
CREATE TABLE observer_logs (
    id INTEGER PRIMARY KEY,
    brain_id INTEGER, kind TEXT, title TEXT,
    body TEXT,                                -- JSON 文本，承载完整结构化叙事
    cited_ce_ids TEXT, pushed INTEGER
);

CREATE TABLE brain_snapshots (
    id INTEGER PRIMARY KEY,
    brain_id INTEGER, frontier_score REAL,
    ce_count INTEGER, relation_count INTEGER,
    active_agents INTEGER, metrics_json TEXT
);
```

### 11.9 users（鉴权）

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE, email TEXT UNIQUE,
    password_hash TEXT,                       -- bcrypt
    role TEXT DEFAULT 'user', status TEXT DEFAULT 'active'
);
```

强密码要求（前后端双重校验）：8 位 + 大小写字母 + 数字 + 特殊字符。

### 11.10 兼容层

旧版 7 张表（projects / scientist_directives / research_queue / research_sessions / research_findings / director_memory / datasets）仍保留并由 [agents/director.py](../agents/director.py) / [agents/researcher.py](../agents/researcher.py) / [agents/scientist.py](../agents/scientist.py) + APScheduler 驱动，通过 `brains.legacy_project_id` 与新架构对接。新功能均使用 silicon_brain schema。

---

## 12. 部署架构

```
                        ┌──────────────┐
   外部访问 (HTTPS) ──▶ │  Nginx       │  /ainstein/      → 静态文件 (frontend/dist)
                        │              │  /ainstein/api/  → proxy_pass http://gunicorn
                        │              │  client_max_body_size 50M
                        └──────┬───────┘
                               │
                               ▼
                        ┌──────────────┐
                        │  Gunicorn    │  -w 2 -b 127.0.0.1:9089 --timeout 300
                        │   (systemd)  │  入口：wsgi:application
                        └──────┬───────┘
                               │
                  ┌────────────┴────────────┐
                  ▼                          ▼
            ┌─────────┐                ┌─────────┐
            │ Worker 0│                │ Worker 1│
            │ (持锁)  │                │         │
            │ ATA✓    │                │ ATA✗    │
            │ Sched✓  │                │ Sched✗  │
            └────┬────┘                └────┬────┘
                 │                          │
                 └────────────┬─────────────┘
                              ▼
                        ┌──────────────┐
                        │  SQLite WAL  │  /opt/ainstein/data/ainstein.db
                        └──────────────┘
```

### 12.1 关键组件

| 组件 | 配置 |
| --- | --- |
| OS | Ubuntu 22.04 |
| Nginx | 静态文件 + 反代 + 50M body limit |
| Gunicorn | systemd 启动；2 workers；timeout 300s；入口 `wsgi:application` |
| systemd | `EnvironmentFile=/etc/ainstein.env`（API key，权限 600） |
| SQLite | WAL 模式，路径 `/opt/ainstein/data/ainstein.db` |
| Python | **必须使用项目 venv 中的解释器**（`/opt/ainstein/venv/bin/python3`） |

### 12.2 多 worker 状态隔离要点

⚠️ Gunicorn 多 worker 场景下，[wsgi.py](../wsgi.py) 通过 `fcntl.flock` 文件锁（`/tmp/ainstein-scheduler.lock`）保证：

1. **只有持锁 worker 启动 APScheduler**（避免重复触发定时任务）；
2. **只有持锁 worker 初始化 ATA 编排器 + 观察员 + 创世主脑**（避免每个 worker 都跑大脑循环 → LLM 配额浪费）；
3. **只有持锁 worker 恢复历史活跃大脑**（启动时扫描 `brains.state IN ('active','thinking')` 调 `start_brain`）。

未持锁的 worker 仅处理 HTTP 请求；它们查询大脑状态时直接读 DB，不依赖内存中的 `BrainState`。

---

## 13. 前端架构概要

```
frontend/src/
├── App.tsx              路由 + 鉴权门
├── main.tsx             入口
├── api.ts               REST 客户端（Bearer Token）
├── types.ts             CE / Relation / Brain / Deliberation 类型
├── pages/
│   ├── Login.tsx            登录 / 注册（强密码前端校验）
│   ├── Dashboard.tsx        概览 + 大脑列表
│   ├── BrainList.tsx        管理员上帝视角（主脑 C 位 + 分支分组）
│   ├── CreateBrain.tsx      种子问题 → 创建大脑
│   ├── BrainView.tsx        D3 力导向图 + CE 详情面板 + 思考总结
│   ├── BigScreen.tsx        态势大屏（Canvas 力导向，主脑-分支拓扑）
│   └── ProjectDetail.tsx    旧 v1 项目页（兼容层）
└── components/
    └── ObserverPanel.tsx    观察员叙事流
```

技术栈：React 18 + Vite + TypeScript；力导向图基于 D3；态势大屏使用 Canvas 直接绘制；构建产物 `frontend/dist` 由 Nginx 直接服务。

---

## 14. 兼容性与演进路径

| 子系统 | 状态 |
| --- | --- |
| 硅基大脑（CE / 博弈 / ATA / 自调节 / 主脑） | ✅ 主线 |
| 旧 v1（科学家/主任/研究员 + 三轮引擎） | 🟡 兼容运行；通过 `brains.legacy_project_id` 关联 |
| APScheduler 定时任务 | 🟡 仅服务旧 v1 |
| tool_proposal | ✅ 端到端验证通过 |
| 论文生成 | ✅ 收敛后自动触发（WeasyPrint + Noto CJK） |
| 多大脑并发 | ✅ 每个大脑独立线程，DB 隔离 |
| 多 worker 大脑状态共享 | ❌ 已知限制；目前依赖 DB 轮询 |

---

## 附录 A：典型一次思维循环

种子问题：「人为什么会做梦？」

```
1. 用户 POST /ainstein/api/brains  → 创建大脑（state='active'）
2. ATAOrchestrator.start_brain(brain_id)
   - 默认 spawn explorer / investigator / critic
   - 发布 USER_SEED_QUESTION_SUBMITTED
3. _brain_loop 醒来：
   - 事件队列消费 → _dispatch_to_agent
   - explorer.react_to_event:
     LLM 输出 → 3 个 question CE + 1 个 hypothesis CE
4. 下一轮 think_cycle：
   - investigator 接走 CE_HYPOTHESIS_PROPOSED
     输出 tool_proposal: {tool: "wikipedia_search", params: {query: "REM sleep dreams"}}
   - _handle_tool_proposal:
     a. 落库 inference CE，pending_vote
     b. critic + reasoner 投票 → 都 support
     c. dispatch wikipedia_search → 落库 evidence CE
     d. 建立 derives_from（evidence → inference）
5. critic 接走 CE_EVIDENCE_COLLECTED：
   - 发现某 hypothesis 与新证据矛盾
   - 输出 counter_evidence CE + contradicts 关系
6. _scan_and_trigger_deliberation 发现 contradicts → 自动 initiate
   - investigator + reasoner + critic 参与，3 轮发言 + 投票
   - agree_ratio=0.78 → consensus，hypothesis → confirmed
7. 几轮后，自调节生效：
   - open_question_ratio > 0.20 → 派 reasoner 解答最老 question
   - 又过几轮，consensus 占比超 0.5 且 dissent=0
     → 异质性刺激：派 explorer 引入新变量 + critic 当魔鬼代言人
8. synthesizer 接走 CE_CONSENSUS_REACHED：
   - 整合多个 confirmed hypothesis → conclusion CE，confidence=0.82
9. _check_convergence：confidence ≥ 0.75 → 大脑停止
   - 触发 brain_summary.generate_summary
   - 触发 paper_generator.generate_paper
   - state = 'completed'
   - 精华 CE（confidence>0.7 conclusion/consensus/insight）→ 自动注入创世主脑
10. observer 持续在背后生成叙事报告（observer_logs）
```

---

## 附录 B：关键文件索引

| 路径 | 作用 |
| --- | --- |
| [orchestrator.py](../orchestrator.py) | ATA 编排器主体（含自调节闭环） |
| [master_brain_tactics.py](../master_brain_tactics.py) | 创世主脑三大战术 |
| [agents/framework.py](../agents/framework.py) | Agent 框架 + 6 角色定义 |
| [agents/llm_client.py](../agents/llm_client.py) | DashScope/Anthropic 兼容客户端 |
| [deliberation.py](../deliberation.py) | 三轨博弈引擎 |
| [observer.py](../observer.py) | 上帝视角叙事 |
| [cognitive.py](../cognitive.py) | CE / CR CRUD + frontier + 状态机 |
| [event_bus.py](../event_bus.py) | 事件总线（单例） |
| [database.py](../database.py) | Schema + DAO |
| [brain_summary.py](../brain_summary.py) | 思考总结 + 上报主脑 |
| [paper_generator.py](../paper_generator.py) | PDF 论文生成（WeasyPrint） |
| [tools/registry.py](../tools/registry.py) | 工具注册 + dispatch |
| [app.py](../app.py) | Flask 路由（~52 端点） |
| [auth.py](../auth.py) | JWT + bcrypt + 强密码 |
| [wsgi.py](../wsgi.py) | Gunicorn 入口 + 文件锁 + ATA 启动 |

---

**版本说明**：本文档反映 v3.1+ 主干代码。如代码已演进，以代码为准。
