# 将编排器拆分为模块化包结构

_来源：76b5166 → 6a45874 提交周期内记录的编码计划——内容为规划时意图，实现可能滞后或有出入。_

**状态：** accepted

## 背景
原有的 orchestrator.py 单文件达到 3848 行，严重违反单一职责原则，导致维护困难且容易引入 Bug。为了在不影响生产运行的前提下提升代码质量，需要对其进行结构性重构。

## 决策驱动
- 单一职责原则
- 降低认知负荷
- 便于独立测试与维护

## 备选方案
- **保持单文件 orchestrator.py** _（已否决）_ — 优点：无需迁移成本，文件结构简单；缺点：代码耦合度高，难以定位问题，违反架构最佳实践
- **拆分为 orchestrator/ 包结构** — 优点：按功能域（策略、工具提案、主脑协调、博弈触发）分离关注点，常量集中管理，符合模块化设计；缺点：需要谨慎处理模块间依赖和导入顺序，迁移过程需确保生产稳定性

## 决策
采用模块化包结构重构编排器。将原单文件拆分为 orchestrator/__init__.py (主类), strategy.py, tool_proposal.py, master_coordinator.py, deliberation_trigger.py 和 constants.py。迁移顺序定为：constants → tool_proposal → master_coordinator → strategy → deliberation_trigger，以确保依赖正确且风险可控。

## 影响
代码结构更加清晰，各功能模块职责明确，有利于后续功能的扩展和 Bug 修复。但引入了模块间调用的开销，且需要在重构期间严格验证以确保生产环境无回归错误。