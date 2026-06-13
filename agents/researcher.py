"""Researcher agent: picks topics, runs engine, persists results."""
import json
import logging
import database as db
from engines.base import ResearchContext
from engines.three_round import ThreeRoundEngine
from tools.data_access import get_dataset_summary

logger = logging.getLogger(__name__)

ENGINE = ThreeRoundEngine()


def _resolve_brain_id(project_id):
    """通过 legacy_project_id 反查关联的硅基大脑 id。

    旧流程仅有 project_id；如果该项目已被映射到 brains 表（``legacy_project_id``
    指向当前项目），则返回最新一个 brain 的 id，供引擎做认知元素双写。
    任何异常或未找到记录都返回 ``None``，调用方会自动跳过双写。
    """
    try:
        with db.get_db() as conn:
            row = conn.execute(
                "SELECT id FROM brains WHERE legacy_project_id=? "
                "ORDER BY created_at DESC LIMIT 1",
                (project_id,)
            ).fetchone()
            return row['id'] if row else None
    except Exception as e:
        logger.warning(f"[双写] resolve brain_id failed for project {project_id}: {e}")
        return None


def run_research_session(project_id, topic=None):
    """Run a single research session for a project."""
    project = db.get_project(project_id)
    if not project:
        logger.error(f"Project {project_id} not found")
        return None

    config = json.loads(project.get('config_json', '{}') or '{}')
    mission = project['mission']
    domain = project['domain']

    queue_item = None
    if topic:
        queue_item = {'topic': topic, 'id': None}
    else:
        queue_item = db.pick_next_topic(project_id)
        if not queue_item:
            logger.info(f"No pending topics for project {project_id}")
            return None
        topic = queue_item['topic']

    datasets = db.get_datasets(project_id)
    datasets_summary = get_dataset_summary(project_id, datasets)

    recent_findings = db.get_findings(project_id, limit=10)
    directives = db.get_directives(project_id)

    ctx = ResearchContext(
        project_id=project_id,
        mission=mission,
        domain=domain,
        topic=topic,
        config=config,
        datasets_summary=datasets_summary,
        recent_findings=recent_findings,
        directives=directives,
        brain_id=_resolve_brain_id(project_id),
    )

    session_id = db.create_session(
        project_id=project_id,
        topic=topic,
        engine_type=ENGINE.engine_type,
        queue_id=queue_item.get('id'),
    )
    ctx.session_id = session_id

    logger.info(f"Starting session {session_id}: {topic}")

    try:
        result = ENGINE.run(ctx)
    except Exception as e:
        logger.error(f"Engine failed for session {session_id}: {e}")
        db.update_session(session_id, status='failed')
        if queue_item.get('id'):
            db.update_queue_item(queue_item['id'], 'failed')
        return None

    db.update_session(
        session_id,
        status=result.status,
        hypotheses=result.hypotheses,
        verification=result.verification,
        findings=json.dumps(result.findings, ensure_ascii=False) if result.findings else None,
        next_directions=json.dumps(result.next_directions, ensure_ascii=False) if result.next_directions else None,
        data_summary=result.data_summary,
        duration_seconds=result.duration_seconds,
    )

    for f in result.findings:
        db.add_finding(
            project_id=project_id,
            session_id=session_id,
            finding=f.get('finding', ''),
            category=f.get('category', 'general'),
            confidence=f.get('confidence', 'low'),
            evidence=f.get('evidence', ''),
            actionable=1 if f.get('actionable') else 0,
            action_suggestion=f.get('action_suggestion', ''),
        )

    for nd in result.next_directions:
        db.add_to_queue(
            project_id=project_id,
            topic=nd,
            priority=7,
            source='ai_generated',
            source_session_id=session_id,
        )

    if queue_item.get('id'):
        db.update_queue_item(queue_item['id'], 'completed')

    logger.info(f"Session {session_id} done: {result.status}, {len(result.findings)} findings")
    return {
        'session_id': session_id,
        'status': result.status,
        'findings_count': len(result.findings),
        'next_directions': result.next_directions,
        'duration_seconds': result.duration_seconds,
    }
