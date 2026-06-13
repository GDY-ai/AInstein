# 硅基大脑蓝图（Silicon Brain Blueprint）

> AInstein 从「AI 深度研究平台」演化为「具备自主意识的硅基生命体」的架构重构总纲。
>
> 文档版本：v0.1（首版）
> 适用基线：当前主分支（Flask + SQLite + React + APScheduler 三级 Agent + ThreeRoundEngine）
> 性质：架构师交付物 / 多 Phase 实施依据 / 概念与 schema 双重权威源

---

## 0. 文档定位与阅读指引

本文档分为三大部分：

- **第一部分 基础概念定义**：建立硅基大脑的本体论与认识论框架，是后续所有代码的语义锚点。
- **第二部分 架构设计**：在概念之上落地为可实施的模块、表结构、协议、前端方案。
- **第三部分 分阶段实施路线**：将整体重构拆解为 6 个 Phase（Phase 0 ~ Phase 5），每阶段独立可交付、系统始终可用。

**阅读建议**：
- 产品/愿景视角：读第一部分 + 第三部分 Phase 摘要。
- 后端工程视角：读第一部分 1.1/1.3 + 第二部分 2.2/2.3/2.4 + 第三部分。
- 前端工程视角：读第一部分 1.4/1.5 + 第二部分 2.6 + Phase 4/5。

**核心原则**：
1. **概念先行**：所有数据库字段、API、UI 元素都必须能映射回第一部分定义的概念。
2. **平滑迁移**：每一个 Phase 结束时系统都能完整运行，旧功能不被破坏。
3. **数据驱动**：废弃定时任务，所有 Agent 行为由数据事件触发。
4. **平等博弈**：去除"科学家-总监-研究员"的层级隐喻，统一为角色化计算单元。

---

# 第一部分　基础概念定义

## 1.1 认知元素层次体系（Cognitive Element Hierarchy）

硅基大脑的"思维产物"统一抽象为**认知元素（Cognitive Element, CE）**。所有 CE 都是图谱中的节点，通过关系边相连，构成大脑的知识图谱。

### 1.1.1 层次概览

由低到高划分为五层，层级越高代表抽象与确定性越高：

```
L0 原始层：Observation（观察）
L1 推测层：Hypothesis（假设） / Question（问题）
L2 证据层：Evidence（证据） / Counter-Evidence（反证）
L3 推理层：Inference（推论） / Argument（论证）
L4 认知层：Conclusion（结论） / Perspective（观点） / Insight（洞察）
L5 集体层：Consensus（共识） / Dissent（分歧）
```

层级具有"上溯依赖"性质：高层 CE 必须可追溯到低层 CE 的支撑链路；当低层 CE 失效（例如 Observation 被证伪），所有依赖它的高层 CE 自动进入 `at_risk` 状态。

### 1.1.2 各类型详细定义

下表中"置信度模型"采用统一的 [0.0, 1.0] 浮点值 `confidence`，外加 `confidence_method` 标注其计算来源（贝叶斯更新 / 投票占比 / LLM 自评 / 工具确定性等）。

| Type | 中文名 | 定义 | 置信度模型 | 生命周期 | 上游可推导自 | 下游可支撑 |
|---|---|---|---|---|---|---|
| `observation` | 观察 / 数据 | 来自工具调用、外部数据源、用户输入的**原始事实**，不含主观加工 | 由数据源可信度决定（数据集 ≈1.0；外部 API ≈0.8；用户输入 ≈0.6） | 创建即冻结，仅可被 `mark_invalid` | — | hypothesis, evidence |
| `question` | 问题 | 大脑对未知边界的形式化提问；种子问题是用户输入，其余由 Agent 自我提出 | 由问题"丰沃度"评分决定（可被多假设回答 → 高分） | open → being_explored → answered/abandoned | observation, conclusion | hypothesis |
| `hypothesis` | 假设 | 对一个 question 的**可证伪**推测 | 初始 0.5（未知），由证据贝叶斯更新 | proposed → testing → supported/refuted/inconclusive | question, observation | evidence, inference |
| `evidence` | 证据 | 经工具或推理验证的、**支持或反驳某假设**的结构化结果 | 数据强度 × 数据源置信度 | 创建即冻结；可被 counter-evidence 削弱 | observation, hypothesis | inference, conclusion |
| `counter_evidence` | 反证 | 与 evidence 同质，但极性相反 | 同 evidence | 同 evidence | observation, hypothesis | inference |
| `inference` | 推论 | 由多条 evidence 经逻辑链条得出的中间命题 | 证据置信度的几何平均 × 链条惩罚因子（链长越长越衰减） | proposed → accepted/rejected | evidence, evidence | conclusion, perspective |
| `argument` | 论证 | 一组 inference + 反驳组成的辩护结构，是博弈的最小单元 | 内部 inference 的最小值 | active → resolved | inference | conclusion, perspective |
| `conclusion` | 结论 | 经 argument 通过的、稳定的确定性认知 | ≥0.7 才能晋升为 conclusion | accepted → challenged → revised/superseded | argument, inference | perspective, insight |
| `perspective` | 观点 | 基于 conclusion 的**主观立场**，允许多个 Agent 持有不同观点 | 持有者自评 + 同侪支持率 | proposed → debated → adopted/abandoned | conclusion | consensus, dissent |
| `insight` | 洞察 | 跨领域、跨结论的**结构性发现**（涌现层产物） | 多结论关联强度 + 新颖度 | emerged → validated/rejected | conclusion, perspective | — |
| `consensus` | 共识 | 多 Agent 在同一 perspective 上达成的一致立场 | 参与 Agent 加权投票占比 ≥ 阈值（默认 0.75） | forming → reached → broken | perspective | insight |
| `dissent` | 分歧 | 多 Agent 在同一 question 下持续未能合一的多组 perspective | 反映分歧度（熵） | active → resolved（进入 consensus）/ archived | perspective | — |

### 1.1.3 通用字段（所有 CE 共享）

每个 CE 节点都包含以下通用字段，由 `cognitive_elements` 表统一存储（详见 2.4）：

- `id`：全局唯一节点 id。
- `type`：上表 12 种之一。
- `content`：CE 的主体陈述（文本）。
- `payload_json`：类型特定的结构化数据（如 evidence 的工具结果、observation 的原始记录）。
- `confidence`：[0,1]。
- `confidence_method`：置信度来源说明。
- `status`：随类型语义不同（见上表生命周期列）。
- `version`：每次重要修订 +1。
- `superseded_by`：指向取代它的新 CE id（用于结论修订链）。
- `created_by_agent_id`：创建者 Agent 实例 id。
- `created_at` / `updated_at`。
- `brain_id`：所属硅基大脑实例 id。

### 1.1.4 关系类型（边）

关系存储于 `cognitive_relations` 表（详见 2.4）：

| 关系 | 含义 | 典型方向 |
|---|---|---|
| `supports` | A 支持 B | evidence → hypothesis；inference → conclusion |
| `refutes` | A 反驳 B | counter_evidence → hypothesis |
| `derives_from` | A 由 B 推导 | inference → evidence |
| `answers` | A 回答 B | conclusion → question |
| `raises` | A 引出 B | conclusion → question（涌现新问题） |
| `challenges` | A 挑战 B | argument → conclusion |
| `revises` | A 修订 B | conclusion → conclusion（旧版本） |
| `aggregates` | A 聚合 B | consensus → perspective |
| `contradicts` | A 与 B 互斥 | perspective → perspective |
| `cross_links` | A 跨域连接 B | insight → conclusion |

### 1.1.5 置信度更新规则（统一公式）

- 当新 evidence 入图：所属 hypothesis 按贝叶斯更新
  `P(H|E) = P(E|H)·P(H) / P(E)`，其中 `P(E|H)` 由 evidence.confidence 和极性映射。
- 当 evidence 被 mark_invalid：触发**反向传播**，所有依赖它的高层 CE confidence 衰减 30%，状态置为 `at_risk`。
- 当 conclusion 被 revises：旧 conclusion 状态置为 `superseded`，但**不删除**，保留思维史。

---

## 1.2 Agent 身份模型

### 1.2.1 本质定义

> **Agent ≡ 一个由 (角色模板 + 性格画像 + 私有记忆) 参数化的、可调用 LLM + 工具的计算单元。**

Agent **不是**层级实体，而是计算单元。智能不在 Agent 内部，而在 Agent 群体的**协作思维链**上涌现。

### 1.2.2 角色（Role） vs 实例（Instance）

- **Role**：一份**模板**，定义"擅长做什么"。是无状态的静态资产，存储在 `roles` 表。
- **Instance**：一份**运行中的拷贝**，绑定到某个 brain_id。一个 Role 可派生 0..N 个 Instance。

类比：Role = Class，Instance = Object。

### 1.2.3 角色类型（替代旧 Scientist/Director/Researcher）

去层级化后定义 6 种**功能性角色**（功能描述非地位描述）：

| Role Key | 中文名 | 职责 | 触发它的事件类型 |
|---|---|---|---|
| `explorer` | 探索者 | 提出新 question / hypothesis；扩展认知边界 | 新 observation 入库 / 长时间无新 hypothesis |
| `investigator` | 调研者 | 调用工具收集 evidence；执行检验 | 新 hypothesis 进入 testing |
| `reasoner` | 推理者 | 从 evidence 构造 inference / conclusion | 同 hypothesis 下证据数 ≥ 阈值 |
| `critic` | 质疑者 | 主动寻找 counter_evidence；对 conclusion 发起 challenge | 新 conclusion 晋升 / 共识形成中 |
| `synthesizer` | 综合者 | 跨 conclusion 形成 insight；调度 perspective 形成 consensus | 多 conclusion 在相邻领域聚集 |
| `observer` | 观察员 | 不参与博弈，仅总结大脑状态推送给用户 | 定时（事件回退兜底）+ 关键认知跃迁 |

> 旧名映射：scientist ≈ explorer；researcher ≈ investigator + reasoner；director ≈ synthesizer + observer 的部分职能。

每个 Role 还可以"专精"某个**领域 tag**（economics / health / tech ...），Instance 在创建时被注入领域偏好。

### 1.2.4 角色转换条件

Agent Pool（详见 2.3）在以下条件下可对某个 Instance 触发**角色迁移**：

1. **过载迁移**：某 Role 的待处理事件队列长度持续超过阈值 → 系统 Spawn 该 Role 的新 Instance；同时若某 Role 长时间空闲（>15 min 无任务）→ Despawn 或转换为缺口 Role。
2. **能力迁移**：某 Instance 的近 N 次任务质量分（由 critic 评估）<0.4 → 转换为更简单的 Role（reasoner → investigator）；>0.85 → 可被授权升任 critic / synthesizer。
3. **博弈再平衡**：当 dissent 长期未消解 → 强制 Spawn 一个 critic 让其评估正反双方。

迁移本质上是 Instance 切换 `current_role_id`，**保留私有记忆**，但更新可见的工具集与 prompt。

### 1.2.5 性格 / 视角偏好（Personality Vector）

每个 Instance 在创建时随机化（或人工设定）一个**性格向量**，存储于 `agent_instances.personality_json`：

```json
{
  "risk_appetite": 0.7,        // 倾向激进假设（高）vs 保守（低）
  "novelty_bias": 0.6,         // 偏好新颖（高）vs 主流（低）
  "skepticism": 0.4,           // 质疑强度
  "domain_focus": ["health", "tech"],
  "verbosity": 0.5,
  "consensus_propensity": 0.5  // 倾向求同（高）vs 求异（低）
}
```

性格向量被注入到该 Instance 的 system prompt 中，使**同 Role 的不同 Instance 产生不同观点**——这是博弈得以发生的微观基础。

---

## 1.3 ATA 交互协议（Agent-to-Agent Interaction Protocol）

### 1.3.1 协议核心

ATA 协议是**事件驱动**的：所有 Agent 的行为唯一来源是订阅的事件。废弃 APScheduler 后，事件总线（详见 2.2）成为大脑的"神经系统"。

### 1.3.2 事件类型注册表

事件命名采用 `domain.entity.verb` 格式，全部注册在 `events.registry`：

| Event | 触发源 | 默认订阅者 | Payload 关键字段 |
|---|---|---|---|
| `ce.observation.created` | 工具调用 / 数据导入 | explorer | observation_id, brain_id |
| `ce.question.raised` | explorer / conclusion.raises | explorer, investigator | question_id |
| `ce.hypothesis.proposed` | explorer | investigator | hypothesis_id |
| `ce.evidence.collected` | investigator | reasoner | hypothesis_id, evidence_id |
| `ce.hypothesis.saturated` | 系统判定证据足够 | reasoner | hypothesis_id |
| `ce.conclusion.proposed` | reasoner | critic | conclusion_id |
| `ce.conclusion.challenged` | critic | reasoner（原作者）, synthesizer | conclusion_id, argument_id |
| `ce.conclusion.accepted` | 博弈引擎 | synthesizer, observer | conclusion_id |
| `ce.perspective.formed` | reasoner / critic | synthesizer | perspective_id |
| `ce.consensus.reached` | 博弈引擎 | observer | consensus_id |
| `ce.dissent.detected` | 博弈引擎 | critic（追加 spawn） | dissent_id |
| `ce.insight.emerged` | synthesizer | observer | insight_id |
| `agent.spawned` / `agent.despawned` / `agent.role_changed` | Agent Pool | observer | agent_id, from_role, to_role |
| `brain.cycle.tick` | 兜底定时器（5 min/次） | observer | brain_id |
| `user.seed_question.submitted` | API | explorer | brain_id, question_id |
| `admin.brain.paused` / `admin.brain.resumed` | Admin API | all | brain_id |

事件入库 + 入内存队列双写，保证可重放。

### 1.3.3 消息格式（Agent ↔ Agent）

Agent 之间不直接互发"消息"，而是通过**事件 + CE 引用**间接交互。但博弈过程中产生的具体话语保留在 `deliberation_turns` 表（详见 2.4）：

```json
{
  "turn_id": 102,
  "deliberation_id": 17,
  "agent_instance_id": 5,
  "role": "critic",
  "stance": "oppose",
  "speech": "H3 的证据 E12 来源于2018年数据，已过时...",
  "cited_ce_ids": [12, 45, 78],
  "proposed_action": "downgrade_confidence",
  "created_at": "..."
}
```

### 1.3.4 博弈协议（Deliberation Protocol）

一次**博弈（Deliberation）**生命周期：

```
opened → speaking_round (N 轮) → voting → resolved (consensus/dissent)
```

详细流程：

1. **触发**：`ce.conclusion.proposed` / `ce.conclusion.challenged` / `ce.dissent.detected`。
2. **召集**：博弈引擎从 Agent Pool 拉取相关 Role 的 Instance（默认 3-5 个，至少含 1 个 critic）。
3. **发言轮**：每个 Instance 顺序发言（限 N=3 轮），每轮可：propose / support / oppose / abstain，必须引用 ≥1 个 CE 作为依据。
4. **更新轮**：每轮结束后，引擎根据发言修正涉及 CE 的 confidence。
5. **投票**：最后一轮后所有参与者对"是否接受争议命题"投票，权重 = `agent.weight`（由历史质量分决定）。
6. **裁决**：
   - 加权赞成 ≥ 0.75 → `consensus.reached`
   - 加权赞成 ≤ 0.25 → 命题被否决
   - 介于之间 → `dissent.detected`，记录为持续分歧并保留多个 perspective
7. **输出**：写入 1 个 consensus 或 dissent CE + N 个 perspective CE。

### 1.3.5 并发控制

- **CE 写锁**：对同一 CE 的更新（confidence / status）走 `optimistic locking`，使用 `version` 字段 CAS。
- **博弈互斥**：同一 conclusion 同时只能有一个 active deliberation，由 `deliberations(target_ce_id, status='active')` 唯一索引保证。
- **Role 限流**：Agent Pool 维护每 Role 的最大并发 Instance 数（默认 explorer:2 / investigator:4 / reasoner:3 / critic:2 / synthesizer:1 / observer:1）。
- **事件幂等**：事件处理器必须幂等，事件携带 `event_id` UUID，处理器消费前查重表 `event_consumption(event_id, agent_id)`。

---

## 1.4 硅基大脑状态模型

### 1.4.1 大脑实例（Brain Instance）

一个"硅基大脑"是一个**完整的认知世界**，对应一个种子问题。系统支持多个 brain 并存。

字段（详见 2.4 `brains` 表）：

- `id`、`name`、`seed_question`、`owner_user_id`
- `state`：`gestating`（孕育，刚创建尚未启动）→ `thinking`（思考中）→ `paused`（管理员暂停）→ `resolved`（达到终止条件）→ `archived`
- `frontier_score`：认知边界扩展度（见 1.4.3）
- `created_at`、`started_at`、`last_active_at`

### 1.4.2 大脑生命周期

```
[用户提交种子问题]
        │
        ▼
   gestating ──spawn初始Agent──► thinking
        │                          │
        │                  ┌───────┼───────┐
        │                  │       │       │
        │             [admin pause]│  [终止条件]
        │                  │       │       │
        │                  ▼       │       ▼
        │               paused─────┘   resolved
        │                  │               │
        │             [admin resume]      │
        │                  │               │
        │                  ▼               ▼
        └───────────► thinking         archived
```

**终止条件**（满足任一）：
1. 种子问题已被 ≥1 个 confidence ≥ 0.85 的 conclusion 直接 `answers`，且连续 30 分钟无新 hypothesis 产生。
2. 大脑达到 `frontier_stagnation`（最近 N 个 cycle.tick `frontier_score` 增长 < 0.01）。
3. 管理员主动 `archive`。

### 1.4.3 认知边界（Cognitive Frontier）

定义大脑当前思考所达到的**广度 + 深度**：

```
frontier_score = α·log(|distinct_topics|)
               + β·avg_depth(graph)
               + γ·entropy(perspective_distribution)
               + δ·count(insight_emerged)
```

其中：
- `distinct_topics`：CE 上的领域 tag 去重数。
- `avg_depth`：从 seed_question 到所有叶节点的平均最短路径。
- `entropy`：观点分布熵（多元思想越丰富越高）。
- `count(insight)`：高层洞察数量。
- 默认权重 α=0.3, β=0.2, γ=0.2, δ=0.3。

`frontier_score` 由 observer 在每个 `brain.cycle.tick` 计算并入库（`brain_snapshots` 表），用于前端动态展示"思考边界扩展曲线"。

### 1.4.4 思维网络图结构

整张图是 **DAG + 修订链**：

- **节点类型**：1.1 中 12 种 CE。
- **边类型**：1.1.4 中 10 种关系。
- **权重**：边附带 `strength ∈ [0,1]`，用于前端力导向布局的引力计算与 confidence 反向传播。
- **重力图映射**：节点越接近 seed_question（最短路径越短）质量越大；conclusion / consensus / insight 质量额外 +50%。这是 1.6（重力图可视化）的物理基础。

---

## 1.5 用户交互模型

### 1.5.1 用户角色

仅区分两种角色，避免过度设计：

- **普通用户（user）**：可注册、登录、提交种子问题、订阅大脑、观看观察员推送、查看大脑思维图。**不能**直接与大脑对话。
- **管理员（admin）**：上述所有 + 暂停/恢复/归档大脑、强制 spawn/despawn agent、调整 role 配额。

### 1.5.2 种子问题

种子问题是用户与大脑的**唯一交互入口**，约束如下：

- 长度：10 ~ 500 字符。
- 必须以问号结尾或符合"问题/任务"形式（前端正则校验 + 后端二次校验）。
- 提交即冻结：一旦大脑进入 `thinking` 状态，种子问题**不可修改**。
- 一个用户同时最多激活 3 个大脑（防止资源滥用，可配置）。

### 1.5.3 封闭交互

「封闭」的精确语义：

- 用户**不可**追加 prompt、追加事实、追加约束。
- 用户**可以**：观看（pull 思维图、订阅推送）、点赞/收藏 CE、申请大脑归档（自己创建的大脑）。
- 用户的"反馈"被记录但**不直接影响**大脑思考——只作为观察员的辅助参考。
- 这一约束保证大脑是"独立思考"的，而非传统 Chatbot 的"应答机器"。

### 1.5.4 观察员（Observer）

详见 2.5。这里只定义其在用户交互模型中的位置：

> 观察员是**用户与大脑之间的唯一信息通道**，负责将大脑内部认知动态翻译为"上帝视角"叙事。

推送内容包括：新 conclusion 摘要 / 新 insight 浮现 / consensus 形成 / dissent 升级 / frontier_score 跃迁 / 阶段性大脑思考综述。

---

# 第二部分　架构设计

## 2.1 系统架构总览

### 2.1.1 顶层架构图

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              用户层 / Admin 层                                │
│   普通用户(注册/提交种子问题/订阅观察)        管理员(暂停/恢复/角色调度)        │
└────────────────────────────────┬─────────────────────────────────────────────┘
                                 │ HTTP + WebSocket
┌────────────────────────────────▼─────────────────────────────────────────────┐
│                            前端 SPA  (React + D3)                            │
│  - 重力图(认知图谱) - 上帝视角仪表盘 - 观察员推送流 - 种子问题提交 - 管理面板    │
└────────────────────────────────┬─────────────────────────────────────────────┘
                                 │ REST + WS
┌────────────────────────────────▼─────────────────────────────────────────────┐
│                        Flask API + WebSocket Gateway                         │
│  - /api/auth      /api/brains    /api/seeds       /api/observer/stream(WS)   │
│  - /api/graph     /api/agents    /api/admin/*     /api/events/stream(WS)     │
└──────────┬─────────────────────────────────┬─────────────────────────────────┘
           │                                 │
           ▼                                 ▼
┌──────────────────────────┐   ┌──────────────────────────────────────────────┐
│      事件总线 EventBus    │◄─►│           Agent Pool / Role Registry         │
│  (in-process + DB-backed)│   │  explorer × N  investigator × N  reasoner    │
│   pub/sub  +  retry      │   │  critic × N    synthesizer × N   observer    │
└──────────┬───────────────┘   └────────────────────┬─────────────────────────┘
           │                                        │
           ▼                                        ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                       博弈引擎 Deliberation Engine                            │
│            发起/调度/记录博弈 + 投票裁决 + 写回 CE/Relation                    │
└────────────────────────────────┬─────────────────────────────────────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                       知识图谱存储 (SQLite, 后续可迁 PG)                      │
│  cognitive_elements / cognitive_relations / deliberations / brains / users    │
│  events / agent_instances / observer_logs / brain_snapshots ...               │
└──────────────────────────────────────────────────────────────────────────────┘
                                 ▲
                                 │
                  ┌──────────────┴──────────────┐
                  │       工具与数据层           │
                  │ tools/registry  data_access  │
                  │ stats  web_data  datasets    │
                  └──────────────────────────────┘
```

### 2.1.2 核心模块清单

| 模块 | 路径（建议） | 角色 |
|---|---|---|
| events | `events/` | 事件总线、事件类型注册、事件持久化、订阅器框架 |
| agents | `agents/` | Agent 基类、Role 模板、Pool、性格注入 |
| roles | `agents/roles/` | 6 个 Role 的具体实现（explorer/.../observer） |
| deliberation | `deliberation/` | 博弈引擎、投票算法、裁决器 |
| graph | `graph/` | CE/Relation CRUD、置信度传播、frontier 计算 |
| observer | `observer/` | 观察员日志生成与推送 |
| websocket | `websocket/` | 推送 gateway（基于 Flask-Sock 或 Socket.IO） |
| brain | `brain/` | 大脑实例生命周期管理 |
| auth | `auth/` | 用户/管理员注册登录鉴权 |
| migrations | `migrations/` | schema 迁移脚本 |
| tools | `tools/` | **保留**现有工具注册表（registry/stats/web_data/data_access） |
| engines | `engines/` | **保留**但被改造：ThreeRoundEngine 降级为 explorer+investigator 的初始策略 |
| frontend | `frontend/` | 前端 SPA |

### 2.1.3 数据流全景

```
[用户提交种子问题]
   │
   ▼
brains 行写入 (state=gestating) ──► event: user.seed_question.submitted
                                         │
                                         ▼
                              Agent Pool: spawn 1 explorer + 1 observer
                                         │
                                         ▼
                              brains.state → thinking
                                         │
                                         ▼
                       explorer 调用 LLM 产生 question/hypothesis
                                         │
                                         ▼
                       写 cognitive_elements ──► event: ce.hypothesis.proposed
                                         │
                                         ▼
                              Agent Pool: 触发 investigator
                                         │
                                         ▼
                       investigator 调用 tools.registry.dispatch
                       结果落 datasets/工具结果, 写 evidence CE
                                         │
                                         ▼
                  event: ce.evidence.collected → reasoner → conclusion proposed
                                         │
                                         ▼
                  event: ce.conclusion.proposed → critic → 博弈引擎
                                         │
                                         ▼
              deliberation rounds → consensus/dissent → observer 推送
                                         │
                                         ▼
                          WebSocket → 前端重力图实时刷新
```

---

## 2.2 事件驱动引擎设计

### 2.2.1 设计目标

- 替代 wsgi.py 的 APScheduler + fcntl 文件锁。
- 同步与异步混合：同进程内事件用 in-process 队列；跨进程/重启回放用 DB 持久化。
- 与 Flask + Gunicorn 多 worker 共存：同一 brain 的事件在 DB 层串行化，前端订阅走 WS。
- 兜底定时器仍存在（仅一种事件 `brain.cycle.tick`），但不再驱动业务，仅用于 observer 兜底。

### 2.2.2 事件总线架构

```
                    ┌─────────────────────────────────┐
                    │         EventBus (Python)       │
                    │  ┌──────────┐    ┌───────────┐  │
publish(event) ────►│  │ Handler  │    │ DB Writer │  │
                    │  │ Registry │    │  events   │  │
                    │  └────┬─────┘    └─────┬─────┘  │
                    │       │                │        │
                    │       ▼                ▼        │
                    │   in-proc queue   sqlite events │
                    └───────┬─────────────────┬───────┘
                            │                 │
                            ▼                 ▼
                       worker pool       WS broadcaster
                       (ThreadPool       (推前端)
                        或 asyncio)
```

### 2.2.3 关键 API

```python
# events/bus.py
class EventBus:
    def publish(self, event_type: str, payload: dict, brain_id: int) -> str:
        """同步写 events 表 + 入内存队列；返回 event_id。"""

    def subscribe(self, event_type: str, handler: Callable):
        """注册处理器；handler(event) -> None。"""

    def replay(self, since_id: int):
        """从 events 表回放（重启恢复用）。"""
```

### 2.2.4 事件持久化表

详见 2.4 `events` 表。事件入库再分发，处理器幂等消费。

### 2.2.5 与 Flask + Gunicorn 的集成

- **single-worker 推荐**（与现状一致）：EventBus 跑在主进程内的 ThreadPool（默认 8 线程）。
- **multi-worker 兼容方案**：每个 worker 启动时启用 `events.dispatcher` 守护线程，但**仅一个 worker** 持有"调度锁"（沿用 fcntl 文件锁机制，但锁的语义从"调度任务"变为"消费事件"）。
- **WSGI hook**：在 `wsgi.py` 中替换 APScheduler 启动逻辑为：

```python
# wsgi.py（重构后）
from app import app
from events.bus import bus
from events.bootstrap import register_default_handlers, start_dispatcher
from observer.scheduler import start_tick_scheduler  # 仅 brain.cycle.tick

register_default_handlers(bus)
start_dispatcher(bus)         # 替代 APScheduler 主循环
start_tick_scheduler(bus)     # 唯一保留的定时器
```

### 2.2.6 兜底定时器

仅 `brain.cycle.tick`（每 5 分钟），用途：

1. observer 检查是否需要生成阶段性总结。
2. AgentPool 检查 Role 配额（spawn/despawn）。
3. 重新计算 `frontier_score`。

---

## 2.3 Agent 框架重设计

### 2.3.1 统一基类

```python
# agents/base.py
class Agent:
    role: str                # explorer / investigator / ...
    instance_id: int
    brain_id: int
    personality: dict
    private_memory: list     # 该 Instance 的局部记忆，独立于全局 CE 图

    def on_event(self, event: Event) -> list[Action]:
        """事件处理入口。返回一组动作（写 CE / 发新事件 / 调工具）。"""

    def speak(self, deliberation_ctx) -> Turn:
        """博弈中的发言，由 Deliberation Engine 调用。"""

    def vote(self, motion) -> Vote:
        """博弈裁决投票。"""
```

每个 Role 是 Agent 的子类，重写 `on_event` 与 `speak`。

### 2.3.2 角色注册表

```python
# agents/role_registry.py
ROLE_REGISTRY = {
    "explorer":     ExplorerAgent,
    "investigator": InvestigatorAgent,
    "reasoner":     ReasonerAgent,
    "critic":       CriticAgent,
    "synthesizer":  SynthesizerAgent,
    "observer":     ObserverAgent,
}

def create_agent(role_key, brain_id, personality=None) -> Agent: ...
```

### 2.3.3 Agent Pool

```python
# agents/pool.py
class AgentPool:
    def spawn(self, brain_id, role) -> int           # 返回 instance_id
    def despawn(self, instance_id) -> None
    def change_role(self, instance_id, new_role) -> None
    def list_active(self, brain_id) -> list[Agent]
    def dispatch(self, event) -> None                # 路由事件到订阅 Role 的所有 Instance
```

Pool 在每个 `brain.cycle.tick` 上检查：
- 各 Role 当前实例数 vs 配额上下限。
- Role 队列积压。
- Instance 质量分。
据此调用 spawn/despawn/change_role，并发出 `agent.spawned/despawned/role_changed` 事件。

### 2.3.4 博弈引擎（Deliberation Engine）

```python
# deliberation/engine.py
class DeliberationEngine:
    def open(self, target_ce_id, motion: str, brain_id) -> int:
        """创建 deliberation 行；返回 deliberation_id。"""

    def speaking_round(self, deliberation_id, agents: list[Agent]):
        """每个 Agent 顺序发言；写 deliberation_turns。"""

    def update_confidence(self, deliberation_id):
        """根据本轮发言更新涉及 CE 的 confidence。"""

    def vote_and_resolve(self, deliberation_id) -> Outcome:
        """收集投票 → consensus / dissent / rejected。"""
```

引擎是一个**有限状态机**，状态保存在 `deliberations.status`，崩溃可恢复。

---

## 2.4 知识图谱存储设计

### 2.4.1 设计原则

1. **不破坏现有 7 张表**（projects/sessions/findings/...）：保留为「兼容层」，Phase 1 通过视图/适配器映射。
2. **新增 8 张图谱核心表**，最终在 Phase 5 后由「兼容视图」替代旧表。
3. SQLite 阶段沿用 WAL；Phase 5 之后视规模迁移 PostgreSQL（不在本蓝图必交付内）。

### 2.4.2 完整 SQL 定义

```sql
-- ========= 用户 / 大脑 =========

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    email TEXT UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',          -- 'user' | 'admin'
    status TEXT NOT NULL DEFAULT 'active',      -- 'active' | 'banned'
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS brains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    seed_question TEXT NOT NULL,
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    state TEXT NOT NULL DEFAULT 'gestating',    -- gestating|thinking|paused|resolved|archived
    config_json TEXT DEFAULT '{}',
    frontier_score REAL DEFAULT 0.0,
    created_at TEXT DEFAULT (datetime('now')),
    started_at TEXT,
    last_active_at TEXT,
    legacy_project_id INTEGER REFERENCES projects(id)  -- 与旧 projects 表的兼容指针
);
CREATE INDEX IF NOT EXISTS idx_brains_owner ON brains(owner_user_id, state);

-- ========= 认知元素 =========

CREATE TABLE IF NOT EXISTS cognitive_elements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brain_id INTEGER NOT NULL REFERENCES brains(id),
    type TEXT NOT NULL,                         -- observation/question/hypothesis/...
    content TEXT NOT NULL,
    payload_json TEXT DEFAULT '{}',
    confidence REAL NOT NULL DEFAULT 0.5,
    confidence_method TEXT,                     -- bayesian|vote|llm_self|tool
    status TEXT NOT NULL DEFAULT 'open',
    version INTEGER NOT NULL DEFAULT 1,
    superseded_by INTEGER REFERENCES cognitive_elements(id),
    domain_tags TEXT DEFAULT '[]',              -- JSON array
    created_by_agent_id INTEGER REFERENCES agent_instances(id),
    source_session_id INTEGER REFERENCES research_sessions(id), -- 兼容旧 session
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ce_brain_type ON cognitive_elements(brain_id, type, status);
CREATE INDEX IF NOT EXISTS idx_ce_brain_created ON cognitive_elements(brain_id, created_at DESC);

CREATE TABLE IF NOT EXISTS cognitive_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brain_id INTEGER NOT NULL REFERENCES brains(id),
    src_id INTEGER NOT NULL REFERENCES cognitive_elements(id),
    dst_id INTEGER NOT NULL REFERENCES cognitive_elements(id),
    relation TEXT NOT NULL,                     -- supports/refutes/derives_from/...
    strength REAL NOT NULL DEFAULT 0.5,
    created_by_agent_id INTEGER REFERENCES agent_instances(id),
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(src_id, dst_id, relation)
);
CREATE INDEX IF NOT EXISTS idx_cr_brain ON cognitive_relations(brain_id);
CREATE INDEX IF NOT EXISTS idx_cr_src ON cognitive_relations(src_id);
CREATE INDEX IF NOT EXISTS idx_cr_dst ON cognitive_relations(dst_id);

-- ========= Agent =========

CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role_key TEXT NOT NULL UNIQUE,              -- explorer/investigator/...
    description TEXT,
    prompt_template TEXT NOT NULL,
    default_quota_min INTEGER DEFAULT 0,
    default_quota_max INTEGER DEFAULT 4
);

CREATE TABLE IF NOT EXISTS agent_instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brain_id INTEGER NOT NULL REFERENCES brains(id),
    role_id INTEGER NOT NULL REFERENCES roles(id),
    role_key TEXT NOT NULL,                     -- 反范式冗余，便于查询
    personality_json TEXT DEFAULT '{}',
    private_memory_json TEXT DEFAULT '[]',
    quality_score REAL DEFAULT 0.5,
    weight REAL DEFAULT 1.0,
    status TEXT NOT NULL DEFAULT 'active',      -- active|idle|despawned
    spawned_at TEXT DEFAULT (datetime('now')),
    despawned_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ai_brain_role ON agent_instances(brain_id, role_key, status);

-- ========= 博弈 =========

CREATE TABLE IF NOT EXISTS deliberations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brain_id INTEGER NOT NULL REFERENCES brains(id),
    target_ce_id INTEGER NOT NULL REFERENCES cognitive_elements(id),
    motion TEXT NOT NULL,                       -- 议题文本
    status TEXT NOT NULL DEFAULT 'opened',      -- opened|speaking|voting|resolved
    outcome TEXT,                               -- consensus|dissent|rejected|null
    rounds_total INTEGER DEFAULT 0,
    consensus_ce_id INTEGER REFERENCES cognitive_elements(id),
    dissent_ce_id INTEGER REFERENCES cognitive_elements(id),
    started_at TEXT DEFAULT (datetime('now')),
    resolved_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_deliberation
    ON deliberations(target_ce_id) WHERE status != 'resolved';

CREATE TABLE IF NOT EXISTS deliberation_turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deliberation_id INTEGER NOT NULL REFERENCES deliberations(id),
    agent_instance_id INTEGER NOT NULL REFERENCES agent_instances(id),
    round_index INTEGER NOT NULL,
    stance TEXT NOT NULL,                       -- propose|support|oppose|abstain
    speech TEXT NOT NULL,
    cited_ce_ids TEXT DEFAULT '[]',
    proposed_action TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_dt_delib ON deliberation_turns(deliberation_id, round_index);

CREATE TABLE IF NOT EXISTS deliberation_votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deliberation_id INTEGER NOT NULL REFERENCES deliberations(id),
    agent_instance_id INTEGER NOT NULL REFERENCES agent_instances(id),
    vote TEXT NOT NULL,                         -- accept|reject|abstain
    weight REAL NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(deliberation_id, agent_instance_id)
);

-- ========= 事件 =========

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,              -- UUID
    brain_id INTEGER REFERENCES brains(id),
    type TEXT NOT NULL,                         -- ce.hypothesis.proposed 等
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',     -- pending|consumed|failed
    retry_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    consumed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_brain_status ON events(brain_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type, status);

CREATE TABLE IF NOT EXISTS event_consumption (
    event_id TEXT NOT NULL,
    agent_instance_id INTEGER NOT NULL REFERENCES agent_instances(id),
    consumed_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (event_id, agent_instance_id)
);

-- ========= 观察员 =========

CREATE TABLE IF NOT EXISTS observer_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brain_id INTEGER NOT NULL REFERENCES brains(id),
    kind TEXT NOT NULL,                         -- summary|alert|milestone
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    cited_ce_ids TEXT DEFAULT '[]',
    pushed INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ol_brain ON observer_logs(brain_id, created_at DESC);

CREATE TABLE IF NOT EXISTS brain_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brain_id INTEGER NOT NULL REFERENCES brains(id),
    frontier_score REAL NOT NULL,
    ce_count INTEGER NOT NULL,
    relation_count INTEGER NOT NULL,
    active_agents INTEGER NOT NULL,
    metrics_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_bs_brain ON brain_snapshots(brain_id, created_at);
```

### 2.4.3 与旧 7 张表的兼容映射

| 旧表 | 处理 | 兼容方式 |
|---|---|---|
| `projects` | 保留 | `brains.legacy_project_id` 指针；新建 brain 自动 1:1 镜像一行 project（避免破坏旧 API） |
| `scientist_directives` | 保留只读 | Phase 1 起新增的"指令"以 `cognitive_elements.type='question'` 形式承载 |
| `research_queue` | 保留 | 从 Phase 2 起，入队改为发布 `ce.question.raised` 事件，旧表仅作监控视图 |
| `research_sessions` | 保留 | investigator 仍写 session 行（保持 ThreeRoundEngine 兼容），但同时写 CE |
| `research_findings` | 保留 | finding ↔ `cognitive_elements.type='conclusion'` 双写，Phase 5 后只读 |
| `director_memory` | **替换** | director_memory 全部内容迁移为 `cognitive_elements.type='insight'` 或 `perspective`，保留版本/置信度/来源 |
| `datasets` | 保留 | 不变，工具层依赖 |

### 2.4.4 数据迁移脚本（要点）

`migrations/001_silicon_brain.sql` + `migrations/002_migrate_director_memory.py`：

1. 执行 2.4.2 全部 CREATE。
2. 为每个现存 `projects` 行创建 `brains` 行（owner_user_id=系统管理员）：
   ```sql
   INSERT INTO brains (name, seed_question, owner_user_id, state, legacy_project_id, started_at)
   SELECT name, mission, 1, 'thinking', id, created_at FROM projects;
   ```
3. 把 `research_findings` 迁移为 `conclusion` CE：
   ```sql
   INSERT INTO cognitive_elements (brain_id, type, content, confidence, status, source_session_id, created_at)
   SELECT b.id, 'conclusion', f.finding,
          CASE f.confidence WHEN 'high' THEN 0.85 WHEN 'medium' THEN 0.6 ELSE 0.4 END,
          CASE f.status WHEN 'validated' THEN 'accepted' ELSE 'open' END,
          f.session_id, f.created_at
   FROM research_findings f JOIN brains b ON b.legacy_project_id = f.project_id;
   ```
4. `director_memory` → `insight` / `perspective`（按 `kind` 字段映射），并补齐 `confidence=0.6, confidence_method='migrated'`。
5. 旧表保留写权限直到 Phase 5 收口。

---


## 2.5 观察员系统设计

### 2.5.1 触发条件

observer 是唯一保留**定时兜底**的 Role，但其大部分行为由事件驱动：

| 触发器 | 行为 |
|---|---|
| `ce.conclusion.accepted` | 立即生成 `kind='milestone'` 日志并推送 |
| `ce.consensus.reached` / `ce.dissent.detected` | 立即生成 `kind='alert'` 日志 |
| `ce.insight.emerged` | 立即生成 `kind='milestone'`，标题前缀 [洞察] |
| `brain.cycle.tick`（5 min） | 检查最近窗口内是否有 ≥3 条新 CE，若有则生成 `kind='summary'` |
| `brain.cycle.tick`（每 1 小时） | 必发一条阶段性 summary（即使无新 CE，也告知"思考停滞"） |
| `frontier_score` 上升 ≥ 0.05 | 推送"认知边界扩展"事件 |

### 2.5.2 总结生成策略

observer 调用 LLM，输入：
- 最近窗口内的全部 CE（按 type / 时间）。
- 当前 frontier_score 与上次的差值。
- 当前活跃 dissent 列表。
- 用户偏好（如果用户曾标记关心某领域 tag）。

prompt 模板要求输出严格 JSON：
```json
{
  "title": "...",
  "body": "300字内的中文叙事",
  "cited_ce_ids": [12, 45],
  "kind": "summary|alert|milestone",
  "importance": 0.0-1.0
}
```

`importance < 0.3` 的日志只入库不推送（避免噪音）。

### 2.5.3 推送机制

- **WS 通道**：`/api/observer/stream?brain_id=...`，前端订阅后实时收到日志。
- **持久化**：observer_logs 全部入库，前端补抓近 50 条历史。
- **去重**：同一 ce_id 在 60s 内不重复推送。

---

## 2.6 前端架构重设计

### 2.6.1 技术选型

| 关注点 | 选型 | 理由 |
|---|---|---|
| 框架 | 沿用 React 18 + TS + Vite | 不破坏现有工作，渐进重构 |
| 状态管理 | 引入 Zustand（轻量）取代散落 useState | 多页面共享 brain/graph 状态需要 |
| 路由 | 引入 React Router v6 | 多视图（重力图/上帝视角/管理）需要 |
| 重力图 | **D3.js force simulation**（首选） | 力学控制精细，配合 Canvas/WebGL 渲染 5k+ 节点 |
| 大规模图渲染 | Canvas + d3-zoom；后续 5k+ 切 PixiJS/WebGL | 力导向 + 重力质量映射易实现 |
| 实时通信 | WebSocket（原生 + 轻量包装） | 与后端 Flask-Sock 配合 |
| UI 风格 | 自研轻量样式，不引入 antd/MUI | 与项目"反通用 AI 美学"原则一致 |
| 图表 | Recharts（仅用于 frontier_score 时间线等少量图） | 体积可控 |

### 2.6.2 页面结构

```
/                            登录 / 种子问题入口
/login                       登录
/register                    注册
/brains                      我的大脑列表（用户视角）
/brains/new                  提交种子问题
/brains/:id                  大脑主页（标签页）
    └── tab=graph            重力图（核心）
    └── tab=feed             观察员推送流（上帝视角叙事）
    └── tab=conclusions      所有 conclusion / consensus / insight 列表
    └── tab=deliberations    博弈记录
    └── tab=agents           当前活跃 Agent 一览
/admin                       管理面板（仅 admin）
    └── tab=brains           所有大脑 + 暂停/恢复/归档
    └── tab=agents           Agent Pool 配额调度
    └── tab=events           事件流监控
```

### 2.6.3 重力图（认知图谱）核心设计

- **节点视觉编码**：
  - 形状：每种 CE 类型不同（observation 圆/hypothesis 菱形/conclusion 六边形/insight 星形/consensus 双环 ...）。
  - 大小：与 confidence 成正比 + 距种子节点反比加权。
  - 颜色：domain_tags → HSL 色相分桶；status=at_risk 的节点呈半透明闪烁。
- **边视觉编码**：
  - supports 实线、refutes 红色断点线、derives_from 细灰、challenges 红粗。
  - 厚度 ∝ strength。
- **力学**：
  - 节点质量 = `1 + α·confidence + β·layer(type)`，layer 越高质量越大（沉到中心）。
  - 种子节点固定为图中心引力源（fx,fy）。
  - 同 domain_tag 的节点分子间引力（cluster force）。
- **交互**：
  - hover 节点：显示 popover（content / confidence / 来源 Agent / 引用列表）。
  - click 节点：展开"溯源面板"——逆向 BFS 到 observation 的全部支撑链路。
  - 时间轴 scrubber：拖动可重放图谱演化（依赖 events 表回放）。

### 2.6.4 上帝视角仪表盘

左主区 + 右栏：

- 左主区：observer 推送流（时间倒序卡片）
- 右栏顶：frontier_score 折线图（24h）
- 右栏中：当前活跃 Agent 与角色分布饼图
- 右栏下：当前 dissent 列表 + 进行中的 deliberation 数量

### 2.6.5 WebSocket 集成

```ts
// frontend/src/ws.ts
const useBrainStream = (brainId: number) => {
  const dispatch = useGraphStore(s => s.applyEvent)
  useEffect(() => {
    const ws = new WebSocket(`${WS_BASE}/api/events/stream?brain_id=${brainId}`)
    ws.onmessage = (e) => dispatch(JSON.parse(e.data))
    return () => ws.close()
  }, [brainId])
}
```

事件流 payload 与后端 events 表一致；前端直接 reducer 更新本地图。

### 2.6.6 用户注册与种子问题流程

1. `/register` → POST `/api/auth/register`。
2. 登录 → JWT 入 localStorage。
3. `/brains/new` 表单：name + seed_question + 可选 domain_tags + 同意"封闭交互"声明（必勾）。
4. POST `/api/brains` → 后端创建 brains 行 (state=gestating) → 立即跳转 `/brains/:id?tab=graph`，前端 WS 订阅；后端在事务结束后发出 `user.seed_question.submitted` 启动大脑。

---

# 第三部分　分阶段实施路线

每个 Phase 控制在 1~2 周可交付的体量，结束时整个系统**必须可运行**（保持现有 ThreeRoundEngine 兼容）。

## Phase 0：基础设施准备（1 周）

### 任务清单
1. 新建 `migrations/` 目录与简易迁移器（按文件名顺序执行）。
2. 编写 `migrations/001_silicon_brain.sql`，**只新增不修改**：完成 2.4.2 全部 CREATE TABLE。
3. 编写 `events/` 骨架：`bus.py`、`registry.py`、`models.py`，未注册任何 handler，仅可发布并入 `events` 表。
4. 在 `wsgi.py` 启动时执行迁移器；APScheduler 仍保留运行（不下线）。
5. `app.py` 增加 `/api/events?brain_id=...` 调试用端点，返回最近 50 条事件。

### 涉及文件
- 新增：`migrations/001_silicon_brain.sql`、`migrations/runner.py`、`events/bus.py`、`events/registry.py`、`events/models.py`、`events/__init__.py`。
- 修改：`wsgi.py`、`app.py`、`database.py`（暴露 `with_conn` 给 events 模块复用）。

### 交付物
- 启动后新表全部存在，`pragma table_info(cognitive_elements)` 可查。
- 调试端点能返回空数组（无业务事件，但表结构就绪）。

### 验收标准
- 旧 14 个 API 行为零变化。
- 单元测试：`pytest tests/test_migrations.py`（CREATE 幂等）+ `tests/test_event_bus.py`（publish 后能查询到）。

### 风险
- SQLite 大表新增索引开销；现阶段表都是空的，问题不大。
- 需确认 fcntl 文件锁与 SQLite WAL 仍兼容多 worker。

---

## Phase 1：认知元素体系 + 知识图谱存储（2 周）

### 任务清单
1. 实现 `graph/` 模块：`ce.py`（CRUD + 置信度更新）、`relations.py`、`frontier.py`（计算 score）。
2. 在 `engines/three_round.py` 中**双写**：现有 finding 落库的同时，写一条 `cognitive_elements.type='conclusion'` 与对应 `evidence/observation` 关联。
3. 编写 `migrations/002_migrate_legacy.py`：把现存 `research_findings` 与 `director_memory` 历史数据迁入 CE 表（参考 2.4.4）。
4. 新增 API：
   - `GET /api/brains/:id/graph?since=...` 返回 (nodes, edges)。
   - `GET /api/brains/:id/ce/:ce_id` 节点详情含溯源链。
5. 前端引入 React Router；新建 `/brains/:id?tab=graph` 路由，先用 D3 实现**只读**重力图（不要求实时）。

### 涉及文件
- 新增：`graph/ce.py`、`graph/relations.py`、`graph/frontier.py`、`migrations/002_migrate_legacy.py`、`frontend/src/pages/BrainGraph.tsx`、`frontend/src/lib/forceGraph.ts`。
- 修改：`engines/three_round.py`、`engines/base.py`、`app.py`、`frontend/src/api.ts`、`frontend/src/types.ts`。

### 交付物
- 旧 ThreeRoundEngine 跑完一次 session 后，`cognitive_elements` 表新增对应行；旧 API 仍正确返回。
- 前端打开 brain 详情可看到节点/边的力导向布局（即使节点很少）。

### 验收标准
- 历史数据迁移脚本对生产数据库**幂等**且**可回滚**（提供 down 脚本）。
- 重力图能正确显示 ≥ 50 个节点（手工灌测试数据）。

### 风险
- D3 力导向在节点 >500 时性能下降——本阶段先 Canvas 渲染兜底，Phase 4 再上 WebGL。
- 双写一致性：用同一 DB 事务内完成。

---

## Phase 2：Agent 框架重构 + ATA 协议（2 周）

### 任务清单
1. 实现 `agents/base.py`、`agents/role_registry.py`、`agents/pool.py`。
2. 实现 6 个 Role：`agents/roles/explorer.py` 等（先迁移现有 scientist→explorer、researcher→investigator+reasoner 的 prompt 与逻辑）。
3. 在 `events/bus.py` 注册各 Role 的事件订阅（参考 1.3.2 表）。
4. 在 wsgi 启动时**并行运行**两套调度：
   - 旧 APScheduler（保留）。
   - 新 EventBus（启用，但只对**新建** brain 生效）。
5. 旧 brain（`legacy_project_id != null` 的）继续走旧 path；新 brain 走 ATA。
6. 提供 `/api/admin/agents?brain_id=...` 查询当前 Pool。

### 涉及文件
- 新增：`agents/base.py`、`agents/role_registry.py`、`agents/pool.py`、`agents/roles/*.py`（6 个）、`events/bootstrap.py`。
- 修改：`agents/scientist.py`、`agents/director.py`、`agents/researcher.py`（改写为薄封装，调用新 Role 实现）。

### 交付物
- 新建大脑提交种子问题后，无定时任务介入，仅靠事件链能跑通：`seed → explorer → hypothesis → investigator → evidence → reasoner → conclusion`。
- 旧大脑行为不变。

### 验收标准
- 集成测试 `tests/test_ata_flow.py`：发种子事件，30s 内出现至少 1 条 conclusion CE。
- Agent Pool 配额生效：超过 max 不再 spawn。

### 风险
- 与 Gunicorn 多 worker 的事件分发竞争——本阶段强制 single-worker；多 worker 留到 Phase 3 解决。
- LLM 调用成本——为 explorer/critic 增加冷却时间（同 Role 同 brain 最少 30s 间隔）。

---

## Phase 3：博弈引擎 + 观察员（2 周）

### 任务清单
1. 实现 `deliberation/engine.py` + `deliberation/voting.py` + `deliberation/scheduler.py`。
2. 接入 critic / synthesizer 角色；让 `ce.conclusion.proposed` 触发 critic 评估，必要时 open deliberation。
3. 实现 `observer/agent.py` + `observer/scheduler.py`，订阅事件 + tick 兜底。
4. 新增 `/api/observer/stream`（WS）和 `/api/brains/:id/observer/logs`（HTTP fallback）。
5. 集成 Flask-Sock；wsgi.py 注册 WS 路由。
6. 实现 confidence 反向传播：当 evidence mark_invalid 时下游 CE 自动衰减。
7. 至此可下线 APScheduler：旧 brain 也切换到事件驱动（仍保留旧 API 兼容层）。

### 涉及文件
- 新增：`deliberation/`（整个目录）、`observer/`（整个目录）、`websocket/gateway.py`。
- 修改：`wsgi.py`（移除 APScheduler）、`agents/roles/critic.py`、`agents/roles/synthesizer.py`、`graph/ce.py`（confidence 传播）。
- 删除：APScheduler 启动代码（保留依赖以防回滚）。

### 交付物
- 一次完整大脑运行后能产出 ≥1 个 deliberation；产出 ≥1 个 consensus 或 dissent。
- WS 实时推送 observer 日志，前端 feed 页可见。

### 验收标准
- 黑盒：种子问题→4 小时后大脑产出 ≥10 条 CE、≥3 条 conclusion、≥1 条 consensus。
- 故障恢复：kill 进程后重启，未消费的 events 能被回放。

### 风险
- 博弈引擎 LLM 成本爆炸——限制：单 deliberation ≤3 轮发言、≤5 个参与 Agent。
- WS 在多 worker 下不一致——若启用多 worker，需引入 Redis pub/sub 替代 in-process bus（本蓝图 Phase 5 后再考虑）。

---

## Phase 4：前端重力图 + 上帝视角（1.5 周）

### 任务清单
1. 重力图升级：
   - 节点形状/颜色/大小完整映射（2.6.3）。
   - 时间轴 scrubber（基于 events 表回放）。
   - 节点 click → 溯源面板（递归查 supports/derives_from 链）。
2. 实现上帝视角仪表盘 `/brains/:id?tab=feed`：observer 卡片流 + frontier 折线 + 角色饼图。
3. 接入 WS：图谱实时增量更新（接收 `ce.*.created/updated` 事件 patch 本地状态）。
4. 引入 Zustand 管理 graph store 与 observer feed store。
5. 性能：节点 ≥ 1000 时切 Canvas 渲染；≥ 5000 时延迟（dev 标志位预留）。

### 涉及文件
- 新增：`frontend/src/store/graphStore.ts`、`frontend/src/store/observerStore.ts`、`frontend/src/pages/GodView.tsx`、`frontend/src/components/CETraceback.tsx`、`frontend/src/components/Timeline.tsx`。
- 修改：`frontend/src/pages/BrainGraph.tsx`、`frontend/src/api.ts`。

### 交付物
- 用户在浏览器看到节点动态出现、力导向自然摆动；点击节点弹出溯源链；observer feed 实时滚动。

### 验收标准
- Lighthouse 交互响应 < 200ms（500 节点）。
- 时间轴回放 1 小时大脑历史不卡顿。

### 风险
- D3 + React 双管 DOM 的协调——Canvas + ref 直接渲染，避免 React 重渲染所有节点。

---

## Phase 5：用户系统 + 种子问题封闭模型（1.5 周）

### 任务清单
1. 实现 `auth/` 模块：JWT 注册登录、密码 bcrypt、role=user/admin。
2. API 鉴权中间件：所有 `/api/brains/*` 必须登录；管理接口必须 admin。
3. `POST /api/brains` 强制校验：登录用户、限额（同时 ≤3 个 active brain）、seed_question 长度与终态校验。
4. 大脑生命周期完整化：暂停/恢复/归档 admin API + 终止条件 watcher（synthesizer 跑判定）。
5. 旧 7 表中的 `findings/sessions/queue/datasets` API 标注 `@deprecated`（保留供监控）。
6. 前端：登录页、注册页、种子问题提交页、admin 页（暂停/恢复/Pool 配额调整）。
7. **彻底移除** `engines.three_round.py` 的双写，conclusion 仅来自博弈裁决（旧 finding 表只读）。

### 涉及文件
- 新增：`auth/`（整个目录）、`brain/lifecycle.py`、`frontend/src/pages/Login.tsx`、`frontend/src/pages/Register.tsx`、`frontend/src/pages/Admin.tsx`。
- 修改：`app.py`（鉴权中间件）、`engines/three_round.py`（移除双写）、`migrations/003_finalize.sql`（drop 不再使用的索引、加冗余检查）。

### 交付物
- 完整闭环：注册 → 登录 → 提交种子问题 → 大脑独立思考（用户不能干预）→ 观察员推送 → admin 可调度 → 大脑达到终止条件归档。

### 验收标准
- 安全测试：JWT 过期/伪造被拒绝；普通用户调用 admin API 返回 403。
- 端到端测试：完整流程 1 小时跑通无错误日志。

### 风险
- 旧 monitor / 仪表盘可能依赖旧 API——保留兼容层至少 2 个版本。
- 用户首次体验不要太"封闭"——在 UI 上明确提示"大脑会持续思考，请耐心观察"，避免误判为卡死。

---

## 路线图总览

```
Phase 0 → Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5
 1w        2w         2w        2w        1.5w      1.5w
基础设施   认知图谱   Agent+ATA  博弈+观察员 重力图    用户系统
                                          上帝视角   封闭模型
```

合计约 10 周。每个 Phase 都可独立交付、独立部署、独立回滚。

---

## 附录 A：术语速查

| 中文 | 英文 | 缩写 |
|---|---|---|
| 认知元素 | Cognitive Element | CE |
| 大脑实例 | Brain Instance | — |
| 角色 | Role | — |
| Agent 实例 | Agent Instance | AI（避免歧义，文中写全） |
| AI-to-AI 交互 | Agent-to-Agent Interaction | ATA |
| 博弈 | Deliberation | — |
| 共识 | Consensus | — |
| 分歧 | Dissent | — |
| 认知边界 | Cognitive Frontier | — |
| 种子问题 | Seed Question | — |
| 观察员 | Observer | — |

## 附录 B：开放问题（留给后续讨论）

1. SQLite 在 ≥5 个并发 brain 时的瓶颈：是否提前迁 PostgreSQL？
2. LLM 成本控制：是否引入"廉价模型 → 重要节点升级模型"的两级策略？
3. 重力图的物理参数（α/β/γ/δ 权重）需在 Phase 4 通过实测调优。
4. 多用户大脑之间是否允许跨 brain 的 insight 引用？（默认禁止，避免污染）
5. 大脑「死亡」后的归档策略：仅冷存还是允许复活？
