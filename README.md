# AInstein（爱因思探）

通用 AI 深度研究平台。用户创建研究项目、设定使命，三级 AI（科学家→主任→研究员）自动做数据驱动的深度研究，长期积累知识。

## 核心特性

- **三级 AI 团队**：科学家制定战略、研究员执行分析、主任审核质量
- **三轮研究引擎**：假设生成 → 工具检验 → 验证总结
- **7 种统计工具**：相关性、回归、t 检验、异常检测、分布拟合、分组统计、描述性统计
- **外部数据工具**：Web Search、Wikipedia、arXiv、Google Trends
- **自动化调度**：研究员每日 03:30 UTC、主任每日 10:00 UTC、科学家每周一 06:00 UTC
- **知识库积累**：Findings + Director Memory 持续积累研究洞察
- **领域无关**：通过 `config_json` + prompt 模板变量实现任意领域研究

## 本地开发

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

前端构建产物放在 `frontend/dist/`，配合 Nginx 反代一起使用（详见 `docs/ops-manual.md`）。

## 架构

```
Nginx /ainstein/
    → Gunicorn :9089
        → Flask app
            ├── 科学家 agent（项目创建 + 每周）
            ├── 主任 agent（每日审核）
            ├── 研究员 agent（每日研究）
            │     └── three_round engine
            ├── SQLite（WAL 模式）
            └── datasets/（CSV/JSON）
```

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Flask + Gunicorn + SQLite + APScheduler |
| 前端 | React + Vite + TypeScript |
| LLM | DashScope Anthropic API（默认 kimi-k2.6） |
| 部署 | Nginx + systemd |

## 目录结构

```
ainstein/
    wsgi.py              # Gunicorn 入口 + APScheduler
    config.py            # 配置（全部读环境变量）
    database.py          # DB schema + CRUD
    app.py               # Flask 路由
    .env.example         # 环境变量模板
    agents/
        llm_client.py    # LLM 客户端（Anthropic 协议）
        scientist.py     # 科学家
        director.py      # 主任
        researcher.py    # 研究员编排
    engines/
        base.py          # 引擎基类
        three_round.py   # 三轮引擎
    tools/
        registry.py      # 工具注册
        stats.py         # 统计工具
        data_access.py   # 数据加载
        web_data.py      # 外部数据工具
    prompts/
        scientist.txt    # 科学家 prompt
        director.txt     # 主任 prompt
        researcher.txt   # 研究员 prompt
        three_round.txt  # 三轮引擎 prompt
    frontend/            # React 前端
    data/datasets/{pid}/ # 项目数据文件
    docs/                # 设计 / 运维 / 测试文档
```

## 贡献

欢迎 PR 和 Issue！

1. Fork 本仓库
2. 创建你的分支：`git checkout -b feature/awesome`
3. 提交改动：`git commit -m "Add awesome feature"`
4. 推送：`git push origin feature/awesome`
5. 开 Pull Request

## 文档

- [设计文档](docs/design.md) — 架构、数据模型、AI 流程
- [使用手册](docs/user-manual.md) — 完整功能说明
- [运维手册](docs/ops-manual.md) — 部署、监控、故障排查
- [测试文档](docs/testing.md) — 测试用例和结果

## License

[MIT](LICENSE)
