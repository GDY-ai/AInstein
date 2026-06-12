"""Researcher agent: picks topics, runs engine, persists results."""
import json
import logging
import database as db
from engines.base import ResearchContext
from engines.three_round import ThreeRoundEngine
from tools.data_access import get_dataset_summary

logger = logging.getLogger(__name__)

ENGINE = ThreeRoundEngine()


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
