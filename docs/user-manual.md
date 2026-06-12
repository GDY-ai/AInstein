# AInstein 使用手册

## 1. 访问系统

### 1.1 入口

```
http://<server-ip>/ainstein/
```

首次访问会看到空的 Dashboard。

### 1.2 浏览器兼容

- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

## 2. Dashboard（首页）

### 2.1 全局统计

顶部三张卡片显示：

- **Projects**：活跃项目数
- **Sessions Completed**：所有项目累计完成的研究会话数
- **Total Findings**：所有项目累计产出的研究发现数

### 2.2 项目卡片

每个项目显示：

- 项目名称
- 研究使命（mission）
- 领域标签（domain）
- 统计徽章：sessions / findings / pending queue

点击卡片进入项目详情。

### 2.3 创建项目

1. 点击右上角 "+ New Project"
2. 填写表单：
   - **Project Name**：项目名（唯一，不可重复）
   - **Research Mission**：长期研究目标（例如："Discover which factors drive short-term stock returns"）
   - **Domain**：领域描述（例如："quantitative finance, stock market, factor investing"）
3. 点击 "Create"

## 3. 项目详情

进入项目后，顶部显示：

- 项目名称 + 使命
- 统计摘要：sessions / findings / validated / pending
- 5 个 tab：Findings / Research Log / Queue / Datasets / AI Team

### 3.1 Findings（研究发现）

显示所有研究发现，每张卡片包含：

- **置信度徽章**：high（绿）/ medium（黄）/ low（灰）
- **类别**：general / factor_efficacy / correlation 等
- **状态**：open / validated / rejected
- **来源**：关联的 session topic
- **发现正文**：研究结论
- **证据**：支持该发现的数据证据
- **行动建议**：如果 actionable=1，显示绿色行动建议

**筛选**：顶部按钮可筛选 All / open / validated / rejected

### 3.2 Research Log（研究日志）

显示所有研究会话，每条包含：

- 状态（completed / failed / running）
- 研究主题
- 耗时（秒）
- 创建时间

**运行研究**：

1. 点击 "Run Research Session"
2. 系统从队列中取出下一个 pending topic
3. 执行三轮研究引擎（约 60-120 秒）
4. 完成后刷新列表

**查看会话详情**：

点击任意会话，展开三轮记录：

- **Data Summary**：数据概要
- **Hypotheses**：生成的假设（H1, H2, ...）
- **Findings**：验证后的发现
- **Next Directions**：建议的后续研究方向

### 3.3 Queue（研究队列）

显示研究队列，表格列：

- Topic：研究主题
- Priority：优先级（P1 最高，P10 最低）
- Source：来源（user / scientist / director / ai_generated）
- Status：状态（pending / picked / completed / failed）
- Created：创建时间

**添加课题**：

1. 在输入框填写研究主题
2. 选择优先级（P1-P10）
3. 点击 "Add"

队列按 status → priority → created_at 排序。研究员每次从 pending 中取优先级最高的。

### 3.4 Datasets（数据集）

显示已上传的数据集，每个卡片包含：

- 文件名
- 行数
- 来源（upload）
- Schema：列名 + 数据类型

**上传数据**：

1. 点击 "Upload Dataset"
2. 选择 CSV / JSON / Excel 文件
3. 系统自动解析 schema（前 100 行推断列类型）
4. 上传完成后刷新列表

**支持格式**：

- `.csv`：逗号分隔
- `.json`：JSON 数组
- `.xlsx`：Excel 工作表

**数据存储**：

每个项目独立目录：`/opt/ainstein/data/datasets/{project_id}/`

### 3.5 AI Team（AI 团队）

显示科学家指令 + 主任记忆，提供手动触发按钮。

**Run Scientist**：

- 分析项目使命 + 可用数据
- 产出 3-7 条战略指令
- 播种 5-10 个初始研究课题
- 定义领域特定的 finding 类别
- 建议：项目创建时跑一次，之后每周一自动

**Run Director**：

- 审核最近 5 个 session 的 findings
- 验证高质量发现（p < 0.05, 大效应）
- 拒绝统计噪声
- 调整队列优先级
- 追加后续研究课题
- 积累记忆（insight / pattern / warning / decision）
- 写 daily briefing
- 建议：每日 10:00 UTC 自动，也可手动触发

**Scientist Directives**：

显示当前活跃的战略指令，每条包含：

- 指令描述
- 优先级（P1-P10）

**Director Memory**：

显示主任积累的记忆，每条包含：

- 类型（insight / pattern / warning / decision / scientist_strategy / briefing）
- 内容
- 创建时间

## 4. 研究工作流

### 4.1 完整流程

```
1. 创建项目 → 设定使命和领域
2. 上传数据集 → CSV/JSON
3. 运行科学家 → 生成战略 + 初始课题
4. 运行研究员 → 执行研究（自动从队列取题）
5. 运行主任 → 审核发现 + 调整队列
6. 重复 4-5 → 知识库持续积累
```

### 4.2 自动化

系统自动执行：

- **研究员**：每日 03:30 UTC，遍历所有 active 项目
- **主任**：每日 10:00 UTC，遍历所有 active 项目
- **科学家**：每周一 06:00 UTC，遍历所有 active 项目

手动触发和自动触发效果相同，可混合使用。

### 4.3 队列管理

- **用户添加**：手动在 Queue tab 添加
- **科学家添加**：项目创建时 + 每周一
- **主任添加**：每日审核时基于 findings 生成后续课题
- **AI 生成**：研究员 session 完成后，next_directions 自动追加到队列

队列自动流转：pending → picked（研究员取走）→ completed / failed

## 5. 最佳实践

### 5.1 项目设计

- **使命要具体**：不要写"研究股票"，写"Discover which factors drive 5-day returns in US mid-cap stocks"
- **领域要宽**：包含相关术语，帮助 LLM 理解上下文
- **数据要充分**：至少 100 行，列名清晰，无缺失值

### 5.2 数据准备

- **列名语义化**：`volume_score` 比 `col_3` 好
- **数值列优先**：统计工具主要处理数值数据
- **避免文本列**：除非用于分组（如 `symbol`, `strategy`）

### 5.3 研究节奏

- **第 1 天**：创建项目 + 上传数据 + 运行科学家
- **第 2-7 天**：每日运行研究员（或等自动调度）
- **第 7 天**：运行主任，审核第一周 findings
- **后续**：让系统自动跑，每周查看 briefing

### 5.4 质量把控

- 定期检查 Findings tab，关注 high confidence 的发现
- 如果主任频繁 reject findings，检查数据质量或使命描述
- 如果队列长期为空，手动添加新课题或重新运行科学家

## 6. 常见问题

### 6.1 研究失败

**现象**：Session 状态为 failed

**原因**：
- LLM API 调用失败（网络 / 配额）
- 数据集不存在或格式错误
- 工具执行异常

**解决**：
- 检查日志：`journalctl -u ainstein -n 50`
- 验证数据集：确保文件在 `data/datasets/{pid}/` 下
- 重试：再次点击 "Run Research Session"

### 6.2 无 findings 产出

**现象**：Session completed 但 findings 为空

**原因**：
- LLM 未生成有效 JSON
- 数据不足以支持假设检验
- 主题过于宽泛

**解决**：
- 检查 session 详情中的 hypotheses 和 verification
- 缩小主题范围，添加更具体的课题
- 上传更多数据

### 6.3 队列不流转

**现象**：队列长期 pending，无人研究

**原因**：
- 研究员调度未启动（检查 APScheduler 日志）
- 所有 worker 都没拿到调度锁

**解决**：
- 检查日志：`journalctl -u ainstein | grep scheduler`
- 重启服务：`systemctl restart ainstein`
- 手动触发：点击 "Run Research Session"

### 6.4 前端加载慢

**现象**：页面加载超过 3 秒

**原因**：
- 首次访问，JS 未缓存
- 网络慢

**解决**：
- 刷新页面，利用浏览器缓存
- 检查 Nginx 是否配置了 `expires 30d` for assets

## 7. 键盘快捷键

暂无（前端未实现）

## 8. 数据导出

暂无内置导出功能。如需导出：

```bash
# 导出 findings
sqlite3 -header -csv /opt/ainstein/data/ainstein.db \
  "SELECT * FROM research_findings WHERE project_id=1" > findings.csv

# 导出 sessions
sqlite3 -header -csv /opt/ainstein/data/ainstein.db \
  "SELECT * FROM research_sessions WHERE project_id=1" > sessions.csv
```
