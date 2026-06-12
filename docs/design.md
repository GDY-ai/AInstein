# AInstein 设计文档

## 1. 系统概述

### 1.1 目标

构建通用型 AI 深度研究平台。用户创建研究项目、设定使命，三级 AI 自动做数据驱动的深度研究，长期积累知识。

### 1.2 核心原则

- **领域无关**：通过 `config_json` + prompt 模板变量，同一套系统支持金融、医学、社科等任意领域
- **数据驱动**：Phase 1 以统计分析为主，Phase 2 可扩展 ATA（Agent-to-Agent）对话模式
- **持续积累**：Findings + Director Memory 形成知识库，跨 session 传递上下文
- **自动化**：APScheduler 定时触发，无需人工干预

### 1.3 与 us-stock-analyzer 的关系

从 us-stock-analyzer 的研究实验室剥离。原实验室深度耦合股票领域（因子 IC、regime、FACTOR_SIGNS），AInstein 抽象为通用平台。

## 2. 架构

### 2.1 三层架构

```
用户层
    ├── React 前端（Dashboard + ProjectDetail）
    └── REST API

业务层
    ├── Flask app（路由 + 调度）
    ├── 三级 AI Agent（科学家 / 主任 / 研究员）
    ├── 研究引擎（three_round）
    └── 工具链（统计 + 数据访问）

数据层
    ├── SQLite（WAL 模式，7 张表）
    └── datasets/（CSV/JSON 文件）
```

### 2.2 三级 AI 职责

| 级别 | 运行时 | 输入 | 输出 |
|------|--------|------|------|
| 科学家 | 项目创建 + 每周一 | mission + domain + datasets | directives + initial_topics + categories |
| 主任 | 每日 10:00 UTC | recent_sessions + open_findings + queue + memory | findings_review + queue_changes + new_topics + memory + briefing |
| 研究员 | 每日 03:30 UTC | topic + datasets + directives + recent_findings | hypotheses + test_results + findings + next_directions |

### 2.3 三轮研究引擎

```
Round 1: Hypothesis Generation
    LLM → 2-4 testable hypotheses with test_plan

Round 2: Tool-based Testing
    LLM + tools → up to 12 tool calls (descriptive_stats, correlation, regression, etc.)
    Iterative: LLM decides next tool based on previous results

Round 3: Verification + Summary
    LLM → verdicts for each hypothesis + findings + next_directions + data_summary
```

### 2.4 工具链

7 个统计工具，全部接受 `dataset` + `columns` 参数：

| 工具 | 功能 | 返回值 |
|------|------|--------|
| descriptive_stats | 描述性统计 | mean, std, min, max, quartiles |
| correlation | Pearson/Spearman 相关 | r, p_value, n |
| t_test | 独立 t 检验 | t_statistic, p_value, mean_a, mean_b |
| regression | 多元线性回归 | intercept, coefficients, r_squared |
| anomaly_detection | 异常检测（z-score/IQR） | anomalies, anomaly_pct |
| distribution_fit | 正态性检验（Shapiro） | is_normal, skewness, kurtosis |
| group_stats | 分组统计 | per-group count, mean, std, median |

工具注册表 (`tools/registry.py`) 提供 `dispatch(tool_name, params, project_id)` 统一分发。

## 3. 数据模型

### 3.1 核心实体

```
projects (根实体)
    ├── scientist_directives (战略指令)
    ├── research_queue (研究队列)
    │     └── research_sessions (研究会话)
    │           └── research_findings (研究发现)
    ├── director_memory (主任记忆)
    └── datasets (数据集)
```

### 3.2 关键表结构

#### projects

```sql
CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    mission TEXT NOT NULL,           -- 长期研究使命
    domain TEXT NOT NULL,            -- 领域关键词
    config_json TEXT DEFAULT '{}',   -- 引擎、工具、prompt 片段等配置
    status TEXT DEFAULT 'active',
    created_at TEXT DEFAULT (datetime('now'))
);
```

#### research_sessions

```sql
CREATE TABLE research_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    queue_id INTEGER REFERENCES research_queue(id),
    topic TEXT NOT NULL,
    engine_type TEXT DEFAULT 'three_round',
    status TEXT DEFAULT 'running',   -- running / completed / failed / partial
    hypotheses TEXT,                  -- JSON: [{"id": "H1", "statement": "...", ...}]
    verification TEXT,                -- JSON: {"test_results": [...], "verdicts": [...]}
    findings TEXT,                    -- JSON: [{"finding": "...", "confidence": "high", ...}]
    next_directions TEXT,             -- JSON: ["topic1", "topic2"]
    data_summary TEXT,                -- 数据概要
    duration_seconds INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);
```

#### research_findings

```sql
CREATE TABLE research_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    session_id INTEGER REFERENCES research_sessions(id),
    finding TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    confidence TEXT DEFAULT 'low',   -- high / medium / low
    evidence TEXT,
    actionable INTEGER DEFAULT 0,
    action_suggestion TEXT,
    status TEXT DEFAULT 'open',      -- open / validated / rejected
    created_at TEXT DEFAULT (datetime('now'))
);
```

### 3.3 领域抽象

三个层次让系统不绑定任何领域：

1. **`project.config_json`**：每个项目自带领域配置
   ```json
   {
     "domain_vocabulary": ["factor", "regime", "IC"],
     "enabled_tools": ["correlation", "regression", "t_test"],
     "prompt_extra": "Focus on out-of-sample performance.",
     "finding_categories": ["factor_efficacy", "regime_dependence"]
   }
   ```

2. **Prompt 模板变量**：`{mission}`、`{domain}`、`{datasets_summary}` 运行时注入

3. **工具分发**：LLM 输出 `{"tool": "correlation", "params": {"col_a": "volume_score", "col_b": "composite_score"}}`，工具注册表按名称分发，列名来自数据集 schema

## 4. AI 流程

### 4.1 科学家流程

```
输入：
    - mission (string)
    - domain (string)
    - datasets_summary (string)

LLM 调用：
    - system_prompt = scientist.txt.format(mission, domain, datasets_summary)
    - user_message = "Analyze the mission and define the research strategy..."
    - model = kimi-k2.6
    - max_tokens = 3000
    - temperature = 0.7

输出解析：
    {
        "directives": [{"directive": "...", "priority": 1-10}],
        "initial_topics": [{"topic": "...", "priority": 1-10}],
        "finding_categories": ["category1", "category2"],
        "strategic_notes": "..."
    }

存储：
    - scientist_directives 表（每条 directive 一行）
    - research_queue 表（每条 topic 一行，source='scientist'）
    - director_memory 表（kind='scientist_strategy'）
```

### 4.2 研究员流程

```
输入：
    - topic (string, from queue or manual)
    - datasets (list of Dataset objects)
    - directives (list of Directive objects)
    - recent_findings (list of Finding objects)

三轮引擎：

Round 1: Hypothesis Generation
    - system_prompt = three_round.txt + "ROUND 1: HYPOTHESIS GENERATION"
    - user_message = "Research topic: {topic}\n\nGenerate 2-4 testable hypotheses..."
    - LLM 输出 JSON: {"hypotheses": [{"id": "H1", "statement": "...", "test_plan": "..."}]}

Round 2: Tool-based Testing
    - system_prompt = three_round.txt + "ROUND 2: HYPOTHESIS TESTING" + tool list
    - user_message = "Test the hypotheses using data tools..."
    - LLM + tools 循环（最多 12 轮）：
        - LLM 输出 tool_use block
        - 工具执行 → 结果注入 messages
        - LLM 继续决定下一步
    - 收集所有 test_results

Round 3: Verification + Summary
    - system_prompt = three_round.txt + "ROUND 3: VERIFICATION AND CONCLUSIONS"
    - user_message = "Based on the evidence, produce verdicts + findings + next_directions..."
    - LLM 输出 JSON: {"verdicts": [...], "findings": [...], "next_directions": [...], "data_summary": "..."}

存储：
    - research_sessions 表（hypotheses, verification, findings, next_directions, data_summary）
    - research_findings 表（每条 finding 一行）
    - research_queue 表（next_directions 追加，source='ai_generated'）
    - research_queue 表（当前 topic 状态更新为 'completed'）
```

### 4.3 主任流程

```
输入：
    - recent_sessions (last 5 sessions)
    - open_findings (up to 30 findings with status='open')
    - queue (current queue items)
    - memory (last 10 memory entries)

LLM 调用：
    - system_prompt = director.txt.format(mission, domain)
    - user_message = "Daily review for project '{name}':\n\n=== Recent Sessions ===\n...\n=== Open Findings ===\n..."
    - model = kimi-k2.6
    - max_tokens = 4000
    - temperature = 0.5

输出解析：
    {
        "findings_review": [{"finding_id": 1, "action": "validate|reject|keep_open", "reason": "..."}],
        "queue_changes": [{"action": "add|remove|reprioritize", "topic": "...", "priority": 5}],
        "new_topics": [{"topic": "...", "priority": 5, "source": "director"}],
        "memory_entries": [{"kind": "insight|pattern|warning|decision", "content": "..."}],
        "briefing": "2-3 paragraph daily briefing..."
    }

执行：
    - 遍历 findings_review，执行 validate/reject（更新 research_findings.status）
    - 遍历 new_topics，追加到 research_queue（source='director'）
    - 遍历 memory_entries，追加到 director_memory
    - briefing 追加到 director_memory（kind='briefing'）
```

## 5. 调度与并发

### 5.1 APScheduler + 文件锁

```python
# wsgi.py
LOCK_FILE = '/tmp/ainstein-scheduler.lock'

def acquire_scheduler_lock():
    _lock_fd = open(LOCK_FILE, 'a')
    fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    _lock_fd.seek(0)
    _lock_fd.truncate()
    _lock_fd.write(str(os.getpid()))
    return True

if acquire_scheduler_lock():
    start_scheduler()  # 只有拿到锁的 worker 启动调度器
```

Gunicorn 多 worker 场景下，文件锁确保只有一个 worker 运行 APScheduler。

### 5.2 任务配置

```python
scheduler.add_job(scheduled_researcher, 'cron', hour=3, minute=30,
                  id='daily_researcher', max_instances=1, coalesce=True)

scheduler.add_job(scheduled_director, 'cron', hour=10, minute=0,
                  id='daily_director', max_instances=1, coalesce=True)

scheduler.add_job(scheduled_scientist, 'cron', day_of_week='mon', hour=6, minute=0,
                  id='weekly_scientist', max_instances=1, coalesce=True)
```

- `max_instances=1`：同一任务不并行
- `coalesce=True`：错过的执行合并为一次

## 6. 扩展性

### 6.1 Phase 2：ATA 对话模式

```python
# engines/dialogue.py
class DialogueEngine(ResearchEngine):
    """Agent-to-Agent dialogue: researcher discusses with domain expert agent."""
    
    @property
    def engine_type(self):
        return 'dialogue'
    
    def run(self, ctx):
        # 多轮对话：researcher ↔ domain_expert
        # 每轮 LLM 扮演不同角色
        pass
```

### 6.2 新增工具

```python
# tools/registry.py
register_tool('time_series_forecast', ts_tools.forecast, _build_schema(
    'time_series_forecast',
    'Forecast future values using ARIMA/Prophet.',
    {
        'dataset': {'type': 'string'},
        'col': {'type': 'string'},
        'horizon': {'type': 'integer'},
    },
    ['dataset', 'col', 'horizon'],
))
```

### 6.3 新增引擎

```python
# engines/bayesian.py
class BayesianEngine(ResearchEngine):
    """Bayesian hypothesis testing with prior updating."""
    
    @property
    def engine_type(self):
        return 'bayesian'
    
    def run(self, ctx):
        # 先验 → 似然 → 后验
        pass
```

## 7. 安全与隔离

### 7.1 数据隔离

- 每个项目独立目录：`data/datasets/{project_id}/`
- 所有 DB 查询带 `project_id` 过滤
- 文件上传限制在项目目录内

### 7.2 API 安全

- 无认证（内部使用）
- 如需对外，可加 API key 或 OAuth
- `client_max_body_size 50M` 限制上传大小

### 7.3 LLM 安全

- API key 存储在 `/etc/ainstein.env`，权限 600
- 不传给前端
- 不写入日志
