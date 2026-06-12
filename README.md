# AInstein（爱因思探）

通用 AI 深度研究平台。用户创建研究项目、设定使命，三级 AI（科学家→主任→研究员）自动做数据驱动的深度研究，长期积累知识。

## 核心特性

- **三级 AI 团队**：科学家制定战略、研究员执行分析、主任审核质量
- **三轮研究引擎**：假设生成 → 工具检验 → 验证总结
- **7 种统计工具**：相关性、回归、t 检验、异常检测、分布拟合、分组统计、描述性统计
- **自动化调度**：研究员每日 03:30 UTC、主任每日 10:00 UTC、科学家每周一 06:00 UTC
- **知识库积累**：Findings + Director Memory 持续积累研究洞察
- **领域无关**：通过 `config_json` + prompt 模板变量实现任意领域研究

## 快速开始

### 访问

```
http://<server-ip>/ainstein/
```

### 创建项目

1. 点击 "+ New Project"
2. 填写项目名称、研究使命、领域描述
3. 创建后进入项目详情页

### 上传数据

1. 进入项目 → Datasets tab
2. 点击 "Upload Dataset"，选择 CSV/JSON 文件
3. 系统自动解析 schema 和行数

### 启动研究

1. 进入项目 → AI Team tab
2. 点击 "Run Scientist" 生成战略指令和初始课题
3. 点击 "Run Research Session" 执行一轮研究
4. 点击 "Run Director" 审核发现、调整队列

### 查看结果

- **Findings** tab：所有研究发现，按置信度/类别/状态筛选
- **Research Log** tab：研究会话详情（三轮对话记录）
- **Queue** tab：研究队列管理
- **AI Team** tab：科学家指令 + 主任记忆

## 架构

```
Nginx /ainstein/
    → Gunicorn :9089
        → Flask app
            ├── 科学家 agent（项目创建 + 每周）
            ├── 主任 agent（每日 10:00 UTC）
            ├── 研究员 agent（每日 03:30 UTC）
            │     └── three_round engine
            ├── SQLite（WAL 模式）
            └── datasets/（CSV/JSON）
```

## 技术栈

- **后端**：Flask + Gunicorn + SQLite + APScheduler
- **前端**：React + Vite + TypeScript
- **LLM**：DashScope Anthropic API（kimi-k2.6）
- **部署**：Nginx + systemd

## 目录结构

```
/opt/ainstein/
    wsgi.py              # Gunicorn 入口 + APScheduler
    config.py            # 配置
    database.py          # DB schema + CRUD
    app.py               # Flask 路由
    agents/
        llm_client.py    # DashScope 客户端
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
    prompts/
        scientist.txt    # 科学家 prompt
        director.txt     # 主任 prompt
        researcher.txt   # 研究员 prompt
        three_round.txt  # 三轮引擎 prompt
    frontend/            # React 前端
    data/datasets/{pid}/ # 项目数据文件
```

## 文档

- [设计文档](docs/design.md) — 架构、数据模型、AI 流程
- [使用手册](docs/user-manual.md) — 完整功能说明
- [运维手册](docs/ops-manual.md) — 部署、监控、故障排查
- [测试文档](docs/testing.md) — 测试用例和结果

## License

Private
