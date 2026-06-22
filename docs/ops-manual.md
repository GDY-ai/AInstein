# AInstein 运维手册（v3.1+）

> 面向部署、运维、SRE。介绍 AInstein 当前的生产部署形态、服务管理、数据库运维、监控要点、常见故障排查与扩容路径。
>
> 配套阅读：[design.md](./design.md)、[testing.md](./testing.md)、[user-manual.md](./user-manual.md)。

---

## 1. 部署清单

### 1.1 服务器

| 项 | 值 |
| --- | --- |
| 提供商 | 阿里云 ECS |
| 区域 | Virginia |
| 公网域名 | `hub.circlegpu.com`（路径前缀 `/ainstein/`） |
| 操作系统 | Ubuntu 22.04 |
| 默认用户 | `root` |
| Python | 3.10+（必须使用项目 `venv`） |
| Node.js | 18+（仅前端构建机需要） |

### 1.2 路径布局

```
/opt/ainstein/                     # 应用根目录
├── wsgi.py                        # Gunicorn 入口（文件锁 + ATA + 主脑初始化）
├── app.py                         # Flask 路由（~52 端点）
├── auth.py                        # JWT + bcrypt + 强密码
├── config.py                      # 环境变量读取
├── database.py                    # SQLite Schema + DAO
├── cognitive.py                   # CE / CR CRUD + 状态机
├── event_bus.py                   # 单例事件总线
├── deliberation.py                # 三轨博弈引擎
├── observer.py                    # 上帝视角叙事
├── brain_summary.py               # 思考结束总结 + 上报主脑
├── master_brain_tactics.py        # 创世主脑战术
├── paper_generator.py             # WeasyPrint PDF
├── paper_template.css             # 论文样式
├── orchestrator/                  # ATA 编排器（Mixin 包）
│   ├── __init__.py
│   ├── core.py                    # _brain_loop / 状态机 / 调度入口
│   ├── strategy.py                # 自调节闭环（收敛/异质性/问题优先）
│   ├── deliberation_trigger.py    # 自动博弈触发
│   ├── tool_proposal.py           # 工具博弈
│   ├── master_coordinator.py      # 分支→主脑上报
│   └── constants.py               # 阈值/角色/事件映射
├── agents/                        # Agent 框架 + 6 角色
├── tools/                         # 11 工具（外部数据 + 统计）
├── prompts/                       # 角色 prompt 模板
├── frontend/
│   ├── dist/                      # 构建产物（Nginx 直接 alias）
│   └── src/                       # React 源码
├── data/
│   ├── ainstein.db                # SQLite WAL 主库
│   └── datasets/                  # 用户上传数据（兼容层）
└── venv/                          # Python 虚拟环境（项目独占解释器）

/etc/ainstein.env                  # 环境变量（API Key 等，权限 600）
/etc/systemd/system/ainstein.service
/etc/nginx/sites-enabled/service-hub.conf
/tmp/ainstein-scheduler.lock       # 多 worker 同步锁（fcntl flock）
```

### 1.3 端口与域名

| 层 | 监听 | 暴露 |
| --- | --- | --- |
| Gunicorn | `127.0.0.1:9089` | 仅本地 |
| Nginx | `0.0.0.0:443` | 公网 HTTPS |
| 前端入口 | `https://hub.circlegpu.com/ainstein/` | 公网 |
| API 前缀 | `https://hub.circlegpu.com/ainstein/api/` | 公网 |

### 1.4 关键环境变量（`/etc/ainstein.env`）

```bash
DASHSCOPE_API_KEY=<your-dashscope-key>
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/api/v2/apps/anthropic
RESEARCH_MODEL=kimi-k2.6
JWT_SECRET=<128 位随机字符串>

# ── v3.2 新增 ─────────────────────────────────
# GitHub OAuth（一键登录）—— 缺失时仅禁用 GitHub 登录入口，不影响主流程
GITHUB_OAUTH_CLIENT_ID=<github-app-client-id>
GITHUB_OAUTH_CLIENT_SECRET=<github-app-client-secret>

# 飞书群机器人 Webhook（主脑日报推送）—— 缺失时主脑日报仅生成不外推
FEISHU_WEBHOOK_URL=<feishu-webhook-url>

# 可选：
# AINSTEIN_DB_PATH=/opt/ainstein/data/ainstein.db
# AINSTEIN_LOG_LEVEL=INFO
```

| 变量 | 说明 | 缺失行为 |
| --- | --- | --- |
| `GITHUB_OAUTH_CLIENT_ID` | GitHub OAuth App Client ID | 前端隐藏「使用 GitHub 登录」按钮 |
| `GITHUB_OAUTH_CLIENT_SECRET` | GitHub OAuth App Client Secret | 同上 |
| `FEISHU_WEBHOOK_URL` | 飞书群机器人 Webhook 地址（主脑日报推送） | 仅落库 + RSS，不推送飞书 |

> ⚠️ **务必 chmod 600**。systemd 通过 `EnvironmentFile=/etc/ainstein.env` 注入。

### 1.5 定时任务

| 任务 | Cron | 实现 | 防重 |
| --- | --- | --- | --- |
| `scheduled_master_digest` | 每日 **08:00 UTC**（北京 16:00） | 创世主脑生成跨域日报 + 飞书推送 | 文件锁 `/tmp/ainstein_digest.lock` |

> 任务由 ATA 持锁 worker 内的调度器触发，跨 worker 文件锁保证当日仅执行一次。锁残留时手动清理：`rm -f /tmp/ainstein_digest.lock`。

---

## 2. 服务管理

### 2.1 systemd 单元

`/etc/systemd/system/ainstein.service`：

```ini
[Unit]
Description=AInstein Silicon Brain
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/ainstein
EnvironmentFile=/etc/ainstein.env
ExecStart=/opt/ainstein/venv/bin/gunicorn \
    -w 2 -b 127.0.0.1:9089 --timeout 300 \
    --access-logfile - --error-logfile - \
    wsgi:application
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 2.2 启停命令

```bash
systemctl start ainstein
systemctl stop ainstein
systemctl restart ainstein           # 99% 场景用这个
systemctl status ainstein
systemctl reload-or-restart ainstein # 修改 env 后

# 修改 unit 文件后
systemctl daemon-reload
systemctl restart ainstein
```

### 2.3 日志

```bash
# 实时跟踪
journalctl -u ainstein -f

# 最近 200 行
journalctl -u ainstein -n 200 --no-pager

# 按时间窗口
journalctl -u ainstein --since "1 hour ago"
journalctl -u ainstein --since "2026-06-14 10:00" --until "2026-06-14 12:00"

# 关键词过滤
journalctl -u ainstein -n 1000 | grep -E "brain_loop|ATA|deliberation|ERROR"

# 大脑思考节律
journalctl -u ainstein -f | grep -E "brain_id=|cycle|frontier|deliberation"

# 主脑战术触发
journalctl -u ainstein --since "today" | grep -E "master_brain|内博弈|跨域综合|元认知"
```

### 2.4 进程与端口

```bash
ps aux | grep gunicorn                  # 应有 1 master + 2 worker
ss -ltnp | grep 9089                    # gunicorn 监听
cat /tmp/ainstein-scheduler.lock        # 持锁 worker PID
ps -p $(cat /tmp/ainstein-scheduler.lock) || echo "锁失效"
```

---

## 3. 数据库运维

SQLite WAL，路径 `/opt/ainstein/data/ainstein.db`。

### 3.1 v3 主线表

| 表名 | 作用 |
| --- | --- |
| `brains` | 大脑实例（含创世主脑 id=1） |
| `cognitive_elements` | CE 节点（13 种类型） |
| `cognitive_relations` | CE 关系（10+ 种 relation） |
| `roles` | 6 角色定义 + prompt 模板 |
| `agent_instances` | Agent 实例（按 `brain_id` 隔离） |
| `deliberations` / `deliberation_turns` / `deliberation_votes` | 博弈引擎三件套 |
| `events` / `event_consumption` | 事件总线持久化 + 幂等消费 |
| `observer_logs` | 观察员叙事日志 |
| `brain_snapshots` | 周期性指标快照 |
| `users` | JWT 鉴权（bcrypt） |

> 关键字段名（容易踩坑，已沉淀进开发记忆）：
> - `brains.state`（不是 `status`）
> - `cognitive_relations.relation`（不是 `relation_type`）
> - `agent_instances.role_key`（不是 `role`）

兼容层（旧 v1）：`projects` / `scientist_directives` / `research_queue` / `research_sessions` / `research_findings` / `director_memory` / `datasets`。仍保留，新功能不再写入。

### 3.2 常用查询

```bash
sqlite3 /opt/ainstein/data/ainstein.db
```

```sql
-- 列出所有大脑及状态
SELECT id, name, state, owner_user_id, started_at, last_active_at
FROM brains ORDER BY id;

-- 创世主脑健康度
SELECT
  (SELECT COUNT(*) FROM cognitive_elements WHERE brain_id=1) AS ce_count,
  (SELECT COUNT(*) FROM cognitive_relations WHERE brain_id=1) AS cr_count,
  (SELECT COUNT(*) FROM agent_instances WHERE brain_id=1 AND status='active') AS agents;

-- 某大脑最近 20 个 CE
SELECT id, type, status, confidence, substr(content, 1, 60) AS preview, created_at
FROM cognitive_elements
WHERE brain_id = ?
ORDER BY id DESC LIMIT 20;

-- CE 类型分布
SELECT type, COUNT(*) AS n
FROM cognitive_elements WHERE brain_id = ?
GROUP BY type ORDER BY n DESC;

-- 进行中的博弈
SELECT id, brain_id, target_ce_id, status, outcome, started_at
FROM deliberations WHERE status != 'resolved';

-- 博弈结果分布
SELECT outcome, COUNT(*) FROM deliberations
WHERE brain_id = ? AND status='resolved'
GROUP BY outcome;

-- 事件队列堆积情况
SELECT type, status, COUNT(*) FROM events
WHERE brain_id = ? GROUP BY type, status;

-- 观察员最近 10 条叙事
SELECT id, kind, title, created_at
FROM observer_logs WHERE brain_id = ?
ORDER BY id DESC LIMIT 10;

-- 大脑收敛指标快照
SELECT created_at, ce_count, relation_count, active_agents, frontier_score
FROM brain_snapshots WHERE brain_id = ?
ORDER BY id DESC LIMIT 20;
```

### 3.3 备份策略

```bash
# 在线备份（推荐，使用 sqlite3 .backup 不阻塞读）
sqlite3 /opt/ainstein/data/ainstein.db \
  ".backup '/opt/ainstein/backups/ainstein_$(date +%Y%m%d_%H%M%S).db'"

# crontab：每日凌晨 3 点备份，保留 14 天
0 3 * * * sqlite3 /opt/ainstein/data/ainstein.db \
  ".backup '/opt/ainstein/backups/ainstein_$(date +\%Y\%m\%d).db'" \
  && find /opt/ainstein/backups -name 'ainstein_*.db' -mtime +14 -delete
```

### 3.4 维护

```bash
# WAL checkpoint（合并 WAL 到主库，定期执行）
sqlite3 /opt/ainstein/data/ainstein.db "PRAGMA wal_checkpoint(TRUNCATE);"

# VACUUM（碎片整理，先停服）
systemctl stop ainstein
sqlite3 /opt/ainstein/data/ainstein.db "VACUUM;"
systemctl start ainstein

# 清理孤立事件（已消费 + 30 天前）
sqlite3 /opt/ainstein/data/ainstein.db \
  "DELETE FROM events WHERE status='consumed'
     AND consumed_at < datetime('now','-30 days');"
```

---

## 4. 前端构建与部署

### 4.1 本地构建

```bash
cd /opt/ainstein/frontend
npm install                         # 首次或 package.json 变更后
npm run build                       # 产物输出到 frontend/dist
```

### 4.2 Nginx 静态服务

```nginx
location ^~ /ainstein/ {
    alias /opt/ainstein/frontend/dist/;
    try_files $uri $uri/ /ainstein/index.html;
    add_header Cache-Control "no-cache" always;
}

location ^~ /ainstein/assets/ {
    alias /opt/ainstein/frontend/dist/assets/;
    expires 30d;
    add_header Cache-Control "public, immutable";
}

location ^~ /ainstein/api/ {
    proxy_pass http://127.0.0.1:9089;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;
    client_max_body_size 50m;
}
```

```bash
nginx -t && systemctl reload nginx
```

> Vite 生成的 assets 文件名带 hash，`index.html` 设 `no-cache` 即可保证客户端拿到最新版本，无需手动清缓存。

---

## 5. 监控要点

### 5.1 大脑是否在思考

```bash
# brain_loop 心跳
journalctl -u ainstein --since "10 min ago" | grep -E "brain_loop|cycle_count" | tail

# 各大脑最近活跃时间
sqlite3 /opt/ainstein/data/ainstein.db \
  "SELECT id, name, state, last_active_at FROM brains
   WHERE state IN ('active','thinking') ORDER BY last_active_at DESC;"

# 最近 5 分钟有无新 CE 落库（任一活跃大脑应当持续产出）
sqlite3 /opt/ainstein/data/ainstein.db \
  "SELECT brain_id, COUNT(*) FROM cognitive_elements
   WHERE created_at > datetime('now','-5 minutes')
   GROUP BY brain_id;"
```

### 5.2 编排器持锁 worker

```bash
# 锁文件存在且 PID 存活 → ATA 正常运行
LOCK_PID=$(cat /tmp/ainstein-scheduler.lock 2>/dev/null)
[ -n "$LOCK_PID" ] && ps -p "$LOCK_PID" > /dev/null \
  && echo "OK: ATA running in PID $LOCK_PID" \
  || echo "WARN: scheduler lock missing or stale"

# 非持锁 worker 不会跑 brain_loop —— 这是设计意图，不是 bug
```

### 5.3 LLM 调用是否正常

```bash
# 最近的 LLM 调用 / 错误
journalctl -u ainstein --since "30 min ago" | grep -E "LLM|DashScope|kimi|rate limit|401|429"

# 手测 LLM 连通性
cd /opt/ainstein && source venv/bin/activate \
  && set -a && source /etc/ainstein.env && set +a \
  && python3 -c "from agents.llm_client import call_llm; \
print(call_llm('kimi-k2.6','You are a test.',[{'role':'user','content':'pong'}])[:120])"
```

### 5.4 创世主脑

```bash
# 主脑必须存在且 active
sqlite3 /opt/ainstein/data/ainstein.db \
  "SELECT id, name, state FROM brains WHERE id=1;"
# 期望：1 | 创世主脑 | active

# 主脑近期是否在吸收上报
sqlite3 /opt/ainstein/data/ainstein.db \
  "SELECT type, COUNT(*) FROM cognitive_elements
   WHERE brain_id=1 AND created_at > datetime('now','-1 day')
   GROUP BY type;"
```

### 5.5 关键告警阈值（建议）

| 指标 | 阈值 | 处置 |
| --- | --- | --- |
| 持锁 worker PID 失效 | 持续 > 1 min | 重启 ainstein |
| `brains.state='active'` 但 5 min 无新 CE | — | 检查 LLM / 锁 |
| `events.status='pending'` 堆积 > 500 | — | 检查发布器 / Agent |
| `cognitive_elements` 单大脑 > 1000 仍未终止 | — | 兜底轨可能未触发，人工检查 |
| LLM 错误率 > 10% | 5 min 滚动 | 配额 / 网络 / 模型切换 |
| 磁盘剩余 < 5G | — | VACUUM + 清理 events / 备份 |

---

## 6. 故障排查

### 6.1 大脑不思考（Active 但无新 CE）

**症状**：`brains.state='active'`，前端图谱不再生长。

**核心定位流程**：

```bash
# 1) 持锁 worker 是否存活？
LOCK_PID=$(cat /tmp/ainstein-scheduler.lock)
ps -p $LOCK_PID || echo "锁失效"
# 失效 → 锁未释放是常见问题
rm -f /tmp/ainstein-scheduler.lock
systemctl restart ainstein

# 2) ATA 编排器是否注册了该大脑？
journalctl -u ainstein --since "10 min ago" | grep "brain_id=$BID"

# 3) LLM 是否在报错？
journalctl -u ainstein -n 500 | grep -E "ERROR|Traceback|rate limit"

# 4) 事件队列是否堵塞？
sqlite3 /opt/ainstein/data/ainstein.db \
  "SELECT status, COUNT(*) FROM events WHERE brain_id=$BID GROUP BY status;"
```

> **唯一会跑 brain_loop 的是持调度锁的那一个 worker**。其它 worker 只处理 HTTP，靠查 DB 看大脑状态。这是当前架构的明确设计。

### 6.2 历史已修问题（出现说明回归）

| 现象 | 原因 | 修复点 |
| --- | --- | --- |
| `UNIQUE constraint failed: deliberations.target_ce_id` | 同一 CE 上多次并发触发博弈 | `_scan_and_trigger_deliberation` 已加内存去重 + DB 唯一索引前置查询 |
| `NameError: params_text` | tool_proposal 参数序列化时变量名错误 | 已统一为 `params_json` |
| `tool_proposal` 字段从未出现 | prompt JSON Schema 没声明 | 角色 `prompt_template` 必须显式声明 `tool_proposal` 字段 |
| `arxiv_search` 卡死整个 worker | 第三方 SDK 阻塞 | 已包裹防御性超时（见 `tools/web_data.py`） |
| 终止后 conclusion 没上报主脑 | `created_by_agent_id` 为 NULL 导致 JOIN 失效 | 上报逻辑改为不依赖 JOIN |
| 共识总是 dissent | 共识阈值 0.667 偏高 | 已下调至 **0.6** |

如这些问题再次出现，先 `git log -- <文件>` 看是否被回滚。

### 6.3 前端 502 / 网关错误

```bash
# Gunicorn 是否在线
ss -ltnp | grep 9089
ps aux | grep gunicorn

# 没在线 → 检查启动日志
journalctl -u ainstein -n 100 --no-pager

# 常见原因：
# - venv 中 Python 解释器路径错误（检查 unit 文件 ExecStart）
# - import 失败（langchain/anthropic/weasyprint 缺依赖）
# - /etc/ainstein.env 权限问题导致环境变量加载失败
```

### 6.4 注册被拒（强密码）

后端校验：8 位以上 + 大小写字母 + 数字 + 特殊字符。前端会先做同样校验。如果用户报告"密码不被接受"，先确认其密码是否同时满足全部 4 项。前后端校验一致。

### 6.5 论文生成失败

```bash
# WeasyPrint 系统依赖（pango/cairo/fontconfig）
ldconfig -p | grep -E "pango|cairo"

# 中文乱码 → Noto CJK 字体
fc-list :lang=zh | head

# 缺失则
apt install -y fonts-noto-cjk fonts-noto-cjk-extra \
  libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b
```

### 6.6 数据库锁竞争（"database is locked"）

罕见。SQLite WAL 已大幅缓解，仍偶发：

```bash
# 检查长事务
sqlite3 /opt/ainstein/data/ainstein.db "PRAGMA wal_checkpoint(TRUNCATE);"

# worker 数过多会加剧 → 维持 -w 2
```

---

## 7. 更新部署流程

> 用户同时使用 Cursor (CC) 编辑代码并推送到 GitHub。**部署前务必先 `git pull`**。

### 7.1 标准流程（小改）

```bash
# 1. 拉代码
ssh root@<server>
cd /opt/ainstein
git pull origin master

# 2. 后端依赖（如 requirements.txt 变更）
source venv/bin/activate
pip install -r requirements.txt

# 3. 前端构建（如 frontend/ 变更）
cd /opt/ainstein/frontend
npm install
npm run build

# 4. 重启服务
systemctl restart ainstein

# 5. 烟囱测试
curl -s https://hub.circlegpu.com/ainstein/api/health
```

### 7.2 跨机器同步（rsync）

本地有改动尚未推 GitHub 时：

```bash
# 排除大型/敏感目录
rsync -avz --delete \
  --exclude='.git' --exclude='venv' --exclude='node_modules' \
  --exclude='data/' --exclude='__pycache__' --exclude='.DS_Store' \
  /Users/.../ainstein/ root@<server>:/opt/ainstein/

ssh root@<server> "cd /opt/ainstein/frontend && npm run build && systemctl restart ainstein"
```

### 7.3 数据库 Schema 变更

```bash
# 1. 备份
sqlite3 /opt/ainstein/data/ainstein.db ".backup '/opt/ainstein/backups/before_migrate.db'"

# 2. 迁移脚本（手写 ALTER TABLE / 索引）
sqlite3 /opt/ainstein/data/ainstein.db < migrate_v3_x.sql

# 3. 验证
sqlite3 /opt/ainstein/data/ainstein.db ".schema cognitive_elements"

# 4. 重启
systemctl restart ainstein
```

> SQLite ALTER TABLE 限制：**索引必须在列添加之后再创建**，否则失败（已踩坑沉淀）。

---

## 8. 扩容与未来规划

### 8.1 当前性能边界

| 资源 | 现状 | 瓶颈 |
| --- | --- | --- |
| Gunicorn worker | 2 | LLM 是慢路径，IO bound，加 worker 收益小 |
| SQLite | 单文件 WAL | 多大脑高频写入接近瓶颈 |
| 状态共享 | 持锁 worker 内存 + DB 轮询 | 跨 worker 暂停/恢复有少量延迟 |
| 实时推送 | HTTP 轮询 | 前端 1-3s 一次拉 |

### 8.2 PostgreSQL 迁移路径

触发条件：单大脑 CE 写入抖动 > 200ms，或并行大脑数 > 20。

```bash
# 1) 安装
apt install postgresql postgresql-contrib
sudo -u postgres createdb ainstein
sudo -u postgres psql -c "CREATE USER ainstein WITH ENCRYPTED PASSWORD '<pwd>';"
sudo -u postgres psql -c "GRANT ALL ON DATABASE ainstein TO ainstein;"

# 2) 迁移（pgloader）
apt install pgloader
pgloader sqlite:///opt/ainstein/data/ainstein.db \
         postgresql://ainstein:<pwd>@localhost/ainstein

# 3) 代码侧
#    - database.py 抽象出 DB 适配层（占位符 ? → %s）
#    - 唯一索引语法 / WHERE 子句的局部索引需重写
#    - 移除 PRAGMA journal_mode=WAL，改用 PG 默认配置
#    - flock 文件锁仍可保留（仍是单机进程协调），或迁移 advisory lock

# 4) 配置
echo "DATABASE_URL=postgresql://ainstein:<pwd>@localhost/ainstein" >> /etc/ainstein.env
```

### 8.3 WebSocket 推送（计划中）

替换前端轮询：

- 后端：Flask-SocketIO 或独立 ASGI worker（uvicorn）订阅 `event_bus`，按 `brain_id` 推；
- 前端：BrainView / ObserverPanel 改为 WS 订阅，HTTP 仅留作初始拉取；
- Nginx：`proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade";`

### 8.4 多服务器横向扩展

仅在 PostgreSQL 迁移完成后才有意义：

- DB：PostgreSQL（共享）；
- 编排器锁：Redis SETNX / PG advisory lock（分布式锁，替代 fcntl）；
- 静态资源：CDN / OSS；
- 状态层：所有大脑的 `BrainState` 主存仍在持锁机器内存，备份在 DB；
- 推送：Redis Pub/Sub 串联 WS 网关。

---

## 附录：紧急操作速查

```bash
# 应急停服
systemctl stop ainstein

# 紧急锁释放 + 重启
rm -f /tmp/ainstein-scheduler.lock && systemctl restart ainstein

# 单脑紧急终止（管理员 token）
curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://hub.circlegpu.com/ainstein/api/brains/<id>/stop

# 主脑误删恢复 —— 主脑由 wsgi.py 启动时自检；删除后重启即重建（id=1）
systemctl restart ainstein

# 一键收集 24h 诊断包
TS=$(date +%Y%m%d_%H%M%S)
mkdir -p /tmp/ainstein-diag-$TS
journalctl -u ainstein --since "24 hours ago" > /tmp/ainstein-diag-$TS/journal.log
cp /etc/systemd/system/ainstein.service /tmp/ainstein-diag-$TS/
cp /etc/nginx/sites-enabled/service-hub.conf /tmp/ainstein-diag-$TS/
sqlite3 /opt/ainstein/data/ainstein.db ".schema" > /tmp/ainstein-diag-$TS/schema.sql
ps auxf | grep -E "gunicorn|ainstein" > /tmp/ainstein-diag-$TS/processes.txt
tar czf /tmp/ainstein-diag-$TS.tgz -C /tmp ainstein-diag-$TS
```
