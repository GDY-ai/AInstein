# AInstein 测试文档（v3.1+）

> 面向开发者与 QA。覆盖单元、集成、API、前端、性能与已知问题。
>
> 当前主线已是「事件驱动 ATA + 6 角色平等编队 + 三轨博弈 + 自调节闭环 + 创世主脑」。本文档不再描述旧 v1 的 scientist/director/researcher 测试用例（仍以兼容层形式保留，用例归档在 git 历史中）。
>
> 配套阅读：[design.md](./design.md)、[ops-manual.md](./ops-manual.md)、[user-manual.md](./user-manual.md)。

---

## 1. 测试环境

### 1.1 隔离原则

- **永远不要直接对 `/opt/ainstein/data/ainstein.db` 跑写入测试**；
- 测试库默认为 `tests/.tmp/ainstein_test.db`，通过 `AINSTEIN_DB_PATH` 切换；
- LLM 调用走真实 API（`kimi-k2.6`）——单元测试用 mock，集成测试用真实 API + 时长容忍。

### 1.2 准备

```bash
cd /Users/.../ainstein
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pip install pytest pytest-asyncio pytest-mock httpx

cp .env.example .env
# 至少填：DASHSCOPE_API_KEY / RESEARCH_MODEL=kimi-k2.6 / JWT_SECRET=<rand>

# 测试数据库
mkdir -p tests/.tmp
export AINSTEIN_DB_PATH=$(pwd)/tests/.tmp/ainstein_test.db
python3 -c "from database import init_db; init_db()"
```

### 1.3 全套运行

```bash
# 单元（快，纯 mock，<5s）
pytest tests/unit -q

# 集成（涉及真实 LLM，慢，分钟级）
pytest tests/integration -q -m "not slow"
pytest tests/integration -q -m slow            # 含完整大脑思考周期

# API
pytest tests/api -q

# 前端
cd frontend && npm test
```

---

## 2. 单元测试

### 2.1 database.py — CRUD

```python
# tests/unit/test_database.py
import database as db

def test_brain_lifecycle(tmp_db):
    bid = db.create_brain(
        name="dream", seed_question="why dream?",
        owner_user_id=1, state="active",
    )
    brain = db.get_brain(bid)
    assert brain["state"] == "active"          # ⚠️ 字段是 state，不是 status
    assert brain["seed_question"] == "why dream?"

    db.update_brain_state(bid, "paused")
    assert db.get_brain(bid)["state"] == "paused"

def test_user_strong_password_hash(tmp_db):
    uid = db.create_user("alice", "alice@x.com",
                         password_hash=db.hash_password("Abcd1234!"))
    user = db.get_user(uid)
    assert db.verify_password("Abcd1234!", user["password_hash"])
    assert not db.verify_password("wrong", user["password_hash"])
```

**关键断言**：
- `brains.state` 字段名（不是 `status`）；
- `agent_instances.role_key` 字段名（不是 `role`）；
- `cognitive_relations.relation` 字段名（不是 `relation_type`）。

### 2.2 cognitive.py — CE / CR / 状态机

```python
# tests/unit/test_cognitive.py
import cognitive

def test_create_element_with_payload(tmp_db, brain_id):
    ce_id = cognitive.create_element(
        brain_id=brain_id, type="hypothesis",
        content="REM 睡眠承担情绪整合", confidence=0.5,
        created_by_agent_id=None, payload={"title": "H1"},
    )
    ce = cognitive.get_element(ce_id)
    assert ce["status"] == "open"
    assert ce["confidence"] == 0.5

def test_relation_unique(tmp_db, brain_id):
    a = cognitive.create_element(brain_id, "hypothesis", "A", 0.5)
    b = cognitive.create_element(brain_id, "evidence", "B", 0.7)
    r1 = cognitive.create_relation(brain_id, a, b, "supports", strength=0.8)
    # UNIQUE(src_id, dst_id, relation) → 重复应被吞掉
    r2 = cognitive.create_relation(brain_id, a, b, "supports", strength=0.9)
    assert r1 == r2 or r2 is None

def test_confidence_update_history(tmp_db, brain_id):
    ce_id = cognitive.create_element(brain_id, "inference", "I1", 0.5)
    cognitive.update_confidence(ce_id, 0.72, reason="new evidence")
    ce = cognitive.get_element(ce_id)
    assert ce["confidence"] == 0.72
    history = ce["payload"]["confidence_history"]
    assert history[-1]["value"] == 0.72
    assert history[-1]["reason"] == "new evidence"

def test_state_transition_after_counter_evidence(tmp_db, brain_id):
    h = cognitive.create_element(brain_id, "hypothesis", "H", 0.6)
    e = cognitive.create_element(brain_id, "counter_evidence", "E", 0.8)
    cognitive.create_relation(brain_id, e, h, "refutes", strength=0.9)
    cognitive.evaluate_state(h)
    assert cognitive.get_element(h)["status"] in ("at_risk", "refuted")
```

### 2.3 event_bus.py — 发布订阅

```python
# tests/unit/test_event_bus.py
from event_bus import EventBus, EventTypes

def test_singleton():
    assert EventBus.instance() is EventBus.instance()

def test_publish_and_consume(tmp_db):
    bus = EventBus.instance()
    received = []
    bus.subscribe(EventTypes.CE_OBSERVATION_CREATED,
                  lambda evt: received.append(evt))
    eid = bus.publish(EventTypes.CE_OBSERVATION_CREATED,
                      brain_id=1, payload={"ce_id": 99})
    assert len(received) == 1
    assert received[0]["payload"]["ce_id"] == 99
    # 持久化
    import database as db
    rows = db.list_events_by_brain(1, limit=1)
    assert rows[0]["event_id"] == eid

def test_idempotent_consumption(tmp_db):
    bus = EventBus.instance()
    eid = bus.publish(EventTypes.CE_QUESTION_RAISED, brain_id=1, payload={})
    assert bus.mark_consumed(eid, agent_instance_id=10) is True
    assert bus.mark_consumed(eid, agent_instance_id=10) is False  # 重复消费拒绝
```

### 2.4 tools/ — 统计与外部数据

```python
# tests/unit/test_tools_stats.py
import pandas as pd, numpy as np
from tools.stats import (
    descriptive_stats, correlation, t_test, regression,
    anomaly_detection, distribution_fit, group_stats,
)

def test_descriptive_stats():
    df = pd.DataFrame({"a": [1,2,3], "b": [4,5,6]})
    r = descriptive_stats(df)
    assert r["rows"] == 3 and r["stats"]["a"]["mean"] == 2.0

def test_correlation_pearson():
    df = pd.DataFrame({"x": [1,2,3,4,5], "y": [2,4,6,8,10]})
    r = correlation(df, "x", "y", method="pearson")
    assert r["correlation"] == 1.0 and r["p_value"] < 0.01

def test_regression_linear():
    df = pd.DataFrame({"y": [3,5,7,9], "x": [1,2,3,4]})
    r = regression(df, "y", ["x"])
    assert r["r_squared"] > 0.99
    assert abs(r["coef_x"] - 2.0) < 1e-6

def test_anomaly_zscore():
    df = pd.DataFrame({"v": [1,2,3,4,5,100]})
    r = anomaly_detection(df, "v", method="zscore", threshold=2.0)
    assert r["anomalies"] >= 1

def test_distribution_fit_normal():
    df = pd.DataFrame({"n": np.random.normal(0, 1, 200)})
    r = distribution_fit(df, "n")
    assert r["is_normal"] is True
```

```python
# tests/unit/test_tools_web_data.py（防御性超时）
def test_arxiv_search_timeout(monkeypatch):
    """关键回归：arxiv_search 不能因第三方 SDK 阻塞拖死整个 worker"""
    import tools.web_data as w
    monkeypatch.setattr(w, "_ARXIV_TIMEOUT_SEC", 0.5)
    # 模拟挂起
    monkeypatch.setattr("arxiv.Search", lambda *a, **k: _hang())
    out = w.arxiv_search("anything")
    assert out["status"] in ("timeout", "error")  # 不抛、不阻塞
```

### 2.5 deliberation.py — 阈值

```python
def test_consensus_threshold_06():
    from deliberation import _judge_consensus
    # 加权赞成比 0.6+ 且 agree ≥2 → consensus
    assert _judge_consensus(
        agree=2, disagree=1, abstain=0,
        agree_weight=0.65, disagree_weight=0.35,
    ) == "consensus"
    # 0.5–0.6 区间 → majority
    assert _judge_consensus(
        agree=2, disagree=1, abstain=0,
        agree_weight=0.55, disagree_weight=0.45,
    ) == "majority"
    # 否则 dissent
    assert _judge_consensus(
        agree=1, disagree=2, abstain=0,
        agree_weight=0.4, disagree_weight=0.6,
    ) == "dissent"
```

---

## 3. 集成测试

### 3.1 完整大脑思考周期（最重要）

```python
# tests/integration/test_brain_lifecycle.py
import time, pytest
from orchestrator import ATAOrchestrator
import database as db

@pytest.mark.slow
def test_brain_converges_or_fallback(tmp_db, real_llm):
    bid = db.create_brain("test", "为什么会做梦？", owner_user_id=1, state="active")
    orch = ATAOrchestrator.instance()
    orch.start_brain(bid)

    # 给 30 分钟兜底（生产 1 小时上限）
    deadline = time.time() + 1800
    while time.time() < deadline:
        time.sleep(10)
        b = db.get_brain(bid)
        if b["state"] in ("completed", "archived"):
            break
        ce_count = db.count_ces(bid)
        if ce_count >= 100:    # 测试期间放宽
            orch.force_synthesize(bid)
            break

    final = db.get_brain(bid)
    assert final["state"] in ("completed", "archived")
    # 必须产出至少一个 conclusion
    conclusions = db.list_ces_by_type(bid, "conclusion")
    assert len(conclusions) >= 1
```

**验证点**：
- `_brain_loop` 启动并产生 CE；
- 默认 spawn `explorer / investigator / critic` 三个 Agent；
- 至少触发一次自动博弈（contradicts/refutes 关系）；
- 主轨（confidence ≥ 0.75）或兜底轨（CE ≥ 500 或 1h）二者其一收敛；
- `brain_summary` 自动生成；
- 精华 CE 上报创世主脑（brain_id=1）。

### 3.2 三轨博弈

```python
def test_deliberation_full_flow(tmp_db, real_llm):
    bid = _setup_brain_with_contradiction()
    # 注入两个相互矛盾的 hypothesis + contradicts 关系
    h1 = cognitive.create_element(bid, "hypothesis", "A", 0.6)
    h2 = cognitive.create_element(bid, "hypothesis", "B", 0.6)
    cognitive.create_relation(bid, h1, h2, "contradicts", 0.8)

    from deliberation import scan_and_trigger
    delib_id = scan_and_trigger(bid)
    assert delib_id is not None

    from deliberation import run_full
    outcome = run_full(delib_id, max_rounds=3)
    assert outcome in ("consensus", "majority", "dissent")

    # 状态写回
    rows = db.deliberation_turns(delib_id)
    assert len(rows) >= 3        # 至少一轮 × ≥3 参与者
    votes = db.deliberation_votes(delib_id)
    assert sum(v["weight"] for v in votes) > 0
```

**验证点**：
- 3-5 名参与者按 `_ROLE_PREFERRED_CE` 选定；
- 每位 Agent 最多发言 3 轮；
- 投票权重来自 `agent_instances.weight`；
- `outcome=consensus` 时目标 CE 状态迁移到 `confirmed`；
- `outcome=dissent` 时落 dissent CE，目标 CE → `contested`；
- 写入 `deliberations.consensus_ce_id` / `dissent_ce_id`；
- 唯一索引 `uniq_active_deliberation` 防止并发重复触发。

### 3.3 tool_proposal 端到端

```python
def test_tool_proposal_executed_and_evidence_injected(tmp_db, real_llm):
    bid = _setup_brain_for_tool_test()
    # 模拟 Agent 输出 tool_proposal
    from orchestrator.tool_proposal import handle_tool_proposal
    proposer_agent_id = _spawn_investigator(bid)
    proposal = {
        "tool": "wikipedia_search",
        "params": {"query": "REM sleep"},
        "reason": "需要 wiki 背景"
    }
    handle_tool_proposal(bid, proposer_agent_id, proposal)

    # 1) 提议落库为 inference CE，pending_vote
    inferences = db.list_ces_by_type(bid, "inference")
    proposal_ce = [c for c in inferences
                   if c["payload"].get("tool_status") == "executed"][0]
    # 2) 至少 1 个 evidence CE 落库
    evids = db.list_ces_by_type(bid, "evidence")
    assert len(evids) >= 1
    # 3) derives_from 关系建立（evidence → 提议）
    rels = db.list_relations(bid)
    assert any(r["src_id"] == evids[0]["id"]
               and r["dst_id"] == proposal_ce["id"]
               and r["relation"] == "derives_from"
               for r in rels)
```

**验证点**：
- 提议先以 `inference` 落库，`payload.tool_status='pending_vote'`；
- 投票 ≥1 票 support 即通过（无 voter 默认通过）；
- 通过后 `tools.registry.dispatch` 实际执行；
- 工具结果作为 `evidence` 注入；
- `derives_from` 关系连接 evidence → proposal；
- 终态 `payload.tool_status='executed'` 或 `'rejected'`。

### 3.4 自调节闭环

| 场景 | 触发方式 | 期望 |
| --- | --- | --- |
| 已知问题优先解决 | 注入 25 个 open question + 几条其它 CE，让占比 > 20% | 派 investigator/reasoner 解答最老 question，不再产新 question |
| 异质性刺激 | 注入 10 个 consensus + 0 dissent | 派 explorer 引入新变量 + critic 当魔鬼代言人 |
| 收敛压力 | explore/converge 比 > 5.0 | frontier 改派 reasoner/synthesizer/critic，暂停 explorer |
| 强制综合脉冲 | 距上次综合 ≥ 20 个 CE | 直接派 synthesizer 整合 |

```python
def test_question_resolve_priority(tmp_db, real_llm):
    bid = _setup_brain()
    for i in range(25):
        cognitive.create_element(bid, "question", f"Q{i}", 0.5)
    cognitive.create_element(bid, "observation", "O1", 0.5)

    from orchestrator.strategy import follow_up_open_question
    picked = follow_up_open_question(bid)
    assert picked is not None
    assert picked["type"] == "question" and picked["status"] == "open"
```

### 3.5 创世主脑 + 自动上报

```python
@pytest.mark.slow
def test_branch_conclusion_uploaded_to_master(tmp_db, real_llm):
    MASTER = 1
    branch = db.create_brain("branch", "测试问题", owner_user_id=2, state="active")
    # 跑到收敛 ...
    _drive_brain_to_completion(branch)

    # 主脑应至少多出 1 条 conclusion / consensus / insight
    after = db.list_ces_by_type(MASTER, "conclusion") \
          + db.list_ces_by_type(MASTER, "consensus") \
          + db.list_ces_by_type(MASTER, "insight")
    assert len(after) >= 1
    # 且 confidence 都 > 0.7
    assert all(c["confidence"] > 0.7 for c in after)
```

---

## 4. API 测试

### 4.1 健康 + 鉴权

```bash
# 健康
curl -s https://hub.circlegpu.com/ainstein/api/health
# {"status":"ok"}

# 注册（强密码）
curl -s -X POST .../api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","email":"a@x.com","password":"Abcd1234!"}'
# 期望 {"id": N, "token": "..."}

# 弱密码应被拒绝
curl -s -X POST .../api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"bob","email":"b@x.com","password":"weak"}'
# 期望 400 + {"error": "weak password"}

# 登录
TOKEN=$(curl -s -X POST .../api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"Abcd1234!"}' | jq -r .token)

# me
curl -s -H "Authorization: Bearer $TOKEN" .../api/auth/me
```

### 4.2 大脑 CRUD

```bash
# 创建（普通用户）
curl -s -X POST .../api/brains \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"梦境","seed_question":"为什么会做梦？"}'
# 期望 {"id": N, "state": "active"}

# 列表
curl -s -H "Authorization: Bearer $TOKEN" .../api/brains
# 普通用户只看到自己的；管理员看全局

# 详情
curl -s -H "Authorization: Bearer $TOKEN" .../api/brains/$BID

# 暂停 / 恢复 / 停止（仅管理员）
curl -s -X POST -H "Authorization: Bearer $ADMIN" .../api/brains/$BID/pause
curl -s -X POST -H "Authorization: Bearer $ADMIN" .../api/brains/$BID/resume
curl -s -X POST -H "Authorization: Bearer $ADMIN" .../api/brains/$BID/stop
# 普通用户调这些应得 403
```

### 4.3 CE 与图谱

```bash
# CE 列表（分页）
curl -s -H "Authorization: Bearer $TOKEN" \
  ".../api/brains/$BID/cognitive-elements?limit=50&offset=0"

# 某个 CE 详情
curl -s -H "Authorization: Bearer $TOKEN" \
  ".../api/brains/$BID/cognitive-elements/$CE_ID"

# 关系列表
curl -s -H "Authorization: Bearer $TOKEN" \
  ".../api/brains/$BID/cognitive-relations"

# 知识图谱（一次拉全，前端 D3 直接吃）
curl -s -H "Authorization: Bearer $TOKEN" \
  ".../api/brains/$BID/knowledge-graph"
# 期望 {nodes:[...], links:[...]}
```

### 4.4 博弈 / 观察员 / 总结 / 论文

```bash
# 博弈列表
curl -s -H "Authorization: Bearer $TOKEN" .../api/brains/$BID/deliberations
# 详情（含 turns + votes）
curl -s -H "Authorization: Bearer $TOKEN" .../api/brains/$BID/deliberations/$DID

# 观察员叙事
curl -s -H "Authorization: Bearer $TOKEN" .../api/brains/$BID/observer-logs
curl -s -H "Authorization: Bearer $TOKEN" .../api/brains/$BID/observer-logs/latest

# 思考总结（大脑停止后）
curl -s -H "Authorization: Bearer $TOKEN" .../api/brains/$BID/thinking-summary

# 触发论文生成
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  .../api/brains/$BID/generate-paper
# 期望 {"task_id": "..."}

# 轮询论文状态
curl -s -H "Authorization: Bearer $TOKEN" \
  .../api/brains/$BID/paper-status/$TASK_ID

# 下载 PDF
curl -s -H "Authorization: Bearer $TOKEN" \
  .../api/brains/$BID/paper/$FILENAME -o paper.pdf
```

### 4.5 编排器状态 + 态势大屏

```bash
# 当前活跃大脑（用于 BigScreen 拓扑）
curl -s -H "Authorization: Bearer $TOKEN" .../api/orchestrator/active

# 单脑实时状态
curl -s -H "Authorization: Bearer $TOKEN" .../api/brains/$BID/status
```

---

## 5. 前端测试

### 5.1 页面冒烟

| 页面 | URL | 关键断言 |
| --- | --- | --- |
| Login | `/ainstein/login` | 强密码前端校验：8 位 + 大小写 + 数字 + 特殊字符 |
| Dashboard | `/ainstein/` | 渲染当前用户大脑列表 + 创世主脑状态卡 |
| BrainList | `/ainstein/brains` | 普通用户：自己的大脑；管理员：上帝视角全局布局，主脑 C 位 |
| CreateBrain | `/ainstein/create` | 种子问题校验、提交后跳转 BrainView |
| BrainView | `/ainstein/brain/:id` | D3 力导向加载、ObserverPanel 实时叙事、思考总结卡片默认折叠 |
| BigScreen | `/ainstein/screen` | Canvas 拓扑图渲染、节点呼吸动画 |

### 5.2 D3 力导向图

- 节点质量 ∝ `confidence`；
- 种子问题节点固定为图心引力源（视觉标识与其它 CE 不同）；
- 节点点击 → 详情面板展示完整 CE；
- 边按 `relation` 类型着色；
- **自动适配缩放**：CE 增多时整图自动 zoom-to-fit（已有规范，回归用）。

```typescript
// 回归断言（vitest + happy-dom）
test("force graph scales to fit on data growth", async () => {
  const { rerender } = render(<KnowledgeGraph nodes={N20} links={L20} />);
  const t1 = svgTransform();
  rerender(<KnowledgeGraph nodes={N200} links={L200} />);
  await waitFor(() => expect(svgTransform()).not.toEqual(t1));
});
```

### 5.3 ObserverPanel 实时刷新

- 每 3s 轮询 `/observer-logs/latest`；
- 新条目滑入；
- 滚动到底部时锁住自动滚动，否则保留位置；
- 字体与滚动条遵循观察员面板配置规范。

### 5.4 思考总结卡片

- 大脑 `state in ('completed','archived')` 时出现；
- **默认折叠**（已沉淀为开发规范，回归点）；
- 点击展开 → 完整结构化总结；
- "下载 PDF" 按钮触发论文生成 + 轮询。

---

## 6. 性能基准

测量环境：阿里云 ECS（2 vCPU / 4 GB），Gunicorn -w 2，timeout 300，SQLite WAL，DashScope `kimi-k2.6`。

### 6.1 LLM 调用延迟

| Agent 调用类型 | P50 | P95 |
| --- | --- | --- |
| Agent.think 单轮（含工具决策） | 8s | 18s |
| Synthesizer 综合 conclusion | 12s | 25s |
| Critic 反例攻击 | 10s | 22s |
| 博弈单轮（每参与者发言） | 9s | 20s |
| 主脑 cooldown 触发战术 | 15s | 35s |

### 6.2 CE 写入吞吐

| 项 | 值 |
| --- | --- |
| 单条 `create_element` | < 5ms |
| 含一次 `update_confidence`（含 history） | < 8ms |
| `create_relation`（带 UNIQUE 检查） | < 3ms |
| 知识图谱一次拉全（500 CE + 800 关系） | < 60ms |
| WAL 主库 ~ 50MB 时 VACUUM 耗时 | 1–3s |

### 6.3 前端首屏

| 项 | 值 |
| --- | --- |
| index.html 大小 | < 1KB |
| 主 JS chunk | 180–220 KB（gzipped） |
| Dashboard 首屏 LCP（缓存命中） | < 600ms |
| BrainView 首屏（500 CE 图谱） | < 1.5s |
| BigScreen Canvas FPS | ≥ 30 fps（≤ 50 大脑节点） |

### 6.4 端到端

| 流程 | 时长 |
| --- | --- |
| 创建大脑 → 第 1 个 CE 落库 | < 15s |
| 创建大脑 → 主轨收敛（结构化问题） | 8–25 min |
| 创建大脑 → 兜底终止（开放性问题） | 30–60 min |
| 论文生成（含 PDF 渲染） | 30–90s |

---

## 7. 已知问题与 Workaround

### 7.1 当前限制

| 项 | 影响 | 临时 Workaround | 规划 |
| --- | --- | --- | --- |
| 多 worker 大脑状态不共享 | 暂停/恢复请求落到非持锁 worker 时仅修改 DB，需等持锁 worker 下一轮发现 | 重启服务（极少需要），或等待最多 60s | PG advisory lock + 共享内存 |
| HTTP 轮询前端 1–3s 延迟 | 力导向图、观察员叙事略有滞后 | — | WebSocket（路上） |
| 单 SQLite 文件高并发 CE 写入 | 多大脑并行 ≥ 20 时偶现 `database is locked` | 控制并发活跃大脑数 ≤ 10 | PostgreSQL |
| WeasyPrint 中文 fallback | Noto CJK 缺时 PDF 中文方块 | `apt install fonts-noto-cjk` | 同上，已写入运维手册 |
| `arxiv_search` 偶发超时 | 单工具失败 | 已加防御性超时（0.5–5s） | 接入更稳定的 arXiv 镜像 |

### 7.2 历史回归点（出现即说明回退）

- `cognitive_relations.relation`（**不要**写成 `relation_type`）
- `agent_instances.role_key`（**不要**写成 `role`）
- `brains.state`（**不要**写成 `status`）
- `tool_proposal` 字段必须在 `roles.prompt_template` JSON Schema 中**显式声明**，否则 LLM 永远不会输出
- `deliberations` 唯一索引 `uniq_active_deliberation` 必须在创建前查询，避免 UNIQUE 冲突
- 终止逻辑不依赖 `created_by_agent_id IS NOT NULL` 的 JOIN（曾因 NULL 导致上报失败）

### 7.3 不在测试范围

- 旧 v1（scientist/director/researcher + 三轮研究引擎）：兼容运行，新功能不再覆盖；
- APScheduler 定时任务：仅服务旧 v1，不再回归；
- 数据集解析（CSV/JSON/Excel 上传）：兼容层。

---

## 8. CI 建议

```yaml
# .github/workflows/test.yml（建议）
jobs:
  unit:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.10' }
      - run: pip install -r requirements.txt pytest pytest-mock
      - run: pytest tests/unit -q

  api:
    needs: unit
    runs-on: ubuntu-22.04
    services:
      # 真实 DashScope 凭据放 secret，否则跳过
    steps:
      - run: pytest tests/api -q

  frontend:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/setup-node@v4
        with: { node-version: '18' }
      - run: cd frontend && npm ci && npm run build
```

集成测试（`pytest -m slow`）由于真实 LLM 成本与时长，建议本地或夜间任务执行，不进 PR 关键路径。
