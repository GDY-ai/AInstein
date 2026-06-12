"""Scientist agent: decomposes mission into directives and initial topics."""
import os
import json
import logging
import database as db
from agents.llm_client import call_llm, extract_json
from config import SCIENTIST_MODEL

logger = logging.getLogger(__name__)

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'prompts')


def run_scientist(project_id):
    """Run the scientist to generate strategic directives and initial topics."""
    project = db.get_project(project_id)
    if not project:
        logger.error(f"Project {project_id} not found")
        return None

    mission = project['mission']
    domain = project['domain']

    datasets = db.get_datasets(project_id)
    from tools.data_access import get_dataset_summary
    datasets_summary = get_dataset_summary(project_id, datasets)

    with open(os.path.join(PROMPTS_DIR, 'scientist.txt'), 'r') as f:
        system_prompt = f.read().format(
            mission=mission,
            domain=domain,
            datasets_summary=datasets_summary,
        )

    messages = [{
        'role': 'user',
        'content': (
            f"As the lead scientist for project '{project['name']}', analyze the mission and "
            f"define the research strategy. The project focuses on: {mission}\n\n"
            f"Domain: {domain}\n\n"
            f"Available data:\n{datasets_summary}\n\n"
            "Produce strategic directives and initial research topics."
        )
    }]

    logger.info(f"Running scientist for project {project_id}: {project['name']}")
    text = call_llm(SCIENTIST_MODEL, system_prompt, messages, max_tokens=3000, temperature=0.7)
    data = extract_json(text)

    if not data:
        logger.error("Scientist failed to produce valid JSON")
        return None

    directives = data.get('directives', [])
    for d in directives:
        db.add_directive(project_id, d['directive'], d.get('priority', 5))

    topics = data.get('initial_topics', [])
    for t in topics:
        db.add_to_queue(project_id, t['topic'], t.get('priority', 5), source='scientist')

    categories = data.get('finding_categories', [])
    notes = data.get('strategic_notes', '')
    if notes:
        db.add_director_memory(project_id, 'scientist_strategy', notes,
                               context_data={'categories': categories})

    logger.info(f"Scientist done: {len(directives)} directives, {len(topics)} topics")
    return {
        'directives': len(directives),
        'topics': len(topics),
        'categories': categories,
        'notes': notes,
    }
