"""
ATA 编排器 package
================================================================================

为保持与原 ``orchestrator.py`` 100% 接口兼容而存在。对外暴露：

- :class:`ATAOrchestrator` —— 主类（单例）
- :class:`BrainState` —— 大脑运行时状态
- :data:`orchestrator` —— 全局单例
- 模块级便捷接口：``start_brain`` / ``pause_brain`` / ``resume_brain``
  / ``stop_brain`` / ``get_brain_status`` / ``list_active_brains``
- 内部工具：``_summarize_tool_result`` / ``_now_iso``（被 ``engines.three_round`` 等模块引用）

使用方式与拆分前完全一致::

    from orchestrator import ATAOrchestrator, start_brain, orchestrator
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .constants import (
    BrainState,
    _now_iso,
    _summarize_tool_result,
    _EVENT_TO_ROLES,
)
from .core import ATAOrchestrator


# ============================================================
# 模块级便捷接口（保持与原文件一致）
# ============================================================

#: 全局编排器单例
orchestrator: ATAOrchestrator = ATAOrchestrator.instance()


def start_brain(brain_id: int) -> bool:
    """启动一个大脑思考（模块级别捷径）。"""
    return orchestrator.start_brain(brain_id)


def pause_brain(brain_id: int) -> bool:
    """暂停一个大脑思考。"""
    return orchestrator.pause_brain(brain_id)


def resume_brain(brain_id: int) -> bool:
    """恢复一个大脑思考。"""
    return orchestrator.resume_brain(brain_id)


def stop_brain(brain_id: int) -> bool:
    """停止并清理一个大脑。"""
    return orchestrator.stop_brain(brain_id)


def get_brain_status(brain_id: int) -> Optional[Dict[str, Any]]:
    """查询大脑运行状态。"""
    return orchestrator.get_brain_status(brain_id)


def list_active_brains() -> List[Dict[str, Any]]:
    """列出所有活跃大脑。"""
    return orchestrator.list_active_brains()


__all__ = [
    "ATAOrchestrator",
    "BrainState",
    "orchestrator",
    "start_brain",
    "pause_brain",
    "resume_brain",
    "stop_brain",
    "get_brain_status",
    "list_active_brains",
    # 内部工具（保持原 orchestrator.py 模块级可访问性）
    "_summarize_tool_result",
    "_now_iso",
    "_EVENT_TO_ROLES",
]
