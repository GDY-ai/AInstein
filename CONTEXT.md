# AInstein 项目全局上下文

## 项目概述

AInstein 是一个"硅基大脑"多智能体协作平台，核心理念是让多个 AI Agent 围绕一个"种子问题"进行自主探索、博弈、收敛，最终产出高置信度结论。用户可通过前端可视化界面观察 AI 的思考过程（力导向图）。

- **GitHub**: https://github.com/gaodongyue/ainstein
- **线上访问**: https://hub.circlegpu.com/ainstein/
- **服务器**: 47.253.15.17 (美国 Virginia ECS)，SSH root 登录

---

## 技术栈

- **后端**: Python 3.12, Flask, Gunicorn, SQLite, APScheduler
- **前端**: React + TypeScript + Vite, D3.js (力导向图)
- **LLM**: 通过 anthropic SDK 调用 DashScope 兼容接口
- **部署**: systemd (ainstein.service), Nginx 反代

---

## 服务器关键路径

| 用途 | 路径 |
|------|------|
| 项目根目录 | `/opt/ainstein/` |
| Python 虚拟环境 | `/opt/ainstein/venv/` |
| 数据库 | `/opt/ainstein/data/ainstein.db` |
| 前端构建产物 | `/opt/ainstein/frontend/dist/` |
| 环境变量 | `/etc/ainstein.env` |
| systemd 服务 | `ainstein.service` (EnvironmentFile=/etc/ainstein.env) |
| 日志查看 | `journalctl -u ainstein --no-pager -f` |

---

## 当前 API 配置 (/etc/ainstein.env)

```
DASHSCOPE_API_KEY=sk-ws-H.REXDEYY.mp8r.MEUCIHaT3WepP7ZttEUJpfR5ATmRfzuTFIOtuONd61HXPTyvAiEAzczD00PGkX-ONd_0Z1EadPCWRHg_gL9AnBu9cvg3UkI
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/apps/anthropic
RESEARCH_MODEL=qwen3.7-max-2026-05-17
SCIENTIST_MODEL=qwen3.7-max-2026-05-17
DIRECTOR_MODEL=qwen3.7-max-2026-05-17
```

**重要**: anthropic SDK 0.109+ 会自动在 base_url 后拼 `/v1/messages`，代码中 `llm_client.py` 的 `get_client()` 会剥掉尾部 `/v1` 防止重复。

---

## 核心架构模块

### 编排器 (orchestrator/)
- `core.py` — brain_loop 主循环、收敛检测、双轨终止
- `strategy.py` — 策略调度（收敛压力、置信度传播、前沿探索）
- `constants.py` — 所有阈值常量

### 智能体框架 (agents/)
- `framework.py` — Agent 基类、think()、token 累积追踪
- `llm_client.py` — call_llm() 返回 (text, usage) 元组
- `researcher.py`, `scientist.py`, `director.py` — 三种角色

### 前端 (frontend/src/)
- `pages/BrainView.tsx` — 大脑详情页（力导向图 + 观察员面板）
- `pages/BrainList.tsx` — 大脑列表
- `components/ObserverPanel.tsx` — 观察员视角面板
- `api.ts` — API 通信层
- `types.ts` — TypeScript 类型定义

---

## 关键机制

### Token 预算控制
- 文件: `agents/framework.py` + `orchestrator/constants.py` + `orchestrator/core.py`
- `_BRAIN_TOKEN_BUDGET = 100_000` (每个大脑 100K tokens)
- `_brain_token_usage` dict 追踪每个 brain 的累计 token
- brain_loop 开头检查，超限自动 paused

### 收敛检测 (auto-convergence)
- `_check_convergence()` 在每个 think_cycle 后执行
- 条件: 存在 conclusion CE + confidence > 0.75 + 内容匹配种子关键词(半数以上)
- **防假收敛保护**: `_MIN_CES_FOR_CONVERGENCE = 10`，CE 数量 < 10 时跳过检测
- 主脑永不自动收敛

### 双轨终止策略
- 轨道 1 (正轨): synthesizer 产出 conclusion → 博弈确认 → 置信度传播 → 收敛
- 轨道 2 (兜底): CE ≥ 500 或运行 ≥ 3600s 时强制 synthesizer 总结

### 置信度传播
- 每 10 个 cycle 执行一次 `_propagate_confidence()`
- supports/derives_from 关系拉升 confidence
- refutes/contradicts 关系压低 confidence
- DAMPING = 0.3，单轮传播

### call_llm 返回格式
- 统一返回 `(text, usage_dict)` 元组
- usage_dict = {'input_tokens': N, 'output_tokens': M}
- 所有调用方用 `text, _ = call_llm(...)` 或 `text, usage = call_llm(...)` 解构

---

## 前端轮询机制
- BrainView 每 10 秒轮询 `getKnowledgeGraph(bid)` 更新力导向图
- BrainView 每 10 秒轮询 `getBrain(bid)` 检测 state 变化
- ObserverPanel 每 30 秒轮询观察员日志

---

## 手机端适配 (已完成)
- `isMobile` 状态 (< 768px)
- 手机端: 力导向图占满屏，ObserverPanel 变为底部可最小化抽屉
- 默认最小化(48px)，点击展开到 70vh
- 桌面端布局不变

---

## 数据库字段注意事项
- `brains` 表状态字段是 `state`（不是 status）
- `cognitive_elements` 表类型字段是 `type`（不是 ce_type）
- `cognitive_relations` 表关系字段是 `relation`（不是 type）
- `agent_instances` 表角色字段是 `role_key`（不是 role）

---

## Git 协作规范
- **服务器代码是权威源**，本地修改前先从服务器 pull
- 不能用本地代码覆盖服务器
- 流程: 服务器改 → git add/commit/push → 本地 pull

---

## 服务器操作常用命令

```bash
# SSH 登录
ssh root@47.253.15.17

# 查看日志
journalctl -u ainstein --no-pager -f
journalctl -u ainstein --no-pager --since '5 min ago'

# 重启服务
systemctl restart ainstein

# Python 环境
/opt/ainstein/venv/bin/python3

# 前端构建
cd /opt/ainstein/frontend && npx vite build

# 查看大脑状态
/opt/ainstein/venv/bin/python3 -c "
import database as db
brains = db.list_brains()
for b in brains:
    print(f'Brain #{b[\"id\"]}: state={b[\"state\"]}')
"
```

---

## 待办事项
1. **服务器代码 git commit** — 线上改动（token预算、llm_client返回值改造、收敛保护、手机端适配）尚未提交 git
2. **token 上限可能需要调高** — 当前 100K，大脑跑几分钟就到限

---

## 已知坑点
- anthropic SDK base_url 自动拼 `/v1`，env 里不要带尾部 `/v1`
- 旧版 DashScope US 端点 (`dashscope-us.aliyuncs.com`) 已不可用
- `conclusion` CE 的 `created_by_agent_id` 可能为 NULL（博弈引擎产出时）
- SQLite 迁移中索引创建必须在列添加之后
- SSH 远程加载 env 文件需用 `cat /etc/ainstein.env` 而非 `source`
