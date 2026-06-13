"""AInstein 论文生成器 - 将硅基大脑的认知元素综合为结构化研究论文。"""
import os
import logging
import subprocess
import json
from datetime import datetime

import database as db
from agents.llm_client import call_llm
from config import RESEARCH_MODEL

logger = logging.getLogger(__name__)

PAPERS_DIR = '/opt/ainstein/data/papers'
CSS_PATH = os.path.join(os.path.dirname(__file__), 'paper_template.css')


def _fetch_brain_data(brain_id: int):
    """从数据库读取指定 brain 的认知元素、关系和博弈记录。"""
    with db.get_db() as conn:
        # 认知元素（按创建时间正序）
        ces = conn.execute(
            "SELECT * FROM cognitive_elements WHERE brain_id=? ORDER BY created_at ASC",
            (brain_id,)
        ).fetchall()
        ces = [dict(r) for r in ces]

        # 认知关系（字段名是 relation）
        relations = conn.execute(
            "SELECT * FROM cognitive_relations WHERE brain_id=?",
            (brain_id,)
        ).fetchall()
        relations = [dict(r) for r in relations]

        # 博弈记录（先检查表是否存在）
        deliberations = []
        table_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='deliberations'"
        ).fetchone()
        if table_exists:
            delib_rows = conn.execute(
                "SELECT * FROM deliberations WHERE brain_id=? ORDER BY started_at ASC",
                (brain_id,)
            ).fetchall()
            deliberations = [dict(r) for r in delib_rows]

            # 读取博弈轮次发言
            for d in deliberations:
                turns = conn.execute(
                    "SELECT * FROM deliberation_turns WHERE deliberation_id=? ORDER BY round_index, id",
                    (d['id'],)
                ).fetchall()
                d['turns'] = [dict(t) for t in turns]

        # 获取大脑信息
        brain = conn.execute(
            "SELECT * FROM brains WHERE id=?", (brain_id,)
        ).fetchone()
        brain = dict(brain) if brain else {}

    return brain, ces, relations, deliberations


def _split_phases(ces: list):
    """将 CE 按时间分为三个阶段：早期探索、中期深入、后期收敛。"""
    n = len(ces)
    if n == 0:
        return [], [], []
    third = max(1, n // 3)
    early = ces[:third]
    mid = ces[third:third * 2]
    late = ces[third * 2:]
    return early, mid, late


def _build_ce_summary(ces: list, max_items: int = 80) -> str:
    """构建认知元素摘要文本。"""
    lines = []
    for ce in ces[:max_items]:
        content_preview = (ce.get('content') or '')[:200]
        lines.append(
            f"[CE#{ce['id']}] type={ce['type']} confidence={ce.get('confidence', '?')} "
            f"content: {content_preview}"
        )
    if len(ces) > max_items:
        lines.append(f"... (共 {len(ces)} 个认知元素，此处展示前 {max_items} 个)")
    return '\n'.join(lines)


def _build_relation_summary(relations: list, max_items: int = 60) -> str:
    """构建认知关系摘要。"""
    lines = []
    for r in relations[:max_items]:
        lines.append(
            f"CE#{r['src_id']} --[{r['relation']}]--> CE#{r['dst_id']} "
            f"(strength={r.get('strength', '?')})"
        )
    if len(relations) > max_items:
        lines.append(f"... (共 {len(relations)} 条关系)")
    return '\n'.join(lines)


def _build_deliberation_summary(deliberations: list) -> str:
    """构建博弈记录摘要。"""
    if not deliberations:
        return "（无博弈记录）"
    lines = []
    for d in deliberations[:10]:
        lines.append(f"\n### 博弈 #{d['id']}: {d.get('motion', '未知议题')}")
        lines.append(f"   状态: {d.get('status', '?')} | 结果: {d.get('outcome', '未决')}")
        for t in d.get('turns', [])[:6]:
            speech_preview = (t.get('speech') or '')[:150]
            lines.append(
                f"   [轮{t['round_index']}] 立场={t['stance']}: {speech_preview}"
            )
    return '\n'.join(lines)


def _build_mega_prompt(brain: dict, ces: list, relations: list,
                       deliberations: list) -> str:
    """构造 mega-prompt 用于调用 LLM 生成论文。"""
    early, mid, late = _split_phases(ces)

    seed_question = brain.get('seed_question', '未知研究问题')
    brain_name = brain.get('name', '未命名大脑')

    prompt = f"""你是一位资深学术论文编辑与科学写作专家。现在需要你将一个硅基大脑（AI多智能体协作系统）产生的大量认知元素(Cognitive Elements)综合为一篇结构化的研究报告/论文。

## 研究主题
大脑名称: {brain_name}
种子问题: {seed_question}

## 数据概览
- 认知元素总数: {len(ces)}
- 认知关系总数: {len(relations)}
- 博弈记录数: {len(deliberations)}

## 认知元素 - 早期探索阶段 (前1/3，共{len(early)}个)
{_build_ce_summary(early)}

## 认知元素 - 中期深入阶段 (中1/3，共{len(mid)}个)
{_build_ce_summary(mid)}

## 认知元素 - 后期收敛阶段 (后1/3，共{len(late)}个)
{_build_ce_summary(late)}

## 认知关系网络
{_build_relation_summary(relations)}

## 博弈与争论记录
{_build_deliberation_summary(deliberations)}

---

## 输出要求

请输出一篇严格结构化的 Markdown 格式研究论文，结构如下：

```
# [从种子问题提炼的论文标题]

## 摘要
（200字以内，精炼概括核心发现和结论，需给出明确立场）

## 1. 引言
（研究问题的提出背景，为何该问题值得探索，本研究的目标与价值）

## 2. 方法论
（简述多智能体协作思维框架：多个AI角色如何分工合作、如何通过博弈收敛观点）

## 3. 思维演化纪实
（讲述一个"故事"：从种子问题出发，经历了哪些关键转折点，思维如何分支、碰撞、最终收敛。引用 CE 时用 [CE#id] 格式标注）

## 4. 核心论证
（主要 argument/inference 的逻辑链，呈现关键推理过程和证据链）

## 5. 争议与博弈
（重要 deliberation 的正反观点摘要，展示思想碰撞的过程）

## 6. 结论与展望
（最终洞见——需给出明确立场而非模棱两可；开放问题与未来方向）

## 附录: 认知元素引用索引
（以表格形式列出论文中引用的 CE 编号及其内容摘要）
| CE编号 | 类型 | 内容摘要 |
|--------|------|----------|
```

## 写作要求
1. 兼顾学术论文的严谨性和思维演化纪实的生动性
2. 引用 CE 时用 [CE#id] 格式
3. 摘要需200字以内
4. 结论需给出明确立场
5. 思维演化部分要讲"故事"：有起承转合
6. 全文使用中文
7. 直接输出 Markdown 正文，不要包裹在代码块中
"""
    return prompt


def _markdown_to_pdf(md_path: str, pdf_path: str) -> bool:
    """使用 pandoc + wkhtmltopdf 将 Markdown 转为 PDF。"""
    try:
        cmd = [
            'pandoc', md_path,
            '-o', pdf_path,
            '--pdf-engine=wkhtmltopdf',
            '--css', CSS_PATH,
            '-V', 'margin-top=25mm',
            '-V', 'margin-bottom=25mm',
            '-V', 'margin-left=25mm',
            '-V', 'margin-right=25mm',
            '--metadata', f'title=AInstein Research Report',
            '-f', 'markdown',
            '-t', 'html5',
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            logger.error(f"pandoc failed: {result.stderr}")
            # 尝试备用方案：不使用 CSS
            cmd_fallback = [
                'pandoc', md_path,
                '-o', pdf_path,
                '--pdf-engine=wkhtmltopdf',
                '-V', 'margin-top=25mm',
                '-V', 'margin-bottom=25mm',
                '-V', 'margin-left=25mm',
                '-V', 'margin-right=25mm',
            ]
            result2 = subprocess.run(
                cmd_fallback, capture_output=True, text=True, timeout=120
            )
            if result2.returncode != 0:
                logger.error(f"pandoc fallback also failed: {result2.stderr}")
                return False
        return True
    except subprocess.TimeoutExpired:
        logger.error("pandoc timed out")
        return False
    except FileNotFoundError:
        logger.error("pandoc not found in PATH")
        return False


# 任务状态持久化（文件存储，兼容多 worker）
TASKS_FILE = os.path.join(PAPERS_DIR, '.tasks.json')


def _load_tasks() -> dict:
    """从文件加载任务状态。"""
    try:
        if os.path.exists(TASKS_FILE):
            with open(TASKS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_task(task_id: str, data: dict):
    """保存任务状态到文件。"""
    os.makedirs(PAPERS_DIR, exist_ok=True)
    tasks = _load_tasks()
    tasks[task_id] = data
    try:
        with open(TASKS_FILE, 'w', encoding='utf-8') as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to save task status: {e}")


def generate_paper(brain_id: int, task_id: str) -> str:
    """
    生成研究论文的主函数。

    Args:
        brain_id: 大脑 ID
        task_id: 任务 ID（用于追踪进度）

    Returns:
        PDF 文件路径，失败时抛出异常
    """
    try:
        _save_task(task_id, {'status': 'processing', 'progress': '正在读取认知数据...',
                             'brain_id': brain_id})

        # 1. 读取数据
        brain, ces, relations, deliberations = _fetch_brain_data(brain_id)
        if not brain:
            raise ValueError(f"Brain {brain_id} not found")
        if not ces:
            raise ValueError(f"Brain {brain_id} has no cognitive elements")

        _save_task(task_id, {'status': 'processing', 'brain_id': brain_id,
                             'progress': f'已读取 {len(ces)} 个认知元素，正在调用 LLM 生成论文...'})

        # 2. 构造 prompt 并调用 LLM
        system_prompt = (
            "你是一位顶级学术论文编辑，擅长将复杂的多源信息综合为结构清晰、"
            "逻辑严密的研究论文。你的文风兼具学术严谨性和叙事的生动感。"
        )
        mega_prompt = _build_mega_prompt(brain, ces, relations, deliberations)

        messages = [{"role": "user", "content": mega_prompt}]

        model = RESEARCH_MODEL
        markdown_text = call_llm(
            model=model,
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=16000,
            temperature=0.3,
        )

        if not markdown_text or len(markdown_text.strip()) < 100:
            raise RuntimeError("LLM 返回内容过短，论文生成失败")

        _save_task(task_id, {'status': 'processing', 'brain_id': brain_id,
                             'progress': '论文内容已生成，正在转换为 PDF...'})

        # 3. 保存 Markdown
        os.makedirs(PAPERS_DIR, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        base_name = f"brain{brain_id}_{timestamp}"
        md_filename = f"{base_name}.md"
        pdf_filename = f"{base_name}.pdf"
        md_path = os.path.join(PAPERS_DIR, md_filename)
        pdf_path = os.path.join(PAPERS_DIR, pdf_filename)

        # 写入 Markdown 文件
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(markdown_text)

        logger.info(f"Paper markdown saved: {md_path}")

        # 4. 转换为 PDF
        pdf_success = _markdown_to_pdf(md_path, pdf_path)

        if pdf_success and os.path.exists(pdf_path):
            _save_task(task_id, {
                'status': 'done',
                'brain_id': brain_id,
                'progress': '论文生成完成',
                'pdf_filename': pdf_filename,
                'md_filename': md_filename,
            })
            logger.info(f"Paper PDF generated: {pdf_path}")
            return pdf_path
        else:
            # PDF 失败但 Markdown 成功，仍标记部分成功
            _save_task(task_id, {
                'status': 'done',
                'brain_id': brain_id,
                'progress': '论文Markdown已生成，PDF转换失败（可下载Markdown）',
                'pdf_filename': None,
                'md_filename': md_filename,
            })
            logger.warning(f"PDF conversion failed, markdown available: {md_path}")
            return md_path

    except Exception as e:
        logger.exception(f"Paper generation failed for brain {brain_id}")
        _save_task(task_id, {
            'status': 'error',
            'brain_id': brain_id,
            'progress': f'生成失败: {str(e)}',
        })
        raise


def get_task_status(task_id: str) -> dict:
    """获取论文生成任务状态。"""
    tasks = _load_tasks()
    return tasks.get(task_id, {'status': 'unknown', 'progress': '任务不存在'})
