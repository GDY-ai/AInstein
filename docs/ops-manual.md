# AInstein 运维手册

## 1. 部署信息

### 1.1 服务器

- **IP**：your-server-ip（廉价 ECS）
- **系统**：Ubuntu 22.04
- **Python**：3.10
- **Node**：22.22.3

### 1.2 路径

```
/opt/ainstein/           # 应用根目录
    wsgi.py              # Gunicorn 入口
    config.py            # 配置
    database.py          # DB
    app.py               # Flask
    agents/              # AI agents
    engines/             # 研究引擎
    tools/               # 统计工具
    prompts/             # Prompt 模板
    frontend/            # React 前端
        dist/            # 构建产物
        src/             # 源码
    data/
        ainstein.db      # SQLite 数据库
        datasets/        # 上传的数据文件
    venv/                # Python 虚拟环境

/etc/ainstein.env        # 环境变量（API key）
/etc/systemd/system/ainstein.service  # systemd 服务
/etc/nginx/sites-enabled/paperplane   # Nginx 配置
```

### 1.3 端口

- **9089**：Gunicorn（127.0.0.1:9089，仅本地）
- **80**：Nginx（对外，反代到 9089）

### 1.4 URL

```
http://your-server-ip/ainstein/          # 前端
http://your-server-ip/ainstein/api/*     # API
```

## 2. 服务管理

### 2.1 启停

```bash
# 启动
systemctl start ainstein

# 停止
systemctl stop ainstein

# 重启
systemctl restart ainstein

# 状态
systemctl status ainstein
```

### 2.2 开机自启

已配置，无需额外操作。

### 2.3 日志

```bash
# 最近 50 行
journalctl -u ainstein -n 50

# 实时跟踪
journalctl -u ainstein -f

# 按时间筛选
journalctl -u ainstein --since "1 hour ago"

# 按关键词筛选
journalctl -u ainstein | grep "LLM\|scheduler\|ERROR"
```

### 2.4 进程

```bash
# 查看 gunicorn 进程
ps aux | grep gunicorn

# 查看端口占用
lsof -i:9089

# 查看调度锁持有者
cat /tmp/ainstein-scheduler.lock
```

## 3. 数据库

### 3.1 位置

```
/opt/ainstein/data/ainstein.db
```

### 3.2 备份

```bash
# 手动备份
cp /opt/ainstein/data/ainstein.db /opt/ainstein/data/ainstein.db.bak.$(date +%Y%m%d_%H%M%S)

# 定时备份（建议加 crontab）
0 2 * * * cp /opt/ainstein/data/ainstein.db /opt/ainstein/backups/ainstein_$(date +\%Y\%m\%d).db

# 导出为 SQL
sqlite3 /opt/ainstein/data/ainstein.db .dump > ainstein_backup.sql
```

### 3.3 恢复

```bash
# 从 .db 文件恢复
systemctl stop ainstein
cp ainstein.db.bak /opt/ainstein/data/ainstein.db
systemctl start ainstein

# 从 SQL 恢复
systemctl stop ainstein
rm /opt/ainstein/data/ainstein.db
sqlite3 /opt/ainstein/data/ainstein.db < ainstein_backup.sql
systemctl start ainstein
```

### 3.4 查询

```bash
# 进入 SQLite
sqlite3 /opt/ainstein/data/ainstein.db

# 常用查询
.tables
SELECT * FROM projects;
SELECT * FROM research_findings WHERE project_id=1 ORDER BY created_at DESC LIMIT 10;
SELECT status, COUNT(*) FROM research_sessions GROUP BY status;
SELECT * FROM director_memory WHERE project_id=1 ORDER BY created_at DESC LIMIT 5;
```

### 3.5 清理

```bash
# 清理 30 天前的 session
sqlite3 /opt/ainstein/data/ainstein.db \
  "DELETE FROM research_sessions WHERE created_at < datetime('now', '-30 days');"

# 清理 rejected findings
sqlite3 /opt/ainstein/data/ainstein.db \
  "DELETE FROM research_findings WHERE status='rejected';"

# VACUUM（释放空间）
sqlite3 /opt/ainstein/data/ainstein.db "VACUUM;"
```

## 4. 前端构建

### 4.1 开发

```bash
cd /opt/ainstein/frontend
npm run dev
# 访问 http://localhost:5173/ainstein/
```

### 4.2 构建

```bash
cd /opt/ainstein/frontend
npm run build
# 产物在 dist/
```

### 4.3 部署

构建后自动部署到 `dist/`，Nginx 直接指向该目录，无需额外操作。

如需强制刷新缓存：

```bash
# 修改前端代码后重新构建
cd /opt/ainstein/frontend
npm run build

# 前端 index.html 已配置 no-cache，assets 有 hash，自动更新
```

## 5. 监控

### 5.1 健康检查

```bash
# API 健康
curl -s http://localhost/ainstein/api/health
# 应返回 {"status":"ok"}

# 外部访问
curl -s http://your-server-ip/ainstein/api/health
```

### 5.2 调度器状态

```bash
# 检查调度器是否启动
journalctl -u ainstein --since "1 hour ago" | grep "APScheduler started"

# 检查锁持有者
cat /tmp/ainstein-scheduler.lock
# 应显示一个 PID

# 验证 PID 是否存活
ps -p $(cat /tmp/ainstein-scheduler.lock)
```

### 5.3 定时任务执行

```bash
# 查看最近的研究会话
sqlite3 /opt/ainstein/data/ainstein.db \
  "SELECT id, topic, status, created_at FROM research_sessions ORDER BY created_at DESC LIMIT 10;"

# 查看最近的主任审核
sqlite3 /opt/ainstein/data/ainstein.db \
  "SELECT id, kind, created_at FROM director_memory WHERE kind='briefing' ORDER BY created_at DESC LIMIT 5;"
```

### 5.4 磁盘空间

```bash
# 数据库大小
ls -lh /opt/ainstein/data/ainstein.db

# 数据集大小
du -sh /opt/ainstein/data/datasets/

# 总占用
du -sh /opt/ainstein/
```

## 6. 故障排查

### 6.1 服务无法启动

**症状**：`systemctl start ainstein` 失败

**排查**：

```bash
# 查看详细错误
journalctl -u ainstein -n 100 --no-pager

# 常见错误：
# - "Address already in use" → 端口被占用
lsof -i:9089
kill <pid>

# - "ModuleNotFoundError" → venv 未激活或依赖缺失
cd /opt/ainstein && source venv/bin/activate && pip install -r requirements.txt

# - "Permission denied" → 文件权限问题
chmod -R 755 /opt/ainstein
chown -R root:root /opt/ainstein
```

### 6.2 LLM 调用失败

**症状**：Session 状态为 failed，日志显示 "LLM call failed"

**排查**：

```bash
# 检查 API key
cat /etc/ainstein.env
# 应有 DASHSCOPE_API_KEY=sk-...

# 手动测试 LLM
cd /opt/ainstein && source venv/bin/activate && set -a && source /etc/ainstein.env && set +a
python3 -c "
from agents.llm_client import call_llm
print(call_llm('kimi-k2.6', 'You are a test.', [{'role':'user','content':'Say hello'}]))
"

# 常见错误：
# - "Could not resolve authentication method" → API key 未加载
# - "ThinkingBlock has no attribute text" → 已修复（llm_client.py 跳过 ThinkingBlock）
# - "rate limit exceeded" → 配额用完，等待或升级套餐
```

### 6.3 调度器不执行

**症状**：到了 03:30 / 10:00 但没有自动研究

**排查**：

```bash
# 检查调度器日志
journalctl -u ainstein --since "03:00" --until "04:00" | grep -i "scheduled\|researcher\|director"

# 检查锁
cat /tmp/ainstein-scheduler.lock
ps -p $(cat /tmp/ainstein-scheduler.lock)

# 如果锁失效，重启服务
rm -f /tmp/ainstein-scheduler.lock
systemctl restart ainstein

# 手动触发（绕过调度器）
curl -X POST http://localhost/ainstein/api/projects/1/sessions/run
curl -X POST http://localhost/ainstein/api/projects/1/director/run
```

### 6.4 前端 404

**症状**：访问 `/ainstein/` 返回 404 或空白页

**排查**：

```bash
# 检查 dist 目录
ls -la /opt/ainstein/frontend/dist/
# 应有 index.html 和 assets/

# 检查 Nginx 配置
nginx -T | grep -A 20 "location.*ainstein"

# 重新构建前端
cd /opt/ainstein/frontend && npm run build

# 重载 Nginx
nginx -s reload
```

### 6.5 数据集上传失败

**症状**：上传 CSV 后 schema 为空或 row_count=0

**排查**：

```bash
# 检查文件是否存在
ls -la /opt/ainstein/data/datasets/{project_id}/

# 检查文件权限
chmod 644 /opt/ainstein/data/datasets/{project_id}/*.csv

# 手动解析测试
cd /opt/ainstein && source venv/bin/activate
python3 -c "
import pandas as pd
df = pd.read_csv('/opt/ainstein/data/datasets/1/analysis_results.csv', nrows=10)
print(df.columns.tolist())
print(df.dtypes)
"

# 常见错误：
# - "FileNotFoundError" → 文件未保存
# - "UnicodeDecodeError" → 编码问题，尝试 encoding='latin1'
```

## 7. 更新部署

### 7.1 更新后端代码

```bash
# 假设新代码在 /tmp/ainstein/
scp /tmp/ainstein/*.py root@your-server-ip:/opt/ainstein/
scp /tmp/ainstein/agents/*.py root@your-server-ip:/opt/ainstein/agents/
scp /tmp/ainstein/engines/*.py root@your-server-ip:/opt/ainstein/engines/
scp /tmp/ainstein/tools/*.py root@your-server-ip:/opt/ainstein/tools/
scp /tmp/ainstein/prompts/*.txt root@your-server-ip:/opt/ainstein/prompts/

systemctl restart ainstein
```

### 7.2 更新前端

```bash
# 本地构建
cd /tmp/ainstein/frontend
npm run build

# 上传 dist
scp -r /tmp/ainstein/frontend/dist root@your-server-ip:/opt/ainstein/frontend/

# 无需重启，Nginx 直接指向 dist/
```

### 7.3 更新依赖

```bash
cd /opt/ainstein
source venv/bin/activate
pip install --upgrade flask gunicorn anthropic apscheduler pandas scipy numpy

systemctl restart ainstein
```

## 8. 性能优化

### 8.1 Gunicorn worker 数

当前：2 workers（廉价 ECS 内存有限）

如需调整：

```bash
# /etc/systemd/system/ainstein.service
ExecStart=/opt/ainstein/venv/bin/gunicorn -w 4 -b 127.0.0.1:9089 --timeout 300 wsgi:application

systemctl daemon-reload
systemctl restart ainstein
```

建议：`workers = 2 * CPU + 1`，廉价 ECS 通常 1-2 CPU。

### 8.2 SQLite 优化

已启用：

```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA foreign_keys=ON")
```

如需进一步优化：

```python
conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
conn.execute("PRAGMA synchronous=NORMAL")
```

### 8.3 Nginx 缓存

已配置：

```nginx
location ^~ /ainstein/assets/ {
    expires 30d;
    add_header Cache-Control "public, immutable";
}
```

前端 index.html 已配置 `no-cache`，确保每次拉取最新版本。

## 9. 安全

### 9.1 API Key

存储在 `/etc/ainstein.env`，权限 600：

```bash
chmod 600 /etc/ainstein.env
chown root:root /etc/ainstein.env
```

### 9.2 数据库

SQLite 文件权限 644，仅 root 可写：

```bash
chmod 644 /opt/ainstein/data/ainstein.db
chown root:root /opt/ainstein/data/ainstein.db
```

### 9.3 防火墙

ECS 安全组应限制：

- 22（SSH）：仅允许特定 IP
- 80（HTTP）：开放
- 9089（Gunicorn）：不开放（仅本地）

## 10. 扩容

### 10.1 数据库迁移

当 SQLite 不够用时，迁移到 PostgreSQL：

```bash
# 1. 安装 PostgreSQL
apt install postgresql

# 2. 创建数据库
sudo -u postgres createdb ainstein

# 3. 迁移数据
pip install pgloader
pgloader sqlite:///opt/ainstein/data/ainstein.db postgresql:///ainstein

# 4. 修改 database.py
# 替换 sqlite3 为 psycopg2
# 修改 SQL 语法（sqlite3 → PostgreSQL）

# 5. 修改 config.py
DB_PATH = os.environ.get('DATABASE_URL', 'postgresql://localhost/ainstein')
```

### 10.2 多服务器

如需横向扩展：

- 数据库：迁移到 PostgreSQL（共享）
- 调度器：改用 Redis + Celery Beat（分布式锁）
- 数据集：迁移到 S3 / OSS（共享存储）
