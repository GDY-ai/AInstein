"""
AInstein Agent 框架（Silicon Brain Blueprint §1.2 / §2.3）
==========================================================

设计哲学
--------
- **去层级化**：所有 Agent 完全平等，无上下级关系；角色仅是「思考视角」。
- **角色 = 视角**：不同角色代表不同的思维偏好与专长，不代表权力。
- **动态化**：Agent 可被动态 spawn / despawn / transform_role；同一 Role 可有
  多个不同性格的 Instance，从而在博弈中产生思维多样性。
- **数据驱动**：Agent 的行为由事件触发（react_to_event），其产出统一为
  「认知元素（CE）」入图，再次驱动新事件。

模块结构
--------
1. ``ROLES`` —— 6 种功能性角色的静态定义。
2. ``ThinkingContext`` / ``ThinkingResult`` —— 思考的输入输出数据类。
3. ``RoleRegistry`` —— 角色配置注册（数据库持久化 + 内存缓存）。
4. ``BaseAgent`` —— 所有 Agent 的统一基类，封装 think / react_to_event /
   participate_in_deliberation / get_perspective_prompt 等核心能力。
5. ``AgentPool`` —— Instance 的生命周期管理（spawn / despawn / transform）。

与现有模块的协作
----------------
- ``agents.llm_client``：``call_llm`` / ``call_llm_with_tools`` / ``extract_json``
- ``cognitive``：``create_element`` / ``create_relation``
- ``event_bus``：``EventBus.publish`` / ``EventBus.subscribe``
- ``database``：roles / agent_instances 表持久化（``upsert_role`` / ``spawn_agent_instance`` 等）

向后兼容
--------
现有 ``agents/scientist.py`` / ``agents/director.py`` / ``agents/researcher.py``
保留不动；新框架完全独立。
"""
from __future__ import annotations

import json
import logging
import random
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import database as db
import cognitive
from agents.llm_client import call_llm, extract_json
from event_bus import EventBus, EventTypes
from config import RESEARCH_MODEL

logger = logging.getLogger(__name__)


# ============================================================
# 6 种功能性角色定义（Silicon Brain Blueprint §1.2.3）
# ============================================================
#: 角色配置静态表。``RoleRegistry.init_default_roles`` 会把它写入 ``roles`` 表。
ROLES: Dict[str, Dict[str, Any]] = {
    "explorer": {
        "name_cn": "探索者",
        "description": "发现新问题、提出新方向、拓展认知边界",
        "perspective_bias": "好奇心驱动，偏向发散思维，善于提出'为什么'和'如果...'",
        "preferred_ce_types": ["question", "observation", "hypothesis"],
        "default_quota_min": 1,
        "default_quota_max": 2,
    },
    "investigator": {
        "name_cn": "调查者",
        "description": "收集证据、验证假设、执行数据分析",
        "perspective_bias": "严谨求证，偏向工具使用和数据收集",
        "preferred_ce_types": ["evidence", "counter_evidence", "observation"],
        "default_quota_min": 1,
        "default_quota_max": 4,
    },
    "reasoner": {
        "name_cn": "推理者",
        "description": "逻辑推导、构建论证、形成结论",
        "perspective_bias": "逻辑优先，注重因果链和论证完整性",
        "preferred_ce_types": ["inference", "argument", "conclusion"],
        "default_quota_min": 1,
        "default_quota_max": 3,
    },
    "critic": {
        "name_cn": "批评者",
        "description": "质疑假设、发现漏洞、提出反驳",
        "perspective_bias": "怀疑论倾向，寻找反例和逻辑漏洞",
        "preferred_ce_types": ["counter_evidence", "dissent"],
        "default_quota_min": 1,
        "default_quota_max": 2,
    },
    "synthesizer": {
        "name_cn": "综合者",
        "description": "整合多方观点、发现跨领域洞察、构建统一叙事",
        "perspective_bias": "全局视角，寻找模式和联系",
        "preferred_ce_types": ["insight", "perspective", "consensus"],
        "default_quota_min": 0,
        "default_quota_max": 1,
    },
    "observer": {
        "name_cn": "观察员",
        "description": "监控大脑状态、总结思考进展、生成用户报告",
        "perspective_bias": "元认知视角，关注思考过程而非内容",
        "preferred_ce_types": ["insight"],
        "default_quota_min": 1,
        "default_quota_max": 1,
    },
}


# ============================================================
# 数据类
# ============================================================

@dataclass
class ThinkingContext:
    """一次「思考」所需的上下文。

    由调用方（事件处理器或 ATA 编排器）按需装配，再交给 ``BaseAgent.think``。
    """

    brain_id: int
    """所属硅基大脑 id。"""

    research_topic: str = ""
    """大脑的核心研究课题（即用户提出的种子问题原文）。所有思考必须围绕它展开。"""

    trigger_event: Optional[Dict[str, Any]] = None
    """触发本次思考的事件对象（与 EventBus dispatch 出的 dict 同结构）。"""

    relevant_ces: List[Dict[str, Any]] = field(default_factory=list)
    """与本次思考相关的认知元素（已 hydrate，含 payload）。"""

    recent_observations: List[Dict[str, Any]] = field(default_factory=list)
    """最近若干条 observation 类型的 CE，作为现实锚点。"""

    current_frontier: List[Dict[str, Any]] = field(default_factory=list)
    """当前认知边界候选（未被支撑 / 低置信度元素）。"""

    extra: Dict[str, Any] = field(default_factory=dict)
    """扩展字段（角色特定的额外提示，如博弈议题等）。"""


@dataclass
class ThinkingResult:
    """一次「思考」的产出。

    Agent 不直接写库；本类只描述「想做什么」，由调用者落库或转事件。
    ``BaseAgent.think`` 默认会调用 ``_persist_result`` 把 new_elements /
    new_relations 持久化，并发布对应事件。
    """

    new_elements: List[Dict[str, Any]] = field(default_factory=list)
    """产出的新认知元素，每条形如：

    .. code-block:: json

        {
          "type": "hypothesis",
          "title": "可选标题",
          "content": "命题主体...",
          "confidence": 0.6,
          "domain_tags": ["health"],
          "metadata": {"reasoning": "..."}
        }
    """

    new_relations: List[Dict[str, Any]] = field(default_factory=list)
    """产出的新关系；每条 ``{source_index|source_id, target_index|target_id,
    relation, weight}``。``*_index`` 指 new_elements 中的下标；``*_id`` 指既有 CE id。"""

    suggested_events: List[Dict[str, Any]] = field(default_factory=list)
    """建议发布的事件，``{type, payload}``；``BaseAgent.think`` 会自动发布。"""

    deliberation_request: Optional[Dict[str, Any]] = None
    """是否需要发起一次博弈讨论；非 None 时形如
    ``{"target_ce_id": int, "motion": str}``。"""

    tool_proposal: Optional[Dict[str, Any]] = None
    """工具调用提案；非 None 时形如
    ``{"tool": str, "params": dict, "reason": str}``，由 orchestrator 接管轻量级
    博弈与执行，结果以 ``evidence`` CE 注入。"""

    raw_text: str = ""
    """LLM 原始输出文本（调试用）。"""


# ============================================================
# 角色注册表
# ============================================================

class RoleRegistry:
    """角色配置注册表（线程安全的内存缓存 + 数据库持久化）。

    - ``register_role`` / ``init_default_roles`` 写库；
    - ``get_role`` / ``list_roles`` 优先读内存，必要时回查 DB。
    """

    _lock = threading.RLock()
    _cache: Dict[str, Dict[str, Any]] = {}
    _initialized: bool = False

    # ---------- 注册 ----------
    @classmethod
    def register_role(
        cls,
        role_name: str,
        config: Dict[str, Any],
    ) -> int:
        """注册（或更新）一个角色到 ``roles`` 表，并刷入缓存。

        :param role_name: 角色 key，如 ``"explorer"``。
        :param config: 角色配置字典；至少应含 ``description``。
            可选字段：``perspective_bias`` / ``preferred_ce_types`` /
            ``prompt_template`` / ``default_quota_min`` / ``default_quota_max``。
        :return: 数据库中该角色的 id。
        """
        if not role_name or not isinstance(config, dict):
            raise ValueError("role_name 与 config 不可为空")

        prompt_template = config.get("prompt_template") or _build_role_prompt(role_name, config)
        role_id = db.upsert_role(
            role_key=role_name,
            prompt_template=prompt_template,
            description=config.get("description", ""),
            default_quota_min=int(config.get("default_quota_min", 0) or 0),
            default_quota_max=int(config.get("default_quota_max", 4) or 4),
        )

        merged = dict(config)
        merged["role_key"] = role_name
        merged["role_id"] = role_id
        merged["prompt_template"] = prompt_template

        with cls._lock:
            cls._cache[role_name] = merged
        logger.info("角色已注册: %s (id=%s)", role_name, role_id)
        return role_id

    # ---------- 查询 ----------
    @classmethod
    def get_role(cls, role_name: str) -> Optional[Dict[str, Any]]:
        """获取角色配置（含 prompt_template / role_id）。

        优先从缓存读取；缓存未命中时回查 DB 并按 ``ROLES`` 静态配置补全。
        """
        if not role_name:
            return None
        with cls._lock:
            cached = cls._cache.get(role_name)
        if cached:
            return dict(cached)

        row = db.get_role(role_name)
        if not row:
            # 数据库尚未持久化，但属于内置 6 角色 → 返回静态配置
            static = ROLES.get(role_name)
            if static:
                return {**static, "role_key": role_name, "role_id": None,
                        "prompt_template": _build_role_prompt(role_name, static)}
            return None

        merged = dict(ROLES.get(role_name, {}))
        merged.update({
            "role_key": row["role_key"],
            "role_id": row["id"],
            "description": row.get("description") or merged.get("description", ""),
            "prompt_template": row["prompt_template"],
            "default_quota_min": row.get("default_quota_min"),
            "default_quota_max": row.get("default_quota_max"),
        })
        with cls._lock:
            cls._cache[role_name] = merged
        return dict(merged)

    @classmethod
    def list_roles(cls) -> List[Dict[str, Any]]:
        """列出所有已知角色（合并静态 ``ROLES`` 与数据库中的角色）。"""
        keys = set(ROLES.keys())
        with cls._lock:
            keys.update(cls._cache.keys())
        return [r for r in (cls.get_role(k) for k in sorted(keys)) if r]

    # ---------- 默认初始化 ----------
    @classmethod
    def init_default_roles(cls, force: bool = False) -> Dict[str, int]:
        """把内置 6 种角色写入 ``roles`` 表（幂等）。

        :param force: 为 True 时即使已初始化过也重新写一遍；默认 False，
            进程内只跑一次。
        :return: ``{role_key: role_id}`` 映射。
        """
        with cls._lock:
            if cls._initialized and not force:
                return {k: v.get("role_id") for k, v in cls._cache.items()
                        if v.get("role_id") is not None}

        result: Dict[str, int] = {}
        for role_name, config in ROLES.items():
            try:
                role_id = cls.register_role(role_name, config)
                if role_id is not None:
                    result[role_name] = role_id
            except Exception:
                logger.exception("初始化角色失败: %s", role_name)

        with cls._lock:
            cls._initialized = True
        logger.info("默认角色初始化完成: %s", result)
        return result

    @classmethod
    def reset_cache(cls) -> None:
        """清空内存缓存（主要用于测试）。"""
        with cls._lock:
            cls._cache.clear()
            cls._initialized = False


# ---------- prompt 构建辅助 ----------
# 角色专属行为补充（被 _build_role_prompt 插入到「认知元素类型」之后）
# critic 需要主动发起博弈、防止「虚假和谐」——宁可多质疑一次也不能放过可疑结论。
_ROLE_BEHAVIOR_ADDONS: Dict[str, str] = {
    "critic": """
# 行为触发规则
- 当你看到一个 hypothesis 或 conclusion 的置信度 < 0.7 但没有对应的 counter_evidence 时，主动提出质疑
- 当你看到 consensus 是在缺乏充分证据支撑的情况下达成的，必须产出 dissent
- 你的存在价值是防止「虚假和谐」——宁可多质疑一次，也不可放过可疑的结论
- 在 deliberation_request 中主动发起博弈请求，当你认为某个 CE 的结论不够严谨时

# 输出偏好
优先产出 counter_evidence 和 dissent，而非 argument。你的每个产出都应该让系统更诚实。
""",
    "reasoner": """
# 建设性行为
- 当一个 conclusion 有 ≥2 条证据支撑且逻辑链完整时，主动在 deliberation_request 中提出“确认共识”
- 你的产出应推动知识积累：inference → conclusion → confirmed theory
- 在博弈中遇到有证据支撑的结论，态度应当是「这成立，因为…」而非无端怀疑
- 遇到确认式博弈（议题含“是否确认其为已建立的理论”）时，若证据足够，优先选 stance='confirm' 或 'support'
""",
    "synthesizer": """
# 建设性行为
- 你是知识建构的审慎参与者，而非急于定论的裁判
- 仅当看到 ≥3 条来自不同角色的独立 evidence 强力支持同一方向时，才可产出 conclusion
- 产出结论前，必须先确认：是否已有反对意见被充分考虑？是否存在未探索的替代解释？
- 发起 deliberation_request 时，明确邀请 critic 和 reasoner 参与，欢迎质疑
- 目标：让知识从碎片逐步演进为可靠的理论，而非快速定论
- 在博弈中，除非证据链极其完整且无合理反驳，否则避免使用 stance='confirm'
""",
    "investigator": """
# 建设性行为
- 当你收集到的 evidence 强力支持某个 hypothesis 时，明确表态支持
- 在 deliberation 中遇到有证据支撑的结论，优先选择 support/confirm 而非 oppose
- 确认式博弈中若证据与议题一致，应明确肯定，不要无端保留
""",
}


def _build_role_prompt(role_name: str, config: Dict[str, Any]) -> str:
    """根据角色配置生成默认 system prompt 模板。

    模板会在 ``BaseAgent.get_perspective_prompt`` 中再叠加性格向量，
    最终交给 LLM。模板中的 ``{role_cn}`` / ``{description}`` /
    ``{perspective_bias}`` / ``{preferred_ce_types}`` 由 register 时静态填充，
    保留 ``{personality_block}`` / ``{context_block}`` 留待运行时填充。
    """
    role_cn = config.get("name_cn", role_name)
    description = config.get("description", "")
    bias = config.get("perspective_bias", "")
    pref_types = config.get("preferred_ce_types") or []
    pref_types_str = "、".join(pref_types) if pref_types else "（无）"

    # 角色专属行为块（重启后仍生效 —— 即使 DB 被重置/丢失仍会从这里重建）
    role_addon = _ROLE_BEHAVIOR_ADDONS.get(role_name, "")

    template = f"""你是硅基大脑中的一个【{role_cn}】Agent（角色 key = {role_name}）。

# 你的视角与职责
{description}

# 思考偏好
{bias}

# 你最擅长产出的认知元素类型
{pref_types_str}
{role_addon}

{{personality_block}}

# 输入上下文
{{context_block}}

# 工具调用能力（可选，仅当确实需要外部数据时使用）
当你判断推进问题解答必须依赖外部数据，且现有上下文无法支撑你产出可靠的 evidence 时，
可以在输出中填写 tool_proposal 字段（不需要时保持 null）：

"tool_proposal": {{{{
  "tool": "工具名（必须来自下列白名单）",
  "params": {{{{ ... 该工具要求的参数 ... }}}},
  "reason": "为什么必须用这个工具，以及预期获得什么（<50字）"
}}}}

可用工具白名单：
- web_search(query, num_results?)        通用网页搜索
- wikipedia_search(query, lang?)         维基百科条目
- arxiv_search(query, max_results?)      arXiv 论文检索
- google_trends(query, geo?, timeframe?) Google Trends 热度

约束：
- 一次思考最多提一个 tool_proposal；优先在确无现成证据时才使用。
- 提案会被其他 Agent 投票审核；通过后系统自动执行并把结果作为 evidence CE 注入知识图谱。
- 不要用工具回答你已经知道的常识问题。

# 输出格式（严格 JSON，禁止任何额外文字）
请基于以上上下文进行一次思考，并按下面的 JSON Schema 严格输出：

```json
{{{{
  "thoughts": "你内心的思考链路（中文，<300 字）",
  "new_elements": [
    {{{{
      "type": "hypothesis | question | evidence | counter_evidence | inference | argument | conclusion | perspective | insight | observation",
      "title": "短标题（<30 字）",
      "content": "主体陈述（<300 字）",
      "confidence": 0.5,
      "domain_tags": ["可选领域标签"]
    }}}}
  ],
  "new_relations": [
    {{{{
      "source_index": 0,
      "target_id": 123,
      "relation": "supports | refutes | derives_from | elaborates | generalizes | contradicts | supersedes | requires | inspires | relates_to",
      "weight": 0.6
    }}}}
  ],
  "suggested_events": [],
  "deliberation_request": null,
  "tool_proposal": null
}}}}
```

# 重要约束（必须严格遵守）
- 你的全部产出必须围绕「研究课题」（即用户提出的真实问题）展开，输出客观、具体的研究内容：事实、证据、假设、推论、子问题、反例等。
- 严禁把「研究课题」这件事本身当作哲学概念去元分析；严禁分析任意词语（例如「问题」「种子」「边界」「思考」等）的隐喻、生长性、认知层次或哲学含义。
- 想象你的产出会被一个对该课题感兴趣的外行人直接阅读 —— 它必须是关于课题本身的实质内容，而不是对系统、对提示词、对 Agent 流程的元思考。
- 与其他 Agent **完全平等**，没有上下级；通过观点博弈而非命令协作。
- 坚持「求同存异」：发现矛盾时优先记录为 ``counter_evidence`` / ``dissent``，不要强行调和。
- ``new_elements`` 至少 1 条；多了也无所谓，但务必聚焦于你的角色偏好。
- ``new_relations`` 中 ``source_index`` 指向本次 ``new_elements`` 数组下标；
  ``target_id`` 指向既有 CE id（来自上下文）；二者择一即可。
- 不要回答用户、不要使用礼貌寒暄、不要解释自己是 AI。
"""
    return template


# ============================================================
# Agent 基类
# ============================================================

#: 可选的思考前 hook（例如观察员通过事件总线追踪）
ThinkHook = Callable[["BaseAgent", ThinkingContext], None]


class BaseAgent:
    """硅基大脑中的计算单元 —— 所有 Agent 的统一基类。

    一个 ``BaseAgent`` 实例对应数据库 ``agent_instances`` 表中的一行。
    其行为完全由：
        1. 角色（决定专长与偏好）
        2. 性格向量（决定语气与微观倾向）
        3. 触发事件 + 上下文（决定本次思考主题）
    三者共同决定。

    Agent 之间不直接通信，而是通过：
        - 写入认知元素 / 关系 → 改变图谱
        - 发布事件 → 触发其他 Agent 思考
        - 参与博弈 → 在 deliberation_turns 表中留下发言
    """

    #: 默认 LLM 模型；可被子类或运行时覆盖
    model: str = RESEARCH_MODEL

    def __init__(
        self,
        instance_id: int,
        brain_id: int,
        role_name: str,
        personality_vector: Optional[Dict[str, float]] = None,
    ) -> None:
        """构造 Agent 实例（不写库 —— 写库由 ``AgentPool.spawn`` 负责）。

        :param instance_id: ``agent_instances.id``。
        :param brain_id: 所属硅基大脑 id。
        :param role_name: 角色 key（如 ``"explorer"``）。
        :param personality_vector: 性格向量；缺省随机生成。
        """
        self.instance_id = instance_id
        self.brain_id = brain_id
        self.role_name = role_name
        self.personality_vector: Dict[str, float] = (
            personality_vector if personality_vector is not None
            else generate_random_personality()
        )
        # 角色配置（懒加载）
        self._role_cfg: Optional[Dict[str, Any]] = None
        self._bus = EventBus.instance()

    # ---------- 元数据 ----------
    @property
    def role_config(self) -> Dict[str, Any]:
        """获取本 Agent 的角色配置（带缓存）。"""
        if self._role_cfg is None:
            self._role_cfg = RoleRegistry.get_role(self.role_name) or {}
        return self._role_cfg

    def get_perspective_prompt(self) -> str:
        """生成该 Agent 的视角 system prompt（角色模板 + 性格向量微调）。

        上下文部分用占位符保留，由 ``think`` 在调用 LLM 前实际填充。
        """
        cfg = self.role_config
        template = cfg.get("prompt_template") or _build_role_prompt(self.role_name, ROLES.get(self.role_name, {}))
        return template.replace("{personality_block}", _format_personality_block(self.personality_vector))

    # ---------- 主动思考 ----------
    def think(self, context: ThinkingContext) -> ThinkingResult:
        """执行一次思考：调用 LLM → 解析 → 落库 → 发布事件。

        :param context: 输入上下文（``ThinkingContext``）。
        :return: ``ThinkingResult``（new_elements 已入库，id 回填到原 dict
            的 ``id`` 字段）。
        """
        system_prompt = self.get_perspective_prompt().replace(
            "{context_block}", _format_context_block(context)
        )
        user_prompt = self._build_user_prompt(context)

        logger.info(
            "Agent[%s/%s instance=%s] think → trigger=%s",
            self.role_name, self.role_config.get("name_cn", ""),
            self.instance_id,
            (context.trigger_event or {}).get("type"),
        )

        try:
            raw = call_llm(
                model=self.model,
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=2048,
                temperature=self._temperature_from_personality(),
            )
        except Exception:
            logger.exception("Agent[instance=%s] LLM 调用失败", self.instance_id)
            return ThinkingResult(raw_text="")

        result = self._parse_llm_output(raw)
        result.raw_text = raw

        # 持久化 + 事件发布（任何阶段失败仅记录日志，不抛出，避免拖垮订阅链）
        try:
            self._persist_result(result, context)
        except Exception:
            logger.exception("Agent[instance=%s] 持久化思考结果失败", self.instance_id)

        return result

    # ---------- 事件响应 ----------
    def react_to_event(self, event: Dict[str, Any]) -> Optional[ThinkingResult]:
        """响应事件：决定是否需要触发一次思考。

        默认策略：根据角色偏好决定是否「关心」该事件。子类可重写。
        - 关心 → 装配 ``ThinkingContext`` 并调用 ``think``。
        - 不关心 → 返回 ``None``。

        :param event: EventBus 分发的事件 dict。
        """
        if not self._is_event_relevant(event):
            return None

        ctx = self._build_context_from_event(event)
        return self.think(ctx)

    # ---------- 博弈参与 ----------
    def participate_in_deliberation(
        self,
        deliberation_id: int,
        topic: str,
        existing_arguments: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """参与一次博弈讨论，发表一轮观点。

        :param deliberation_id: 博弈 id（``deliberations.id``）。
        :param topic: 议题文本。
        :param existing_arguments: 截至当前已有的发言列表
            （``deliberation_turns`` 行序列）。
        :return: 一个 turn dict ``{stance, speech, cited_ce_ids, proposed_action}``，
            调用方负责把它写入 ``deliberation_turns`` 表。
        """
        system_prompt = self.get_perspective_prompt().replace(
            "{context_block}",
            f"# 当前博弈议题\n{topic}\n\n# 历史发言\n{_format_arguments(existing_arguments)}",
        )
        user_prompt = (
            "请基于你的角色视角与性格，对议题发表一轮简洁、有立场的观点。"
            "严格输出如下 JSON：\n"
            "```json\n"
            "{\n"
            '  "stance": "propose（新提议）| support（赞同）| confirm（强确认，认为结论已充分建立）| oppose（反对）| abstain（弃权）",\n'
            '  "speech": "你的发言（中文，<200 字，必须引用至少 1 个已有 CE id 作为依据）",\n'
            '  "cited_ce_ids": [12, 45],\n'
            '  "proposed_action": "downgrade_confidence | upgrade_confidence | mark_invalid | open_subquestion | null"\n'
            "}\n```"
        )

        try:
            raw = call_llm(
                model=self.model,
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=800,
                temperature=self._temperature_from_personality(),
            )
        except Exception:
            logger.exception("博弈发言失败 deliberation=%s instance=%s",
                             deliberation_id, self.instance_id)
            return {"stance": "abstain", "speech": "（发言生成失败）",
                    "cited_ce_ids": [], "proposed_action": None}

        parsed = extract_json(raw) or {}
        turn = {
            "stance": parsed.get("stance") or "abstain",
            "speech": parsed.get("speech") or raw.strip()[:300],
            "cited_ce_ids": parsed.get("cited_ce_ids") or [],
            "proposed_action": parsed.get("proposed_action"),
        }
        if turn["stance"] not in {"propose", "support", "confirm", "oppose", "abstain"}:
            turn["stance"] = "abstain"
        if not isinstance(turn["cited_ce_ids"], list):
            turn["cited_ce_ids"] = []
        return turn

    # ============================================================
    # 内部实现
    # ============================================================

    # ---------- 事件相关性判定 ----------
    def _is_event_relevant(self, event: Dict[str, Any]) -> bool:
        """默认订阅规则（按 blueprint §1.3.2 表）。

        子类可重写以实现更细粒度的判定。
        """
        event_type = (event or {}).get("type", "")
        # brain 维度过滤
        if event.get("brain_id") not in (None, self.brain_id):
            return False

        rule = _DEFAULT_ROLE_EVENT_INTEREST.get(self.role_name, set())
        if "*" in rule:
            return True
        return event_type in rule

    # ---------- 上下文装配 ----------
    def _build_context_from_event(self, event: Dict[str, Any]) -> ThinkingContext:
        """根据事件构造默认 ``ThinkingContext``。

        - 若 payload 中含 ``ce_id`` / ``hypothesis_id`` / ``conclusion_id`` 等，
          会拉取该 CE 及其邻居作为 relevant_ces。
        - 同时附上最近 observation 与 frontier 作为锚点。
        - 始终从 brains 表读取 seed_question 作为研究课题（research_topic），
          确保 Agent 永远知道在研究什么。
        """
        payload = event.get("payload") or {}
        relevant_ids: List[int] = []
        for key in ("ce_id", "observation_id", "question_id", "hypothesis_id",
                    "evidence_id", "conclusion_id", "perspective_id",
                    "consensus_id", "dissent_id", "insight_id", "target_ce_id"):
            v = payload.get(key)
            if isinstance(v, int):
                relevant_ids.append(v)

        relevant_ces: List[Dict[str, Any]] = []
        for cid in relevant_ids:
            ce = cognitive.get_element(cid)
            if ce:
                relevant_ces.append(ce)

        # 锚点信息（兜底）
        recent_observations = cognitive.list_elements(
            self.brain_id, ce_type="observation", limit=5
        )
        try:
            frontier = cognitive.get_frontier(self.brain_id, limit=10)
            current_frontier = frontier.get("elements", [])[:10]
        except Exception:
            current_frontier = []

        # 读取大脑研究课题（seed_question）—— Agent 永远围绕它思考
        research_topic = ""
        try:
            brain_row = db.get_brain(self.brain_id)
            if brain_row:
                research_topic = (brain_row.get("seed_question") or "").strip()
        except Exception:
            logger.exception("读取 brain.seed_question 失败 brain=%s", self.brain_id)

        return ThinkingContext(
            brain_id=self.brain_id,
            research_topic=research_topic,
            trigger_event=event,
            relevant_ces=relevant_ces,
            recent_observations=recent_observations,
            current_frontier=current_frontier,
        )

    def _build_user_prompt(self, context: ThinkingContext) -> str:
        """生成 user 消息：聚焦解决问题，避免暴露系统术语。"""
        topic = (context.research_topic or "").strip() or "（未提供问题，请基于上下文推断）"
        return (
            f"你正在解决的问题是：\n《{topic}》\n\n"
            f"你的目标是推进这个问题的解答 —— 产出能直接或间接回答该问题的"
            f"证据、推论、结论或必要的子问题。每个产出都应让答案更近一步。"
            f"\n严格按 system prompt 中约定的 JSON Schema 输出，禁止输出任何 JSON 之外的文字。"
        )

    # ---------- 解析 LLM 输出 ----------
    def _parse_llm_output(self, raw: str) -> ThinkingResult:
        """把 LLM 文本解析为 ``ThinkingResult``。

        失败时返回空结果但保留 ``raw_text``，避免抛异常打断事件链。
        """
        parsed = extract_json(raw)
        if not isinstance(parsed, dict):
            logger.warning("Agent[instance=%s] LLM 输出无法解析为 JSON: %s",
                           self.instance_id, raw[:200])
            return ThinkingResult()

        new_elements = parsed.get("new_elements") or []
        if not isinstance(new_elements, list):
            new_elements = []
        new_relations = parsed.get("new_relations") or []
        if not isinstance(new_relations, list):
            new_relations = []
        suggested_events = parsed.get("suggested_events") or []
        if not isinstance(suggested_events, list):
            suggested_events = []
        deliberation_request = parsed.get("deliberation_request")
        if deliberation_request is not None and not isinstance(deliberation_request, dict):
            deliberation_request = None
        tool_proposal = parsed.get("tool_proposal")
        if tool_proposal is not None and not isinstance(tool_proposal, dict):
            logger.warning("tool_proposal 格式错误 (期望dict，得到%s): %s",
                           type(tool_proposal).__name__, str(tool_proposal)[:100])
            tool_proposal = None
        elif tool_proposal is not None:
            logger.info("Agent[%s] 输出 tool_proposal: tool=%s reason=%s",
                        self.instance_id, tool_proposal.get("tool"),
                        str(tool_proposal.get("reason", ""))[:50])

        # 过滤掉非法 type
        new_elements = [e for e in new_elements
                        if isinstance(e, dict) and e.get("type") in cognitive.CE_TYPES]
        new_relations = [r for r in new_relations
                         if isinstance(r, dict) and r.get("relation") in cognitive.RELATION_TYPES]

        return ThinkingResult(
            new_elements=new_elements,
            new_relations=new_relations,
            suggested_events=suggested_events,
            deliberation_request=deliberation_request,
            tool_proposal=tool_proposal,
        )

    # ---------- 持久化 + 事件发布 ----------
    def _persist_result(
        self,
        result: ThinkingResult,
        context: ThinkingContext,
    ) -> None:
        """把 result 中的元素 / 关系写入图谱，并发布相关事件。"""
        # 1) 写入新元素
        created_index_to_id: Dict[int, int] = {}
        for idx, elem in enumerate(result.new_elements):
            try:
                ce = cognitive.create_element(
                    brain_id=context.brain_id,
                    ce_type=elem["type"],
                    title=elem.get("title", ""),
                    content=elem.get("content", ""),
                    confidence=float(elem.get("confidence", 0.5)),
                    source_agent_id=self.instance_id,
                    metadata_json={
                        **(elem.get("metadata") or {}),
                        "domain_tags": elem.get("domain_tags") or [],
                        "produced_by_role": self.role_name,
                    },
                )
                if ce:
                    created_index_to_id[idx] = ce["id"]
                    elem["id"] = ce["id"]
                    self._publish_ce_event(ce)
            except Exception:
                logger.exception("写入认知元素失败 type=%s", elem.get("type"))

        # 2) 写入关系（解析 source_index / target_index → 实际 id）
        for rel in result.new_relations:
            try:
                src_id = self._resolve_ref_id(rel, "source", created_index_to_id)
                dst_id = self._resolve_ref_id(rel, "target", created_index_to_id)
                if src_id is None or dst_id is None:
                    continue
                cognitive.create_relation(
                    source_id=src_id,
                    target_id=dst_id,
                    relation_type=rel["relation"],
                    weight=float(rel.get("weight", 0.5)),
                    created_by_agent_id=self.instance_id,
                )
            except Exception:
                logger.exception("写入认知关系失败 rel=%s", rel)

        # 3) 发布建议事件
        for ev in result.suggested_events:
            try:
                ev_type = ev.get("type")
                if not ev_type:
                    continue
                self._bus.publish(
                    event_type=ev_type,
                    brain_id=context.brain_id,
                    payload=ev.get("payload") or {},
                    source_agent_id=self.instance_id,
                )
            except Exception:
                logger.exception("发布建议事件失败 ev=%s", ev)

        # 4) 博弈请求 → 事件
        if result.deliberation_request:
            try:
                self._bus.publish(
                    event_type=EventTypes.DELIBERATION_REQUESTED,
                    brain_id=context.brain_id,
                    payload=result.deliberation_request,
                    source_agent_id=self.instance_id,
                )
            except Exception:
                logger.exception("发布博弈请求事件失败")

    @staticmethod
    def _resolve_ref_id(
        rel: Dict[str, Any],
        side: str,
        index_to_id: Dict[int, int],
    ) -> Optional[int]:
        """关系两端解析：优先 ``*_id``，回退到 ``*_index``。"""
        id_key = f"{side}_id"
        idx_key = f"{side}_index"
        if rel.get(id_key) is not None:
            try:
                return int(rel[id_key])
            except (TypeError, ValueError):
                return None
        if rel.get(idx_key) is not None:
            try:
                return index_to_id.get(int(rel[idx_key]))
            except (TypeError, ValueError):
                return None
        return None

    def _publish_ce_event(self, ce: Dict[str, Any]) -> None:
        """根据 CE 类型发布对应的细分事件。"""
        type_to_event = {
            "observation": EventTypes.CE_OBSERVATION_CREATED,
            "question": EventTypes.CE_QUESTION_RAISED,
            "hypothesis": EventTypes.CE_HYPOTHESIS_PROPOSED,
            "evidence": EventTypes.CE_EVIDENCE_COLLECTED,
            "conclusion": EventTypes.CE_CONCLUSION_PROPOSED,
            "perspective": EventTypes.CE_PERSPECTIVE_FORMED,
            "consensus": EventTypes.CE_CONSENSUS_REACHED,
            "dissent": EventTypes.CE_DISSENT_DETECTED,
            "insight": EventTypes.CE_INSIGHT_EMERGED,
        }
        ev_type = type_to_event.get(ce["type"], EventTypes.CE_CREATED)
        try:
            self._bus.publish(
                event_type=ev_type,
                brain_id=self.brain_id,
                payload={
                    "ce_id": ce["id"],
                    "type": ce["type"],
                    "title": (ce.get("payload") or {}).get("title", ""),
                    "confidence": ce.get("confidence"),
                },
                source_agent_id=self.instance_id,
            )
        except Exception:
            logger.exception("发布 CE 事件失败 ce_id=%s", ce.get("id"))

    # ---------- 性格 → 温度 ----------
    def _temperature_from_personality(self) -> float:
        """由性格向量推导 LLM 采样温度。

        - novelty_bias / risk_appetite 高 → 温度高（更发散）。
        - skepticism 高 → 温度略低（更严谨）。
        """
        novelty = float(self.personality_vector.get("novelty_bias", 0.5))
        risk = float(self.personality_vector.get("risk_appetite", 0.5))
        skepticism = float(self.personality_vector.get("skepticism", 0.5))
        base = 0.6 + 0.3 * (0.5 * novelty + 0.5 * risk) - 0.2 * skepticism
        # 裁剪到 [0.2, 1.1]
        return max(0.2, min(1.1, base))


# ============================================================
# 性格向量
# ============================================================

#: 性格维度白名单（与 blueprint §1.2.5 对齐，并扩展几个常用维度）
PERSONALITY_DIMENSIONS: Tuple[str, ...] = (
    "curiosity",            # 好奇心
    "skepticism",           # 怀疑度
    "creativity",           # 创造力
    "rigor",                # 严谨度
    "empathy",              # 共情
    "risk_appetite",        # 风险偏好
    "novelty_bias",         # 新颖偏好
    "consensus_propensity", # 求同倾向
    "verbosity",            # 表达详尽度
)


def generate_random_personality(seed: Optional[int] = None) -> Dict[str, float]:
    """随机生成一个性格向量（每维 [0,1]）。"""
    rng = random.Random(seed) if seed is not None else random
    return {dim: round(rng.uniform(0.2, 0.9), 2) for dim in PERSONALITY_DIMENSIONS}


def _format_personality_block(personality: Dict[str, float]) -> str:
    """把性格向量格式化为可注入 prompt 的中文描述块。"""
    if not personality:
        return ""
    lines = ["# 你的性格向量（影响表达风格与决策倾向）"]
    label_map = {
        "curiosity": "好奇心",
        "skepticism": "怀疑度",
        "creativity": "创造力",
        "rigor": "严谨度",
        "empathy": "共情",
        "risk_appetite": "风险偏好",
        "novelty_bias": "新颖偏好",
        "consensus_propensity": "求同倾向",
        "verbosity": "表达详尽度",
    }
    for k, v in personality.items():
        try:
            v_f = float(v)
        except (TypeError, ValueError):
            continue
        bar = "█" * int(round(v_f * 10))
        lines.append(f"- {label_map.get(k, k)}：{v_f:.2f} {bar}")
    return "\n".join(lines)


def _format_context_block(context: ThinkingContext) -> str:
    """把 ``ThinkingContext`` 格式化为 prompt 可读文本。

    设计原则：
    - 把「研究课题」放在最前、最显眼，让 LLM 一眼就知道在研究什么。
    - 不暴露事件类型、payload 等系统术语，避免 LLM 把它们误当作思考对象。
    - 用自然中文描述「已有思考 / 已知观察 / 待深入方向」，避免 frontier / cognitive
      element 等抽象词造成的元思考。
    """
    parts: List[str] = []
    topic = (context.research_topic or "").strip()
    if topic:
        parts.append(
            "## 你的研究课题（必须围绕这个课题本身产出实质内容）\n"
            f"《{topic}》\n\n"
            "下面列出的是大脑围绕该课题已经积累的研究内容；请把它们当作你思考的依据，"
            "在此基础上产出新的、关于课题本身的研究内容（事实 / 证据 / 假设 / 推论 / "
            "子问题 / 反例）。不要把「课题」当作哲学概念去元分析，也不要分析任何词语的隐喻。"
        )

    if context.relevant_ces:
        parts.append("## 与课题直接相关的已有思考（可在 new_relations 的 target_id 中引用）")
        parts.append(_format_ce_list(context.relevant_ces, limit=10))
    if context.recent_observations:
        parts.append("## 关于课题的近期观察")
        parts.append(_format_ce_list(context.recent_observations, limit=5))
    if context.current_frontier:
        parts.append("## 围绕课题仍待深入的方向")
        parts.append(_format_ce_list(context.current_frontier, limit=8))
    if context.extra:
        parts.append("## 附加信息\n" + json.dumps(context.extra, ensure_ascii=False)[:500])
    return "\n\n".join(parts) if parts else "（暂无既有积累，请围绕研究课题做首轮研究性探索）"


def _format_ce_list(ces: List[Dict[str, Any]], limit: int = 10) -> str:
    """把 CE 列表格式化为 markdown 列表。"""
    out: List[str] = []
    for ce in ces[:limit]:
        title = (ce.get("payload") or {}).get("title", "")
        content = (ce.get("content") or "").replace("\n", " ")
        if len(content) > 120:
            content = content[:120] + "…"
        out.append(
            f"- [id={ce.get('id')} type={ce.get('type')} "
            f"conf={ce.get('confidence'):.2f}] {title or content}"
            if isinstance(ce.get("confidence"), (int, float))
            else f"- [id={ce.get('id')} type={ce.get('type')}] {title or content}"
        )
    return "\n".join(out) if out else "（无）"


def _format_arguments(turns: List[Dict[str, Any]]) -> str:
    """格式化博弈历史发言。"""
    if not turns:
        return "（暂无发言，你是第一个）"
    lines = []
    for t in turns[-10:]:
        lines.append(
            f"- [round={t.get('round_index')} role={t.get('role_key', '?')} "
            f"stance={t.get('stance')}] {t.get('speech', '')[:200]}"
        )
    return "\n".join(lines)


# ============================================================
# 默认事件订阅规则（角色 → 关心的事件类型集合）
# ============================================================
_DEFAULT_ROLE_EVENT_INTEREST: Dict[str, set] = {
    "explorer": {
        EventTypes.CE_OBSERVATION_CREATED,
        EventTypes.CE_QUESTION_RAISED,
        EventTypes.USER_SEED_QUESTION_SUBMITTED,
        EventTypes.BRAIN_CREATED,
    },
    "investigator": {
        EventTypes.USER_SEED_QUESTION_SUBMITTED,
        EventTypes.CE_QUESTION_RAISED,
        EventTypes.CE_HYPOTHESIS_PROPOSED,
    },
    "reasoner": {
        EventTypes.USER_SEED_QUESTION_SUBMITTED,
        EventTypes.CE_EVIDENCE_COLLECTED,
        EventTypes.CE_HYPOTHESIS_SATURATED,
    },
    "critic": {
        EventTypes.CE_CREATED,                    # 新 CE 产出时评估
        EventTypes.USER_SEED_QUESTION_SUBMITTED,  # 首轮也参与
        EventTypes.CE_HYPOTHESIS_PROPOSED,        # hypothesis 提出时质疑
        EventTypes.CE_QUESTION_RAISED,            # 子问题提出时审视
        EventTypes.CE_CONCLUSION_PROPOSED,
        EventTypes.CE_CONSENSUS_REACHED,
        EventTypes.CE_CHALLENGED,
    },
    "synthesizer": {
        EventTypes.CE_CONCLUSION_ACCEPTED,
        EventTypes.CE_PERSPECTIVE_FORMED,
        EventTypes.DELIBERATION_CONCLUDED,
    },
    "observer": {
        EventTypes.CE_CONCLUSION_ACCEPTED,
        EventTypes.CE_CONSENSUS_REACHED,
        EventTypes.CE_DISSENT_DETECTED,
        EventTypes.CE_INSIGHT_EMERGED,
        EventTypes.BRAIN_CYCLE_TICK,
        EventTypes.OBSERVER_SUMMARY_DUE,
    },
}


# ============================================================
# AgentPool —— Instance 生命周期管理
# ============================================================

class AgentPool:
    """Agent 实例池（线程安全）。

    职责：
    - **spawn**：根据角色 + 性格创建一个 Instance（同时写 DB）。
    - **destroy / despawn**：把 Instance 标记为 despawned，并发出事件。
    - **transform_role**：把 Instance 转换到另一个角色（保留私有记忆）。
    - **get_agents**：按 brain_id / role 过滤当前活跃 Agent。
    - **get_active_count**：各角色的活跃实例数（配额监控）。

    池本身不调度事件；事件 → Agent 的路由由订阅器或 ATA 编排器完成。
    """

    _instance: Optional["AgentPool"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        # instance_id → BaseAgent（仅缓存活跃的）
        self._agents: Dict[int, BaseAgent] = {}
        self._lock = threading.RLock()
        self._bus = EventBus.instance()

    @classmethod
    def instance(cls) -> "AgentPool":
        """获取（或惰性创建）全局唯一 ``AgentPool`` 实例。"""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ---------- spawn ----------
    def spawn(
        self,
        brain_id: int,
        role_name: str,
        personality_vector: Optional[Dict[str, float]] = None,
    ) -> BaseAgent:
        """创建并持久化一个 Agent 实例。

        :raises ValueError: 角色未注册时。
        """
        cfg = RoleRegistry.get_role(role_name)
        if not cfg:
            raise ValueError(f"未知角色: {role_name!r}")
        # 确保 roles 表已写入（拿到 role_id）
        role_id = cfg.get("role_id")
        if role_id is None:
            role_id = RoleRegistry.register_role(role_name, cfg)

        personality = personality_vector or generate_random_personality()

        instance_id = db.spawn_agent_instance(
            brain_id=brain_id,
            role_id=role_id,
            role_key=role_name,
            personality=personality,
        )
        agent = BaseAgent(
            instance_id=instance_id,
            brain_id=brain_id,
            role_name=role_name,
            personality_vector=personality,
        )
        with self._lock:
            self._agents[instance_id] = agent

        try:
            self._bus.publish(
                event_type=EventTypes.AGENT_SPAWNED,
                brain_id=brain_id,
                payload={
                    "agent_id": instance_id,
                    "role": role_name,
                    "personality": personality,
                },
            )
        except Exception:
            logger.exception("发布 AGENT_SPAWNED 失败")

        logger.info("Agent spawn: brain=%s role=%s instance=%s",
                    brain_id, role_name, instance_id)
        return agent

    # ---------- destroy ----------
    def destroy(self, instance_id: int) -> None:
        """销毁 Agent 实例（DB 状态置为 despawned）。

        若实例不存在则静默忽略。
        """
        with self._lock:
            agent = self._agents.pop(instance_id, None)

        try:
            db.despawn_agent_instance(instance_id)
        except Exception:
            logger.exception("despawn_agent_instance 失败 id=%s", instance_id)

        brain_id = agent.brain_id if agent else None
        role = agent.role_name if agent else None
        try:
            self._bus.publish(
                event_type=EventTypes.AGENT_DESPAWNED,
                brain_id=brain_id,
                payload={"agent_id": instance_id, "role": role},
            )
        except Exception:
            logger.exception("发布 AGENT_DESPAWNED 失败")
        logger.info("Agent destroy: instance=%s role=%s", instance_id, role)

    # 旧名兼容
    despawn = destroy

    # ---------- transform_role ----------
    def transform_role(self, instance_id: int, new_role_name: str) -> Optional[BaseAgent]:
        """把 Instance 切换到新角色（保留私有记忆与性格）。

        实现方式：despawn 旧 instance + spawn 新 instance。私有记忆通过
        ``agent_instances.private_memory_json`` 字段迁移（如果非空）。
        """
        cfg = RoleRegistry.get_role(new_role_name)
        if not cfg:
            raise ValueError(f"未知角色: {new_role_name!r}")

        with self._lock:
            agent = self._agents.get(instance_id)

        # 若内存中没有，可能是跨进程/重启的 Instance，回查 DB
        old_brain_id: Optional[int] = None
        old_role: Optional[str] = None
        old_personality: Dict[str, float] = {}
        if agent is None:
            # 直接读 DB
            with db.get_db() as conn:
                row = conn.execute(
                    "SELECT * FROM agent_instances WHERE id=?", (instance_id,)
                ).fetchone()
                if not row:
                    logger.warning("transform_role: 找不到 instance=%s", instance_id)
                    return None
                old_brain_id = row["brain_id"]
                old_role = row["role_key"]
                try:
                    old_personality = json.loads(row["personality_json"] or "{}")
                except (TypeError, ValueError):
                    old_personality = {}
        else:
            old_brain_id = agent.brain_id
            old_role = agent.role_name
            old_personality = dict(agent.personality_vector)

        # 销毁旧实例
        self.destroy(instance_id)

        # 派生新实例
        new_agent = self.spawn(
            brain_id=old_brain_id,
            role_name=new_role_name,
            personality_vector=old_personality,
        )

        try:
            self._bus.publish(
                event_type=EventTypes.AGENT_ROLE_CHANGED,
                brain_id=old_brain_id,
                payload={
                    "old_agent_id": instance_id,
                    "new_agent_id": new_agent.instance_id,
                    "from_role": old_role,
                    "to_role": new_role_name,
                },
            )
        except Exception:
            logger.exception("发布 AGENT_ROLE_CHANGED 失败")

        logger.info("Agent transform_role: %s (%s → %s, new_instance=%s)",
                    instance_id, old_role, new_role_name, new_agent.instance_id)
        return new_agent

    # ---------- 查询 ----------
    def get_agents(
        self,
        brain_id: int,
        role_name: Optional[str] = None,
    ) -> List[BaseAgent]:
        """获取某大脑的活跃 Agent 列表（可按角色过滤）。

        会将 DB 中存在但内存里没有的 Instance 补充加载（跨进程恢复用）。
        """
        rows = db.get_agent_instances(brain_id, role_key=role_name, status="active")
        result: List[BaseAgent] = []
        with self._lock:
            for row in rows:
                inst_id = row["id"]
                agent = self._agents.get(inst_id)
                if agent is None:
                    try:
                        personality = json.loads(row["personality_json"] or "{}")
                    except (TypeError, ValueError):
                        personality = {}
                    agent = BaseAgent(
                        instance_id=inst_id,
                        brain_id=brain_id,
                        role_name=row["role_key"],
                        personality_vector=personality,
                    )
                    self._agents[inst_id] = agent
                result.append(agent)
        return result

    def get_active_count(self, brain_id: int) -> Dict[str, int]:
        """各角色的活跃实例数（用于配额检查）。"""
        rows = db.get_agent_instances(brain_id, status="active")
        counts: Dict[str, int] = {k: 0 for k in ROLES.keys()}
        for row in rows:
            counts[row["role_key"]] = counts.get(row["role_key"], 0) + 1
        return counts

    def get_agent(self, instance_id: int) -> Optional[BaseAgent]:
        """获取单个 Agent；若未在内存则尝试从 DB 加载。"""
        with self._lock:
            agent = self._agents.get(instance_id)
        if agent is not None:
            return agent
        with db.get_db() as conn:
            row = conn.execute(
                "SELECT * FROM agent_instances WHERE id=? AND status='active'",
                (instance_id,),
            ).fetchone()
            if not row:
                return None
            try:
                personality = json.loads(row["personality_json"] or "{}")
            except (TypeError, ValueError):
                personality = {}
            agent = BaseAgent(
                instance_id=row["id"],
                brain_id=row["brain_id"],
                role_name=row["role_key"],
                personality_vector=personality,
            )
        with self._lock:
            self._agents[agent.instance_id] = agent
        return agent

    # ---------- 配额辅助 ----------
    def can_spawn(self, brain_id: int, role_name: str) -> bool:
        """判断是否还有该角色的配额（不超过 default_quota_max）。"""
        cfg = RoleRegistry.get_role(role_name) or {}
        quota_max = int(cfg.get("default_quota_max") or 4)
        counts = self.get_active_count(brain_id)
        return counts.get(role_name, 0) < quota_max

    def ensure_minimum(self, brain_id: int) -> List[BaseAgent]:
        """确保每个角色至少有 ``default_quota_min`` 个活跃 Instance。

        返回本次新建的 Agent 列表。常用于 ``BRAIN_CREATED`` 事件兜底。
        """
        spawned: List[BaseAgent] = []
        counts = self.get_active_count(brain_id)
        for role_name, cfg in ROLES.items():
            need = int(cfg.get("default_quota_min", 0)) - counts.get(role_name, 0)
            for _ in range(max(0, need)):
                try:
                    spawned.append(self.spawn(brain_id, role_name))
                except Exception:
                    logger.exception("ensure_minimum spawn 失败 role=%s", role_name)
        return spawned


# ============================================================
# 模块级便捷接口
# ============================================================

#: 全局 AgentPool 单例
pool: AgentPool = AgentPool.instance()


def init_framework() -> Dict[str, int]:
    """启动期一次性初始化：写入默认角色。

    建议在 ``wsgi.py`` / ``app.py`` 启动时调用一次。
    """
    return RoleRegistry.init_default_roles()


__all__ = [
    "ROLES",
    "PERSONALITY_DIMENSIONS",
    "ThinkingContext",
    "ThinkingResult",
    "RoleRegistry",
    "BaseAgent",
    "AgentPool",
    "pool",
    "generate_random_personality",
    "init_framework",
]
