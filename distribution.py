"""AInstein 内容分发模块 — 飞书 Webhook + RSS Feed (Task #17)"""
import os
import json
import logging
import requests
from typing import Dict, List, Optional
from datetime import datetime, timezone

import database as db

logger = logging.getLogger(__name__)


def send_to_feishu(digest: Dict) -> bool:
    """通过飞书自定义机器人 Webhook 推送日报。

    使用富文本 post 格式，包含：
    - 标题（日报标题）
    - 正文（摘要）
    - 统计数据
    - 底部链接到完整日报页面
    """
    webhook_url = os.environ.get('FEISHU_WEBHOOK_URL')
    if not webhook_url:
        logger.warning("FEISHU_WEBHOOK_URL not configured, skipping feishu push")
        return False

    title = digest.get('title', '主脑日报')
    summary = digest.get('summary', '')
    highlights = digest.get('highlights', [])
    stats = digest.get('stats', {})
    created_at = digest.get('created_at', datetime.utcnow().strftime('%Y-%m-%d'))

    # 构建富文本内容
    content_lines = [[{"tag": "text", "text": summary}]]

    # 统计行
    if stats:
        stats_text = (
            f"\n📊 统计：新增大脑 {stats.get('new_brains', 0)} | "
            f"新增CE {stats.get('new_ces', 0)} | "
            f"收敛 {stats.get('converged_brains', 0)} | "
            f"矛盾 {stats.get('contradictions', 0)}"
        )
        content_lines.append([{"tag": "text", "text": stats_text}])

    # 亮点
    if highlights:
        hl_text = "\n💡 亮点：\n" + "\n".join(f"• {h}" for h in highlights[:3])
        content_lines.append([{"tag": "text", "text": hl_text}])

    # 底部链接
    base_url = os.environ.get('AINSTEIN_BASE_URL', 'https://hub.circlegpu.com')
    daily_url = f"{base_url}/ainstein/master-daily"
    content_lines.append([
        {"tag": "text", "text": "\n🔗 "},
        {"tag": "a", "text": "查看完整日报", "href": daily_url},
    ])

    payload = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": f"🧠 {title}",
                    "content": content_lines,
                }
            }
        }
    }

    try:
        resp = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if resp.status_code == 200:
            body = resp.json()
            if body.get('code') == 0 or body.get('StatusCode') == 0:
                logger.info("[distribution] 飞书推送成功: %s", title)
                return True
            else:
                logger.warning("[distribution] 飞书返回非零: %s", body)
                return False
        else:
            logger.warning("[distribution] 飞书 HTTP %s: %s", resp.status_code, resp.text[:200])
            return False
    except Exception:
        logger.exception("[distribution] 飞书推送异常")
        return False


def generate_rss_xml(digests: List[Dict],
                     base_url: str = 'https://hub.circlegpu.com/ainstein') -> str:
    """生成 Atom RSS Feed XML 字符串。"""
    now_iso = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    feed_url = f"{base_url}/master-daily.rss"

    entries = []
    for d in digests:
        entry_id = f"{base_url}/master-daily/{d.get('created_at', 'unknown')}"
        # 解析 created_at 为 ISO 格式
        raw_date = d.get('created_at', '')
        if 'T' not in raw_date and len(raw_date) == 10:
            updated = f"{raw_date}T08:00:00Z"
        elif len(raw_date) >= 19:
            updated = raw_date.replace(' ', 'T') + 'Z'
        else:
            updated = now_iso

        title = _xml_escape(d.get('title', '主脑日报'))
        summary = _xml_escape(d.get('summary', ''))
        highlights = d.get('highlights', [])
        hl_html = ''.join(f'<li>{_xml_escape(h)}</li>' for h in highlights[:5])
        content_html = f"<p>{summary}</p>"
        if hl_html:
            content_html += f"<h4>亮点</h4><ul>{hl_html}</ul>"

        entries.append(f"""  <entry>
    <id>{entry_id}</id>
    <title>{title}</title>
    <updated>{updated}</updated>
    <summary type="text">{summary[:200]}</summary>
    <content type="html"><![CDATA[{content_html}]]></content>
    <link rel="alternate" href="{entry_id}" />
  </entry>""")

    entries_xml = '\n'.join(entries)
    last_updated = now_iso
    if digests:
        raw = digests[0].get('created_at', '')
        if raw:
            last_updated = (raw.replace(' ', 'T') + 'Z') if 'T' not in raw else raw

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <id>{feed_url}</id>
  <title>AInstein 主脑日报</title>
  <subtitle>创世主脑每日跨域洞察</subtitle>
  <updated>{last_updated}</updated>
  <link rel="self" href="{feed_url}" />
  <link rel="alternate" href="{base_url}/master-daily" />
  <author>
    <name>AInstein 创世主脑</name>
  </author>
{entries_xml}
</feed>"""


def _xml_escape(text: str) -> str:
    """基础 XML 转义。"""
    return (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&apos;'))


def publish_digest(digest: Dict) -> Dict[str, bool]:
    """统一分发入口：保存数据库 + 飞书 + 更新 RSS。

    Returns: {'feishu': True/False, 'rss': True/False, 'db': True/False}
    """
    results = {'feishu': False, 'rss': False, 'db': False}

    # 1. 保存到数据库
    try:
        digest_id = db.save_digest_log(
            master_id=digest.get('master_id', 0),
            title=digest.get('title', '主脑日报'),
            summary=digest.get('summary', ''),
            highlights=digest.get('highlights', []),
            stats=digest.get('stats', {}),
        )
        results['db'] = True
        logger.info("[distribution] 日报已保存 id=%s", digest_id)
    except Exception:
        logger.exception("[distribution] 保存日报到数据库失败")
        return results

    # 2. 推送飞书（失败不阻塞）
    try:
        results['feishu'] = send_to_feishu(digest)
    except Exception:
        logger.exception("[distribution] 飞书推送异常（已捕获）")

    # 3. RSS 不需要额外操作（通过 API 实时生成）
    results['rss'] = True

    # 4. 更新分发状态
    try:
        status_parts = []
        if results['feishu']:
            status_parts.append('feishu_ok')
        if results['rss']:
            status_parts.append('rss_ok')
        status = ','.join(status_parts) if status_parts else 'partial'
        db.update_digest_status(digest_id, status)
    except Exception:
        logger.exception("[distribution] 更新分发状态失败")

    return results
