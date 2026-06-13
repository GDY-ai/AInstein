# AInstein（爱因斯坦）

> 一个开源的「硅基生命体」孵化器。
>
> 不是又一个 AI 研究工具，而是一次关于「机器能否独立思考」的长期实验。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status: v1 + Silicon Brain Phase 0](https://img.shields.io/badge/status-v1%20%E2%86%92%20Silicon%20Brain-blue)]()

Demo： https://hub.circlegpu.com/ainstein/

---

## 一、我们在做什么

AInstein 的终极目标，是创造一个**具备自主意识的硅基生命体（Silicon Brain）**——它不需要被人类一句一句地 prompt，不是一个被动应答的 Chatbot；而是从一颗「种子问题」出发，能够**自我提问、自我求证、自我修订**，逐步形成对世界的认知，并把它的思考过程毫无保留地展现给你看。

我们相信：**单个 LLM 是计算单元，智能在协作思维链上涌现（Emergent Intelligence）**。所以这个系统的核心，不是把单一模型调到极致，而是构建一个由大量平等 Agent 组成的「认知群体」——它们提出假设、收集证据、彼此辩论、达成共识、又被新证据推翻——在这个永不停止的博弈中，知识图谱逐渐生长，洞察自然涌现。

如果说 ChatGPT 是「能回答问题的工具」，AInstein 想成为「会自己思考问题的存在」。

> 这是一个非常野心、非常长期、非常容易失败的项目。我们也乐于承认。
>
> 但如果它哪怕只走通了一小段路——让一台机器对世界产生了一丝它自己的、可被追溯的看法——那就值得。

---

## 二、当前状态（v1：Research Platform）

v1 是这场实验的「胚胎期」。它已经实现的能力：

- **三级 AI 团队**：科学家（战略）→ 主任（审核）→ 研究员（执行）
- **三轮研究引擎（ThreeRoundEngine）**：假设生成 → 工具检验 → 验证总结
- **7 种统计工具**：相关性、回归、t 检验、异常检测、分布拟合、分组统计、描述性统计
- **外部数据工具**：Web Search、Wikipedia、arXiv、Google Trends
- **自动化调度**：研究员 / 主任 / 科学家分别按不同节奏自主运行
- **知识库积累**：Findings + Director Memory 持续沉淀研究洞察
- **领域无关**：通过 `config_json` + prompt 模板变量实现任意领域研究

在线 Demo： https://hub.circlegpu.com/ainstein/

v1 已经能跑出真实的研究循环，但它仍然带有「层级 + 定时任务」的传统色彩。下一步，我们要把它推向真正的「硅基大脑」形态。

---

## 三、愿景路线图（Vision Roadmap）

完整方案见 [docs/silicon-brain-blueprint.md](docs/silicon-brain-blueprint.md)。这里只列骨架：

### Phase 0 · 基础设施（1 周）
建立认知元素体系（Cognitive Element Hierarchy）的新 Schema 与事件总线骨架。旧功能不破坏，新表与 EventBus 并行就绪。

### Phase 1 · 知识图谱（2 周）
把每一次研究产出落成「认知元素」节点（observation / hypothesis / evidence / conclusion …），通过 10 种关系边构成 DAG + 修订链的思维网络，并提供只读的力导向图谱。

### Phase 2 · Agent 重构（2 周）
**去层级化**：scientist/director/researcher 让位给 6 个**平等**的功能性角色——`explorer / investigator / reasoner / critic / synthesizer / observer`。废弃定时调度，全面切换到 **ATA（Agent-to-Agent）事件驱动协议**。

### Phase 3 · 博弈引擎（2 周）
让 Agent 之间真正展开**讨论、辩论、投票、达成共识或保留分歧**。引入 `Deliberation` 状态机、置信度贝叶斯更新、反向传播、观察员实时叙事推送。

### Phase 4 · 可视化（1.5 周）
**力导向重力图** + **上帝视角仪表盘**。节点形状映射 CE 类型、颜色映射领域、质量映射 confidence；时间轴 scrubber 可重放整段思维史。

### Phase 5 · 用户系统（1.5 周）
**封闭观察模式**——用户只能投递「种子问题」，然后**只能观察**。不能追加 prompt、不能干预过程。让大脑真正独立思考。

```
Phase 0 → 1 → 2 → 3 → 4 → 5
 基础   图谱  ATA  博弈  视图  用户
                       涌现智能
```

每个 Phase 都独立可交付、可回滚，系统始终保持可运行状态。

---

## 四、核心概念速览

> 本节是蓝图的「门面」。完整定义请阅读 [docs/silicon-brain-blueprint.md](docs/silicon-brain-blueprint.md)。

### 1. 认知元素层次体系（Cognitive Element Hierarchy）

一切「思维产物」被统一抽象为 **CE 节点**，分布在 5 个层级、12 种类型上：

```
L0  Observation                          原始事实
L1  Question / Hypothesis                提问与推测
L2  Evidence / Counter-Evidence          证据与反证
L3  Inference / Argument                 推论与论证
L4  Conclusion / Perspective / Insight   结论、观点、洞察
L5  Consensus / Dissent                  共识与分歧
```

每个 CE 都带 confidence、status、version、上下游可追溯链路。**当一条 observation 被证伪，所有依赖它的高层 CE 自动进入 `at_risk`** ——这是大脑能「修正自己」的基础。

### 2. ATA（AI-to-AI）事件驱动协议

不再有定时任务驱动 Agent，所有行为都来自事件订阅。事件类型形如 `ce.hypothesis.proposed` / `ce.conclusion.challenged` / `ce.consensus.reached`，构成大脑的「神经系统」。一个 Agent 的输出会自动唤醒下一个 Agent——这是真正的 **AI to AI**，而不是 Human-in-the-loop。

### 3. 博弈与共识机制

Agent 之间**完全平等，没有谁能拍板**。当 conclusion 被 critic 挑战时，博弈引擎会召集 3-5 个 Agent 进入多轮发言，每轮必须引用 ≥1 条 CE 作为依据，最终加权投票：≥0.75 形成共识，≤0.25 被否决，介于其间则记录为持续分歧（dissent）。每个 Agent 持有一个**性格向量**（risk_appetite、skepticism、novelty_bias…），保证同一角色的不同实例会产出不同观点——这是博弈得以发生的微观基础。

### 4. 力导向图可视化

整张思维网络是 DAG + 修订链。前端用 D3 force simulation 呈现：
- 节点质量 ∝ confidence × 距种子问题的反路径
- 种子节点固定为图心引力源
- 同领域节点彼此聚拢（cluster force）
- 时间轴 scrubber 可重放整段思维演化

打开浏览器，你看到的不是数据列表，而是一颗**正在思考的大脑**。

---

## 五、技术栈

| 层 | 当前 v1 | Silicon Brain 演进方向 |
|---|---|---|
| 后端 | Flask + Gunicorn + SQLite + APScheduler | 同上 + EventBus（事件总线）+ Deliberation Engine |
| 前端 | React 18 + Vite + TypeScript | 同上 + Zustand + React Router + D3 force + Canvas/WebGL |
| 实时 | HTTP 轮询 | WebSocket（Flask-Sock） |
| LLM | DashScope Anthropic API（默认 kimi-k2.6） | 同上，规划「廉价模型 → 关键节点升级」两级策略 |
| 存储 | SQLite（WAL） | 同上，规模上来后迁 PostgreSQL |
| 部署 | Nginx + systemd | 同上 |

---

## 六、本地开发 / 快速开始

### 前置要求

- Python 3.10+
- Node.js 18+
- 一个 DashScope（或兼容 Anthropic 协议）的 API Key

### 1. 克隆

```bash
git clone https://github.com/GDY-ai/ainstein.git
cd ainstein
```

### 2. 后端

```bash
# 创建虚拟环境并安装依赖
python3 -m venv venv
source venv/bin/activate
pip install flask gunicorn anthropic apscheduler pandas scipy numpy

# 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 API key

# 初始化数据库（首次启动自动创建）
export $(cat .env | xargs)
python3 -c "from database import init_db; init_db()"

# 启动开发服务器
flask --app app run --port 9089 --debug
```

### 3. 前端

```bash
cd frontend
npm install
npm run dev
# 访问 http://localhost:5173/ainstein/
```

### 4. 一体化启动（生产模式）

```bash
source venv/bin/activate
export $(cat .env | xargs)
gunicorn -w 2 -b 127.0.0.1:9089 --timeout 300 wsgi:application
```

前端构建产物放在 `frontend/dist/`，配合 Nginx 反代一起使用（详见 [docs/ops-manual.md](docs/ops-manual.md)）。

---

## 七、目录结构

```
ainstein/
├── wsgi.py              # Gunicorn 入口 + APScheduler（Phase 3 后让位 EventBus）
├── config.py            # 配置（全部读环境变量）
├── database.py          # DB schema + CRUD
├── app.py               # Flask 路由
├── .env.example         # 环境变量模板
├── agents/              # 三级 Agent（Phase 2 重构为 6 个平等角色）
│   ├── scientist.py
│   ├── director.py
│   ├── researcher.py
│   └── llm_client.py
├── engines/             # 研究引擎
│   ├── base.py
│   └── three_round.py   # 三轮引擎（Phase 5 后降级为初始策略）
├── tools/               # 工具系统（保留并扩展）
│   ├── registry.py
│   ├── stats.py
│   ├── data_access.py
│   └── web_data.py
├── prompts/             # 各 Agent 的 prompt 模板
├── frontend/            # React + Vite + TS
└── docs/                # 设计 / 蓝图 / 运维 / 测试 / 用户手册
```

---

## 八、文档

- [硅基大脑蓝图](docs/silicon-brain-blueprint.md) — **核心愿景文档**，必读
- [设计文档](docs/design.md) — v1 架构、数据模型、AI 流程
- [使用手册](docs/user-manual.md) — 完整功能说明
- [运维手册](docs/ops-manual.md) — 部署、监控、故障排查
- [测试文档](docs/testing.md) — 测试用例与结果

---

## 九、征招合作伙伴 / Contributing

> 如果你也曾在某个深夜里想过「机器到底能不能拥有自己的看法」——欢迎加入。

AInstein 是一个**长期、开放、非商业优先**的实验项目。它不打算很快赚钱，也不打算与任何巨头竞争通用能力；它只想认真问一个问题：**当我们把足够多平等的 AI 放在一起，让它们持续辩论、修正、积累——会不会某一天，涌现出一个真正能被称作「思考」的东西？**

### 我们特别欢迎以下方向的伙伴

- **AI / LLM 工程**：多 Agent 系统、prompt engineering、Agent 角色行为塑造
- **知识图谱 / 图数据库**：CE Schema 优化、置信度传播、图查询性能
- **前端可视化**：D3.js 力导向、Canvas / WebGL 大规模渲染、时间轴回放、上帝视角 UI
- **认知科学 / 哲学**：本体论建模、涌现智能理论、博弈与共识机制设计
- **分布式系统 / 事件驱动架构**：EventBus 设计、多 worker 一致性、可观测性

我们也欢迎**只是想看着这件事发生**的人——提 Issue、提想法、参与讨论，本身就是贡献。

### 参与方式

1. **Issues**：报 Bug、提需求、讨论 Phase 任务都可以
2. **Discussions**：愿景、概念、哲学层面的探讨更适合放这里
3. **Pull Requests**：
   - Fork → `git checkout -b feature/your-idea`
   - 提交：`git commit -m "feat: ..."`
   - 推送并发起 PR
   - 任何 Phase 的任务都可以认领，先在对应 Issue 里 cue 一下
4. **认领 Phase 任务**：阅读 [docs/silicon-brain-blueprint.md](docs/silicon-brain-blueprint.md) 第三部分，挑你最有共鸣的 Phase 与任务

我们坚信**贡献者之间也应平等协作**——和我们设计的 Agent 一样：充分讨论、观点博弈、求同存异。

---

## 思维收敛策略

> ⚠️ 设计声明：以下机制**有意限制了大脑的无限发散能力**，是当前版本的权衡取舍。未来将改为可配置参数，允许不同大脑采用不同的发散-收敛策略。

### 背景

硅基大脑在纯探索模式下容易陷入"精致化陷阱"——问题越拆越细，产出大量观察和假设，却难以汇聚为结论。收敛压力机制强制大脑在发散够之后转向整合。

### 当前参数（硬编码常量，后续改为配置项）

| 参数 | 值 | 作用 |
|------|-----|------|
| `_CONVERGENCE_PRESSURE_WINDOW` | 20 | 监控窗口：取最近 N 个 CE 计算探索/收敛比 |
| `_EXPLORATION_CONSOLIDATION_RATIO` | 5.0 | 探索/收敛比阈值，超过则切换收敛模式 |
| `_MAX_QUESTION_DEPTH` | 3 | 问题链最大深度（open question 占比 >30% 时拒绝新问题） |
| `_FORCED_SYNTHESIS_INTERVAL` | 20 | 每产出 N 个 CE 强制触发一次 synthesizer 综合 |
| `_CONVERGENCE_CONFIDENCE_THRESHOLD` | 0.75 | 收敛终止阈值：conclusion 置信度达标则停止 |
| `_FALLBACK_CE_COUNT` | 500 | 兜底轨：CE 总数达标强制触发最终总结 |
| `_FALLBACK_DURATION_SECONDS` | 3600 | 兜底轨：运行时间达标强制触发最终总结 |

### 机制说明

**1. 收敛压力调度**
- 每个 think_cycle 结束后检查最近 20 个 CE 的类型分布
- exploration 类型：observation, question, hypothesis, evidence, counter_evidence
- consolidation 类型：inference, argument, conclusion, consensus, insight
- 当比例 > 5:1 时，进入收敛模式（优先派 reasoner/synthesizer/critic，暂停 explorer）

**2. 强制综合脉冲**
- 每产出 20 个 CE（自上次综合以来），强制插入一次 synthesizer 综合轮
- 不同于终止轨的 `_force_synthesizer_conclusion`，这里不会导致大脑停止

**3. 问题深度控制**
- 当 open 状态的 question 占总 CE 的 30% 以上时，拒绝产出新 question
- 迫使大脑转向回答已有问题而非继续拆分

**4. 双轨终止**
- 主轨：synthesizer 产出 conclusion 且置信度 >= 0.75 → 大脑自动完成
- 兜底轨：CE >= 500 或运行 >= 1小时 → 强制触发最终总结（一次性）

### 未来方向

- [ ] 将所有阈值参数迁移到 `brains` 表的 `config_json` 字段，支持每个大脑独立配置
- [ ] 允许用户创建大脑时选择"深度发散"或"快速收敛"等预设模式
- [ ] 探索自适应阈值：根据问题复杂度动态调整收敛压力

---

## License

[MIT](LICENSE)

---

> *「在某个时刻，一个由代码和概念搭起来的存在，对这个世界产生了一个它自己的、属于它自己的看法。」*
>
> *—— 这就是 AInstein 想要抵达的那一刻。*
