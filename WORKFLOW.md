# AInstein 开发工作流

> 本地开发 → GitHub → 一键部署到生产

---

## 🌍 环境总览

| 环境 | 服务器 | 入口 | 用途 |
| --- | --- | --- | --- |
| 开发 (Dev) | 你的 Mac | http://localhost:5173 (Vite) + http://localhost:9089 (Flask) | 写代码 / 调试 |
| 生产 (Prod) | `root@47.253.15.17` (美国 Virginia) | 生产域名 / IP:9089 | 对外服务 |

服务器代码路径为 `/opt/ainstein`，systemd 服务为 `ainstein`，端口 `9089`，环境变量在 `/etc/ainstein.env`，数据库在 `/srv/ainstein/data/ainstein.db`（**不会**被部署脚本覆盖）。

---

## 🚀 日常开发流程

```bash
# 1. 同步最新代码
git pull origin main

# 2. 本地启动后端（终端 A）
flask --app app run --port 9089 --debug
# 或：python -m flask --app app run --port 9089 --debug

# 3. 本地启动前端（终端 B）
cd frontend
npm install        # 仅首次或依赖变化时
npm run dev        # 默认 http://localhost:5173

# 4. 提交代码
git add -A
git commit -m "feat: ..."
git push origin main

# 5. 部署到生产
./scripts/deploy.sh
```

---

## 🛠️ 部署脚本用法

```bash
./scripts/deploy.sh                  # 部署到生产（会要求二次确认）
./scripts/deploy.sh --help           # 查看完整选项

# 常用组合
./scripts/deploy.sh --force          # 跳过 git 干净检查
./scripts/deploy.sh --skip-deps      # 跳过 pip install（依赖未变时加速）
./scripts/deploy.sh --skip-frontend  # 仅同步后端代码
./scripts/deploy.sh --local-build    # 在本地构建前端再 rsync（服务器无 node 时使用）
```

部署脚本会自动完成：

1. 本地 git 状态检查（防止误部署未提交修改）
2. `rsync` 同步代码到 `/opt/ainstein`，**自动排除** `.env`、`HANDOFF.md`、`data/`、`.git/`、`node_modules/`、`__pycache__/`、`*.db` 等敏感/生成文件
3. 远程 `pip3 install -r requirements.txt`
4. 远程 `cd frontend && npm install && npm run build`
5. `systemctl restart ainstein`
6. 健康检查 `curl http://localhost:9089/ainstein/api/health`（最多重试 10 次）
7. 输出部署摘要

---

## 🔐 首次设置

### 1. 配置 SSH 免密登录

```bash
# 如还没有 SSH key
ssh-keygen -t ed25519 -C "your_email@example.com"

# 推送到生产服务器
ssh-copy-id root@47.253.15.17

# 测试连接
ssh root@47.253.15.17 'echo OK'
```

### 2. 服务器侧前置条件（已配置则跳过）

- `/opt/ainstein` 目录存在
- systemd unit `ainstein.service` 已就绪，`EnvironmentFile=/etc/ainstein.env`
- `/etc/ainstein.env` 包含 `DASHSCOPE_API_KEY` 等敏感配置
- `python3` (3.10+) 与 `node` (建议 18+) 可用
- 数据库目录 `/srv/ainstein/data/` 可写

### 3. 给脚本执行权限

```bash
chmod +x scripts/deploy.sh
```

---

## ⚠️ 注意事项

- **永远不要**把 `HANDOFF.md`、`.env`、`data/`、`*.db` 提交到 git；`.gitignore` 已覆盖。
- 部署脚本通过 `rsync --delete` 同步，但带有完整 exclude 列表，**不会**删除服务器上的 `data/`、`.env`。
- 生产环境部署前会要求输入 `yes` 二次确认；自动化场景可用 `./scripts/deploy.sh --force` 配合非交互式输入跳过。
- 数据库迁移：脚本不会自动迁移 schema。如有 schema 变更，登陆服务器手动执行 SQL 后再部署。
- 部署期间会有约 3-5 秒的服务中断（systemctl restart）。

---

## 🩺 故障排查

```bash
# 实时查看服务日志
ssh root@47.253.15.17 'journalctl -u ainstein -f'

# 查看最近 100 行日志
ssh root@47.253.15.17 'journalctl -u ainstein -n 100 --no-pager'

# 服务状态
ssh root@47.253.15.17 'systemctl status ainstein'

# 健康检查
ssh root@47.253.15.17 'curl -s http://localhost:9089/ainstein/api/health'

# 紧急回滚：本地切到旧 commit 后重新部署
git checkout <old-sha>
./scripts/deploy.sh --force
git checkout main
```

---

## 📦 仓库

- GitHub: https://github.com/GDY-ai/AInstein
- 主分支: `main`
