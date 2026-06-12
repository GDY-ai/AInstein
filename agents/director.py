"""Director agent: daily review, queue management, memory accumulation."""
import os
import json
import logging
import database as db
from agents.llm_client import call_llm, extract_json
from config import DIRECTOR_MODEL

logger = logging.getLogger(__name__)

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'prompts')


def run_director_daily(project_id):
    """Run the daily director review for a project."""
    project = db.get_project(project_id)
    if not project:
        logger.error(f"Project {project_id} not found")
        return None

    mission = project['mission']
    domain = project['domain']

    recent_sessions = db.get_sessions(project_id, limit=5)
    open_findings = db.get_findings(project_id, limit=30, status='open')
    queue = db.get_queue(project_id)
    memory = db.get_director_memories(project_id, limit=10)

    sessions_summary = []
    for s in recent_sessions:
        sessions_summary.append({
            'topic': s['topic'],
            'status': s['status'],
            'duration': s.get('duration_seconds', 0),
            'findings': s.get('findings', ''),
        })

    findings_list = []
    for f in open_findings:
        findings_list.append({
            'id': f['id'],
            'finding': f['finding'],
            'confidence': f['confidence'],
            'category': f['category'],
            'evidence': f.get('evidence', ''),
        })

    queue_list = []
    for q in queue[:20]:
        queue_list.append({
            'id': q['id'],
            'topic': q['topic'],
            'priority': q['priority'],
            'status': q['status'],
            'source': q['source'],
        })

    memory_list = []
    for m in memory:
        memory_list.append({'kind': m['kind'], 'content': m['content']})

    with open(os.path.join(PROMPTS_DIR, 'director.txt'), 'r') as f:
        system_prompt = f.read().format(mission=mission, domain=domain)

    user_content = (
        f"Daily review for project '{project['name']}':\n\n"
        f"=== Recent Sessions (last 5) ===\n{json.dumps(sessions_summary, ensure_ascii=False, default=str)[:2000]}\n\n"
        f"=== Open Findings ({len(open_findings)} total) ===\n{json.dumps(findings_list, ensure_ascii=False)[:3000]}\n\n"
        f"=== Research Queue ===\n{json.dumps(queue_list, ensure_ascii=False)[:1500]}\n\n"
        f"=== Director Memory ===\n{json.dumps(memory_list, ensure_ascii=False)[:1000]}\n\n"
        "Perform your daily review: evaluate findings, adjust queue, accumulate memory, write briefing."
    )

    messages = [{'role': 'user', 'content': user_content}]

    logger.info(f"Running director for project {project_id}: {project['name']}")
    text = call_llm(DIRECTOR_MODEL, system_prompt, messages, max_tokens=4000, temperature=0.5)
    data = extract_json(text)

    if not data:
        logger.error("Director failed to produce valid JSON")
        return None

    review_count = 0
    for fr in data.get('findings_review', []):
        fid = fr.get('finding_id')
        action = fr.get('action')
        if fid and action in ('validate', 'reject'):
            new_status = 'validated' if action == 'validate' else 'rejected'
            db.update_finding(fid, new_status)
            review_count += 1

    new_topic_count = 0
    for nt in data.get('new_topics', []):
        db.add_to_queue(
            project_id=project_id,
            topic=nt['topic'],
            priority=nt.get('priority', 5),
            source='director',
        )
        new_topic_count += 1

    memory_count = 0
    for me in data.get('memory_entries', []):
        db.add_director_memory(
            project_id=project_id,
            kind=me.get('kind', 'insight'),
            content=me.get('content', ''),
            context_data=me.get('context_data'),
        )
        memory_count += 1

    briefing = data.get('briefing', '')
    if briefing:
        db.add_director_memory(project_id, 'briefing', briefing)

    logger.info(f"Director done: {review_count} findings reviewed, {new_topic_count} topics added, {memory_count} memories")
    return {
        'findings_reviewed': review_count,
        'new_topics': new_topic_count,
        'memories': memory_count,
        'briefing': briefing,
    }
