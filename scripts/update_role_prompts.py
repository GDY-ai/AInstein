#!/usr/bin/env python3
"""为 investigator / explorer 的 prompt_template 注入 tool_proposal 能力。

幂等：检测到 tool_proposal 关键字则跳过对应角色。
"""
import sqlite3
import sys

DB_PATH = "/opt/ainstein/data/ainstein.db"

# 在 JSON Schema 示例的 deliberation_request 后追加 tool_proposal
JSON_SEARCH = '  "deliberation_request": null\n}}'
JSON_REPLACE = '  "deliberation_request": null,\n  "tool_proposal": null\n}}'

# 工具能力说明（插入到 "# 输出格式" 之前）
TOOL_BLOCK = """# 工具调用能力（可选，仅当确实需要外部数据时使用）
当你判断推进问题解答必须依赖外部数据，且现有上下文无法支撑你产出可靠的 evidence 时，
可以在输出中填写 tool_proposal 字段（不需要时保持 null）：

"tool_proposal": {{
  "tool": "工具名（必须来自下列白名单）",
  "params": {{ ... 该工具要求的参数 ... }},
  "reason": "为什么必须用这个工具，以及预期获得什么（<50字）"
}}

可用工具白名单：
- web_search(query, num_results?)        通用网页搜索
- wikipedia_search(query, lang?)         维基百科条目
- arxiv_search(query, max_results?)      arXiv 论文检索
- google_trends(query, geo?, timeframe?) Google Trends 热度

约束：
- 一次思考最多提一个 tool_proposal；优先在确无现成证据时才使用。
- 提案会被其他 Agent 投票审核；通过后系统自动执行并把结果作为 evidence CE 注入知识图谱。
- 不要用工具回答你已经知道的常识问题。

"""

OUTPUT_HEADER = "# 输出格式（严格 JSON，禁止任何额外文字）"


def patch_prompt(template: str, role_key: str) -> str:
    if "tool_proposal" in template:
        print(f"[{role_key}] 已包含 tool_proposal，跳过修改")
        return template

    # A. JSON Schema 示例追加字段
    if JSON_SEARCH not in template:
        raise RuntimeError(
            f"[{role_key}] 找不到 JSON Schema 锚点"
        )
    new = template.replace(JSON_SEARCH, JSON_REPLACE, 1)

    # B. 输出格式说明前插入工具能力说明
    if OUTPUT_HEADER not in new:
        raise RuntimeError(
            f"[{role_key}] 找不到输出格式锚点"
        )
    new = new.replace(OUTPUT_HEADER, TOOL_BLOCK + OUTPUT_HEADER, 1)

    # 完整性自检：确保占位符没有被破坏
    for marker in ("{personality_block}", "{context_block}"):
        if marker not in new:
            raise RuntimeError(f"[{role_key}] 占位符 {marker} 丢失")

    return new


def main() -> int:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        for role_key in ("investigator", "explorer"):
            row = cur.execute(
                "SELECT id, prompt_template FROM roles WHERE role_key=?",
                (role_key,),
            ).fetchone()
            if not row:
                print(f"[{role_key}] NOT FOUND in DB")
                continue
            role_id, template = row
            patched = patch_prompt(template, role_key)
            if patched == template:
                continue
            cur.execute(
                "UPDATE roles SET prompt_template=? WHERE id=?",
                (patched, role_id),
            )
            print(
                f"[{role_key}] updated; old_len={len(template)} "
                f"new_len={len(patched)} delta={len(patched)-len(template)}"
            )
        conn.commit()
    finally:
        conn.close()

    # 验证
    conn = sqlite3.connect(DB_PATH)
    try:
        for role_key in ("investigator", "explorer"):
            row = conn.execute(
                "SELECT prompt_template FROM roles WHERE role_key=?",
                (role_key,),
            ).fetchone()
            if not row:
                continue
            t = row[0]
            has_field = '"tool_proposal": null' in t
            has_section = "工具调用能力" in t
            has_pb = "{personality_block}" in t
            has_cb = "{context_block}" in t
            print(
                f"[{role_key}] verify: tool_proposal_field={has_field} "
                f"tool_section={has_section} personality_block={has_pb} "
                f"context_block={has_cb}"
            )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
