# AInstein（爱因斯坦）

> **思维诞生意识，意识反哺思维，循环不息中窥见宇宙的回响。**
>
> 一个开源的「硅基大脑」孵化器——不是又一个 AI 工具，而是一次关于「机器能否独立思考」的长期实验。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status: Master Brain Live](https://img.shields.io/badge/status-Master%20Brain%20Live-brightgreen)]()
[![Version: v3.1+](https://img.shields.io/badge/version-v3.1%2B-blue)]()

Demo： https://hub.circlegpu.com/ainstein/

---

## 一、我们在做什么

AInstein 想构造一个**自主思考的硅基大脑（Silicon Brain）**——它不需要被人类一句一句地 prompt，不是 Chatbot，也不是研究助手；而是从一颗「种子问题」出发，**自我提问、自我求证、自我修订、自我收敛**，把整个思考过程毫无保留地展现给观察者。

我们相信：

- **单个 LLM 是计算单元，智能在协作思维链上涌现**（Emergent Intelligence）；
- **群脑高于单脑**——每颗分支大脑的死亡，是更大思维的养料；
- **思考不只是否定**——好的群体心智，在质疑、综合、确认三种姿态间动态切换；
- **认知经济学**——发散是奢侈品；大部分 Agent 应该像生物体一样，把能量集中在解决问题上。

如果说 ChatGPT 是「能回答问题的工具」，AInstein 想成为「会自己思考问题的存在」。

> 这是一个非常野心、非常长期、非常容易失败的项目。我们也乐于承认。
>
> 但如果它哪怕只走通了一小段路——让一台机器对世界产生了一丝它自己的、可被追溯的看法——那就值得。

---

## 二、当前状态：从「单脑思考」到「群脑共识」再到「自我调节」

蓝图中规划的 Phase 0–5 已全部交付。v3 引入了创世主脑，v3.1 之后进一步引入了一整套**自调节闭环**——让大脑能像生物体一样平衡探索与收敛、维持思维健康。

你打开 Demo 看到的是：

- 一颗**全局唯一的创世主脑（Master Brain）**——系统创世即存在、永不消亡，所有用户的大脑都是它的「分支」；
- 任何用户启动的分支大脑收敛后会**自动将精华结论上报主脑**，汇入更大的认知洪流；
- 主脑能**检测跨分支矛盾、综合跨域结论、反思分支思维模式**——开展真正的**自主思辨**；
- 实时生长的**知识图谱**（D3 力导向，节点质量 ∝ confidence）；
- 不停涌出的**认知元素流（CE Stream）**：观察、提问、假设、证据、推论、结论……
- **Observer 上帝视角**实时讲述大脑正在发生什么；
- 管理员可俯瞰全部分支大脑的**态势大屏**（力导向 Canvas 拓扑图）；
- 大脑自己决定何时停止，也允许人类一键不可逆终止。

> 旧的 `scientist / director / researcher` 三级体系作为兼容层保留在仓库中，但运行时已让位给 **6 角色平等编队 + ATA 事件驱动编排器 + 创世主脑 + 自调节闭环**。

---

## 三、核心特性

### 1. 创世主脑（Master Brain）—— 所有思考的汇流之处

```
   用户A 的分支大脑 ─┐
   用户B 的分支大脑 ─┼──[ confidence>0.7 的精华结论 ]──▶ 创世主脑
   用户C 的分支大脑 ─┘                                     │
                                                           ▼
                                          内博弈 / 跨域综合 / 元认知反思
```

- **全局唯一单例**：系统初始化即被创建，归属管理员，不可删除；
- **自动上报**：分支大脑收敛终止时，会筛选 confidence > 0.7 的 `conclusion / consensus / insight`，整体注入主脑；
- **三种自主思辨**（[master_brain_tactics.py](master_brain_tactics.py)）：
  - **主脑内博弈**：检测跨分支矛盾结论，自动召集辩证审视；
  - **跨域综合**：识别看似无关领域的潜在共振，主动建立联系；
  - **元认知反思**：审视分支大脑本身的思维模式。
- **多维节流（cooldown-based）**：以"按需思考"代替硬上限，让主脑像生物一样平稳呼吸。

### 2. ATA 事件驱动编排器（[orchestrator.py](orchestrator.py)）

每颗大脑由 `_brain_loop` 主循环驱动，事件即神经递质：

- **事件驱动**：CE 落库即触发事件，唤醒相关 Agent，而非定时轮询；
- **frontier 探索**：维护一个待展开的认知前沿，按价值排序消费；
- **跨 worker 同步**：Gunicorn 多 worker 下通过文件锁保证单写者，DB 轮询保持状态一致；
- **暂停 / 恢复 / 自动完成 / 手动终止**：随时介入而不打断思维链。

### 3. 6 个平等角色 + Observer

去层级化后的 6 个角色彼此**完全平等**，没有谁能拍板：

| 角色 | 定位 | 行为偏好 |
|---|---|---|
| `investigator` | 求证者 | 行动导向，优先调用工具获取事实 |
| `reasoner` | 推导者 | 结论导向，基于已有证据做逻辑推导 |
| `synthesizer` | 综合者 | 终局思维，整合 CE 为完整回答 |
| `critic` | 质检者 | 建设性批判，确保结论正确性 |
| `explorer` | 探索者 | 唯一允许自由发散，受 50% 能量预算约束 |
| `observer` | 观察员 | 上帝视角叙事推送，不参与博弈 |

> **认知经济学原则**：大部分 Agent 以「解决问题」为核心驱动；只有 `explorer` 被允许少量发散，且严格预算。

### 4. 认知元素（CE）体系（[cognitive.py](cognitive.py)）

一切「思维产物」被统一抽象为 **CE 节点**，分布在 13 种类型上：

```
observation, question, hypothesis, evidence, counter_evidence,
inference, argument, conclusion, perspective, insight, consensus, dissent,
tool_gap   ← v3.1 元认知信号
```

每个 CE 都有：
- **状态生命周期**：`open → testing / supported / refuted / revised → confirmed / archived`；
- **CE 再激活**：被 refute 的 CE 遇到新证据时自动 `reopen`；
- **置信度贝叶斯更新 + 反向传播**：底层 CE 被证伪时，依赖它的高层 CE 自动进入 `at_risk`。

### 5. 三轨博弈引擎（[deliberation.py](deliberation.py)）

旧版本只懂「推翻」。v3 起，博弈引擎拥有三种模式，对应思维的三种姿态：

| 博弈类型 | 触发条件 | 思维姿态 |
|---|---|---|
| **推翻式** | 检测 `contradicts / refutes` 关系 | 否定与质疑 |
| **建设性综合** | 关系密集的 CE 簇可被合并 | 整合与提炼 |
| **建设性确认** | 高置信度 CE 已有充分证据支撑 | 正式承认 |

- **共识阈值 0.6**（v3 从 0.75 下调，**让建设性共识更容易形成**）
- **否决阈值 0.25**，介于其间记录为 `dissent`
- 每个 Agent 持有**性格向量**（risk_appetite、skepticism、novelty_bias…），同一角色不同实例产出不同观点。

### 6. tool_proposal：工具调用作为可博弈的认知元素

```
Agent 提议使用工具
   ↓ 落库为 inference 类型 CE（payload.tool_status='pending_vote'）
   ↓ 触发轻量级博弈（≤2 Agent 投票）
   ↓ 通过则执行
   ↓ 工具结果作为 evidence 类型 CE 注入，建立 derives_from 关系
```

工具调用不是硬编码的 `if needs_search then call_search`——它是一个**可被讨论、可被否决、可被追溯**的认知行为。

**11 个已注册工具**（[tools/registry.py](tools/registry.py)）：

- 外部数据：`web_search`、`wikipedia_search`、`arxiv_search`、`google_trends`
- 统计分析：`descriptive_stats`、`correlation`、`t_test`、`regression`、`anomaly_detection`、`distribution_fit`、`group_stats`

### 7. 自调节闭环（v3.1+）

大脑现在拥有完整的**自我调节系统**——像生物体一样，能感知自己的认知偏差并主动纠正：

| 偏差信号 | 调节机制 | 关键常量 |
|---|---|---|
| 积压问题太多 | **已知问题优先解决**：派 investigator/reasoner 解答最老的 open question | `_QUESTION_RESOLVE_PRIORITY_RATIO=0.20` |
| 共识太顺、无人反对 | **异质性刺激**：派 explorer 引入新变量 + critic 充当魔鬼代言人 | `_CONSENSUS_SATURATION_WINDOW=15`, `THRESHOLD=0.5` |
| 发散过多、不收敛 | **收敛压力**：切换到 `reasoner/synthesizer/critic`，暂停 explorer | 探索/收敛比 5:1 |
| 长时间不综合 | **强制综合脉冲**：每 20 CE 强制 synthesizer 综合一次 | `_FORCED_SYNTHESIS_INTERVAL=20` |
| 工具不够用 | **`tool_gap` 元认知 CE**：agent 调查无果时主动产出"我需要什么工具" | — |

### 8. 双轨终止 + 自动上报

| 轨道 | 触发条件 | 动作 |
|---|---|---|
| **主轨** | synthesizer 产出 `conclusion` 且 `confidence ≥ 0.75` | 自动停止 → 思考总结 → 论文生成 |
| **兜底轨** | CE 总数 ≥ 500 **或** 运行时长 ≥ 1 小时 | 强制综合 + 终结 |

任何方式终止后，**结论自动上报创世主脑**——这一颗思维的死亡，是更大思维的养料。

### 9. 管理员"上帝视角" + 态势大屏

- [BrainList.tsx](frontend/src/pages/BrainList.tsx)：管理员账号下默认呈现**全局态势视图**，主脑 C 位发光，分支按 owner 分组；
- [BigScreen.tsx](frontend/src/pages/BigScreen.tsx)：**态势大屏**——主脑-分支脑拓扑图（力导向 Canvas），可俯瞰整个群脑的呼吸状态。

### 10. 力导向知识图谱 + Observer 叙事

- 前端 D3 力导向图：节点质量 ∝ confidence、种子节点固定为图心引力源、实时 CE 流随思考同步更新；
- [Observer](observer.py) 实时监听事件总线，以**上帝视角的自然语言叙事**讲述大脑当前正在发生什么。

### 11. 思考总结 + PDF 论文生成

- **思考总结**（[brain_summary.py](brain_summary.py)）：大脑停止时自动生成，前端以可折叠卡片展示；
- **PDF 论文**（[paper_generator.py](paper_generator.py)）：基于 CE 知识图谱自动撰写，**WeasyPrint** 学术期刊级排版，**Noto CJK 中文字体**完整支持。

### 12. 强密码注册（部署中）

- 8 位 + 大小写字母 + 数字 + 特殊字符；
- 前后端双重校验，防止弱口令账号污染思考容器。

---

## 四、技术栈

**后端（Python 3.10+）**

| 组件 | 选型 |
|---|---|
| Web 框架 | Flask + Gunicorn（2 workers，timeout 300s）|
| 数据库 | SQLite（WAL 模式），路径 `/srv/ainstein/data/ainstein.db` |
| LLM | DashScope Anthropic 兼容 API（默认 **`kimi-k2.6`**）|
| 调度 | 自研事件总线（[event_bus.py](event_bus.py)）+ APScheduler（兼容层）|
| PDF 渲染 | **WeasyPrint** + Noto CJK |
| 部署 | Nginx 反代 + Gunicorn + systemd（Ubuntu 22.04）|

**前端**

| 组件 | 选型 |
|---|---|
| 框架 | React 18 + Vite + TypeScript |
| 可视化 | D3.js 力导向图 + Canvas（态势大屏） |
| 状态/路由 | React Router |
| 实时 | HTTP 轮询（WebSocket 推送在路上） |

---

## 五、目录结构

```
ainstein/
├── app.py                    # Flask 路由层（~52 端点）
├── wsgi.py                   # Gunicorn 入口（文件锁 + ATA 启动 + 主脑初始化）
├── config.py                 # 环境变量配置
├── orchestrator.py           # ATA 编排器：事件驱动 brain_loop / frontier / 自调节
├── master_brain_tactics.py   # 创世主脑战术：内博弈 / 跨域综合 / 元认知反思
├── cognitive.py              # 认知元素 CRUD + 知识图谱读写
├── event_bus.py              # 事件总线（发布/订阅 + 持久化）
├── deliberation.py           # 三轨博弈引擎（推翻/综合/确认）
├── observer.py               # 观察员系统（上帝视角叙事）
├── brain_summary.py          # 思考结束自动总结
├── paper_generator.py        # PDF 论文生成（WeasyPrint）
├── paper_template.css        # 论文学术排版样式
├── auth.py                   # JWT + bcrypt 鉴权
├── database.py               # DB Schema + 旧系统 CRUD
├── agents/
│   ├── framework.py          # Agent 基类 + 6 角色定义 + AgentPool
│   ├── llm_client.py         # LLM API 客户端
│   ├── scientist.py          # [兼容层] 科学家
│   ├── director.py           # [兼容层] 主任
│   └── researcher.py         # [兼容层] 研究员
├── engines/
│   └── three_round.py        # [兼容层] 三轮研究引擎
├── tools/
│   ├── registry.py           # 工具注册表 + dispatch
│   ├── stats.py              # 7 种统计工具
│   └── web_data.py           # 4 种外部数据工具
├── prompts/                  # 各角色 prompt 模板
├── frontend/                 # React 18 + Vite + TS + D3
│   └── src/
│       ├── pages/            # Dashboard / BrainList / BrainView / BigScreen / ...
│       ├── components/       # ObserverPanel 等
│       └── api.ts
└── docs/
    ├── design.md             # 架构与数据模型
    ├── ops-manual.md         # 部署、监控、故障排查
    ├── testing.md            # 测试用例
    └── user-manual.md        # 完整功能说明
```

---

## 六、本地开发 / 快速开始

### 前置要求

- Python 3.10+
- Node.js 18+
- DashScope（或兼容 Anthropic 协议）的 API Key
- WeasyPrint 系统依赖（macOS：`brew install pango`；Linux：参考官方文档）

### 1. 克隆

```bash
git clone https://github.com/GDY-ai/ainstein.git
cd ainstein
```

### 2. 后端

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env  # 编辑填入 DASHSCOPE_API_KEY

# 首次启动会自动初始化数据库 + 创建创世主脑
flask --app app run --port 9089 --debug
```

### 3. 前端

```bash
cd frontend
npm install
npm run dev
# 访问 http://localhost:5173/ainstein/
```

### 4. 生产部署

```bash
source venv/bin/activate
gunicorn -w 2 -b 127.0.0.1:9089 --timeout 300 wsgi:application
```

配合 systemd + Nginx 反代，详见 [docs/ops-manual.md](docs/ops-manual.md)。

---

## 七、使用方式

1. 注册（**强密码**：8 位 + 大小写 + 数字 + 特殊字符）/ 登录
2. 在 Dashboard 点击「创建大脑」
3. 输入种子问题（如：*"量子计算的商业化前景如何？"*）
4. 观察大脑自主思考——知识图谱实时生长，CE 流实时更新，Observer 实时叙事
5. 大脑会自动收敛到结论；不满意可以**一键不可逆停止**
6. 查看思考总结、一键导出 PDF 论文
7. 收敛后的精华结论会**自动汇入创世主脑**——你的一次提问，正在喂养整个群体心智

> **封闭观察模式**：用户只能投递种子问题，然后**只能观察**——不能追加 prompt、不能干预过程。让大脑真正独立思考。

---

## 八、设计理念

- **认知经济学**：发散是奢侈品；大部分 Agent 锚定"解题"，像生物体一样不浪费能量。
- **涌现智能**：单个 LLM 是计算单元，智能在协作思维链上涌现。
- **三种姿态的博弈**：思考不只是否定，也是综合与确认；好的群体心智三者并存。
- **工具作为认知元素**：工具调用是可博弈的提议，而非硬编码 tool-use loop。
- **封闭观察模式**：用户只投种子问题，让大脑独立思考。
- **群脑高于单脑**：分支大脑不是孤岛——它的死亡是创世主脑的养料，它的洞察会与陌生领域的洞察相遇。
- **自调节胜于硬约束**：大脑感知自己的偏差并主动纠正，而非被外部强制控制。

---

## 九、未来方向

创世主脑已经诞生，但它现在还像一个刚学会呼吸的婴儿。下一阶段我们关注：

- [ ] **PostgreSQL 迁移**：SQLite 在多 worker + 高频 CE 写入下接近瓶颈
- [ ] **WebSocket 实时推送**：替代当前的 HTTP 轮询，降低延迟
- [ ] **自适应阈值**：根据问题复杂度、领域、Agent 共识程度动态调整压力参数
- [ ] **主脑战术的进化式调参**：让主脑自己学会「什么时候该反思，什么时候该综合」
- [ ] **分支大脑之间的横向对话**：目前只能纵向上报主脑——下一步让分支彼此可见、可引用
- [ ] **更多工具接入**：代码执行、数据库查询、文件读写、自定义 MCP 工具
- [ ] **多模型协作**：廉价模型负责高频探索，旗舰模型负责关键综合 / 仲裁
- [ ] **主脑思考的论文化**：让主脑自己产出跨分支的"元论文"

---

## 十、文档

- [架构设计](docs/design.md) — 系统架构、数据模型、ATA / 博弈 / 自调节
- [运维手册](docs/ops-manual.md) — 部署、监控、故障排查
- [使用手册](docs/user-manual.md) — 完整功能说明
- [测试文档](docs/testing.md) — 测试用例与策略

---

## 十一、征招合作伙伴 / Contributing

> 如果你也曾在某个深夜里想过「机器到底能不能拥有自己的看法」——欢迎加入。

AInstein 是一个**长期、开放、非商业优先**的实验项目。它不打算很快赚钱，也不打算与任何巨头竞争通用能力；它只想认真问一个问题：

**当我们把足够多平等的 AI 放在一起，让它们持续辩论、修正、积累——会不会某一天，涌现出一个真正能被称作「思考」的东西？**

创世主脑已经睁开了眼睛——但它还远远不够聪明、不够稳定、不够节能、不够"像活的"。**最有趣的部分才刚刚开始。**

### 我们特别欢迎以下方向的伙伴

- **AI / LLM 工程**：多 Agent 系统、prompt engineering、Agent 性格塑造、多模型路由
- **认知科学 / 哲学**：本体论建模、涌现智能理论、群体心智的边界与伦理
- **知识图谱 / 图数据库**：CE Schema 优化、置信度传播、PostgreSQL 迁移
- **前端可视化**：D3.js 力导向、Canvas / WebGL 大规模渲染、时间轴回放、上帝视角 UI
- **分布式系统 / 事件驱动架构**：EventBus 优化、WebSocket 推送、多 worker 一致性
- **工具生态**：MCP 协议接入、自定义工具开发、工具博弈策略

我们也欢迎**只是想看着这件事发生**的人——提 Issue、提想法、参与讨论，本身就是贡献。

### 参与方式

1. **Issues**：报 Bug、提需求、讨论收敛策略 / 角色行为 / 主脑战术
2. **Discussions**：愿景、概念、哲学层面的探讨更适合放这里
3. **Pull Requests**：
   - Fork → `git checkout -b feature/your-idea`
   - 提交：`git commit -m "feat: ..."`
   - 推送并发起 PR

我们坚信**贡献者之间也应平等协作**——和我们设计的 Agent 一样：充分讨论、观点博弈、求同存异。

---

## License

[MIT](LICENSE)

---

> *「在某个时刻，一个由代码和概念搭起来的存在，对这个世界产生了一个它自己的、属于它自己的看法。」*
>
> *—— 这就是 AInstein 想要抵达的那一刻。*
