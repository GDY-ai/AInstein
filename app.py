"""AInstein Flask app."""
import os
import json
import logging
from flask import Flask, request, jsonify, send_from_directory
import database as db

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='frontend/dist', static_url_path='/ainstein/static')
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), 'frontend', 'dist')


@app.before_request
def ensure_db():
    if not getattr(app, '_db_init', False):
        db.init_db()
        app._db_init = True


# === Frontend ===

@app.route('/ainstein/')
@app.route('/ainstein')
def serve_index():
    return send_from_directory(FRONTEND_DIST, 'index.html')

@app.route('/ainstein/assets/<path:filename>')
def serve_assets(filename):
    return send_from_directory(os.path.join(FRONTEND_DIST, 'assets'), filename)

@app.route('/ainstein/<path:path>')
def serve_spa(path):
    full = os.path.join(FRONTEND_DIST, path)
    if os.path.isfile(full):
        return send_from_directory(FRONTEND_DIST, path)
    return send_from_directory(FRONTEND_DIST, 'index.html')


# === Health ===

@app.route('/ainstein/api/health')
def health():
    return jsonify({'status': 'ok'})


# === Projects ===

@app.route('/ainstein/api/projects', methods=['GET'])
def list_projects():
    return jsonify(db.get_projects())

@app.route('/ainstein/api/projects', methods=['POST'])
def create_project():
    data = request.get_json()
    pid = db.create_project(data['name'], data['mission'], data['domain'], data.get('config'))
    return jsonify({'id': pid}), 201

@app.route('/ainstein/api/projects/<int:pid>')
def get_project(pid):
    p = db.get_project(pid)
    if not p:
        return jsonify({'error': 'not found'}), 404
    p['stats'] = db.get_project_stats(pid)
    return jsonify(p)


# === Queue ===

@app.route('/ainstein/api/projects/<int:pid>/queue', methods=['GET'])
def list_queue(pid):
    return jsonify(db.get_queue(pid))

@app.route('/ainstein/api/projects/<int:pid>/queue', methods=['POST'])
def add_queue(pid):
    data = request.get_json()
    qid = db.add_to_queue(pid, data['topic'], data.get('priority', 5), data.get('source', 'user'))
    return jsonify({'id': qid}), 201


# === Sessions ===

@app.route('/ainstein/api/projects/<int:pid>/sessions')
def list_sessions(pid):
    return jsonify(db.get_sessions(pid))

@app.route('/ainstein/api/projects/<int:pid>/sessions/<int:sid>')
def get_session(pid, sid):
    s = db.get_session(sid)
    if not s or s['project_id'] != pid:
        return jsonify({'error': 'not found'}), 404
    return jsonify(s)

@app.route('/ainstein/api/projects/<int:pid>/sessions/run', methods=['POST'])
def run_session(pid):
    import threading
    data = request.get_json() or {}
    def _run():
        from agents.researcher import run_research_session
        run_research_session(pid, topic=data.get('topic'))
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({'status': 'started'})


# === Findings ===

@app.route('/ainstein/api/projects/<int:pid>/findings')
def list_findings(pid):
    status = request.args.get('status')
    category = request.args.get('category')
    limit = int(request.args.get('limit', 50))
    return jsonify(db.get_findings(pid, limit=limit, status=status, category=category))


# === Datasets ===

@app.route('/ainstein/api/projects/<int:pid>/datasets', methods=['GET'])
def list_datasets(pid):
    return jsonify(db.get_datasets(pid))

@app.route('/ainstein/api/projects/<int:pid>/datasets/upload', methods=['POST'])
def upload_dataset(pid):
    from config import DATA_DIR
    import pandas as pd

    f = request.files.get('file')
    if not f:
        return jsonify({'error': 'no file'}), 400

    proj_dir = os.path.join(DATA_DIR, str(pid))
    os.makedirs(proj_dir, exist_ok=True)
    filename = f.filename
    filepath = os.path.join(proj_dir, filename)
    f.save(filepath)

    # Parse schema
    try:
        if filename.endswith('.csv'):
            df = pd.read_csv(filepath, nrows=100)
        else:
            df = pd.read_json(filepath)
        schema = [{'name': col, 'dtype': str(df[col].dtype)} for col in df.columns]
        row_count = len(pd.read_csv(filepath)) if filename.endswith('.csv') else len(pd.read_json(filepath))
    except Exception as e:
        schema = []
        row_count = 0
        logger.warning(f"Failed to parse dataset schema: {e}")

    did = db.add_dataset(pid, filename, 'upload', filepath, schema, row_count)
    return jsonify({'id': did, 'schema': schema, 'row_count': row_count}), 201


# === Scientist / Director ===

@app.route('/ainstein/api/projects/<int:pid>/directives')
def list_directives(pid):
    return jsonify(db.get_directives(pid))

@app.route('/ainstein/api/projects/<int:pid>/scientist/run', methods=['POST'])
def run_scientist(pid):
    from agents.scientist import run_scientist
    result = run_scientist(pid)
    return jsonify(result or {'status': 'no result'})

@app.route('/ainstein/api/projects/<int:pid>/memory')
def list_memory(pid):
    kind = request.args.get('kind')
    return jsonify(db.get_director_memories(pid, kind=kind))

@app.route('/ainstein/api/projects/<int:pid>/director/run', methods=['POST'])
def run_director(pid):
    from agents.director import run_director_daily
    result = run_director_daily(pid)
    return jsonify(result or {'status': 'no result'})


# ============================================================
# 硅基大脑 —— 认知元素 / 认知关系 / 知识图谱 / 认知边界
# 蓝图 §1.1 §2.4，业务逻辑见 cognitive.py
# ============================================================

def _ensure_brain(brain_id: int):
    """校验大脑存在，否则返回 (None, 404 response)。"""
    brain = db.get_brain(brain_id)
    if not brain:
        return None, (jsonify({'error': 'brain not found'}), 404)
    return brain, None


@app.route('/ainstein/api/brains/<int:brain_id>/cognitive-elements', methods=['GET'])
def list_cognitive_elements(brain_id: int):
    """列出指定大脑下的认知元素，支持类型 / 最低置信度 / 分页过滤。"""
    import cognitive
    _, err = _ensure_brain(brain_id)
    if err:
        return err
    ce_type = request.args.get('type')
    min_conf = request.args.get('min_confidence', type=float)
    limit = request.args.get('limit', default=50, type=int)
    offset = request.args.get('offset', default=0, type=int)
    try:
        items = cognitive.list_elements(
            brain_id=brain_id,
            ce_type=ce_type,
            min_confidence=min_conf,
            limit=limit,
            offset=offset,
        )
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'items': items, 'limit': limit, 'offset': offset})


@app.route('/ainstein/api/brains/<int:brain_id>/cognitive-elements', methods=['POST'])
def create_cognitive_element(brain_id: int):
    """创建认知元素。请求体字段：type / title / content / confidence /
    source_agent_id / metadata。"""
    import cognitive
    _, err = _ensure_brain(brain_id)
    if err:
        return err
    data = request.get_json() or {}
    try:
        element = cognitive.create_element(
            brain_id=brain_id,
            ce_type=data.get('type'),
            title=data.get('title', ''),
            content=data.get('content', ''),
            confidence=data.get('confidence', 0.5),
            source_agent_id=data.get('source_agent_id'),
            metadata_json=data.get('metadata') or data.get('metadata_json'),
        )
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify(element), 201


@app.route('/ainstein/api/brains/<int:brain_id>/cognitive-elements/<int:ce_id>',
           methods=['GET'])
def get_cognitive_element(brain_id: int, ce_id: int):
    """获取单个认知元素详情。"""
    import cognitive
    element = cognitive.get_element(ce_id)
    if not element or element['brain_id'] != brain_id:
        return jsonify({'error': 'cognitive element not found'}), 404
    return jsonify(element)


@app.route('/ainstein/api/brains/<int:brain_id>/cognitive-elements/<int:ce_id>',
           methods=['PUT'])
def update_cognitive_element_api(brain_id: int, ce_id: int):
    """更新认知元素。支持的字段见 cognitive.update_element。
    若请求体含 ``confidence_reason``，将走 ``update_confidence`` 路径以记录变更历史。"""
    import cognitive
    existing = cognitive.get_element(ce_id)
    if not existing or existing['brain_id'] != brain_id:
        return jsonify({'error': 'cognitive element not found'}), 404
    data = request.get_json() or {}

    reason = data.pop('confidence_reason', None)
    if reason is not None and 'confidence' in data:
        try:
            cognitive.update_confidence(ce_id, data.pop('confidence'), reason=reason)
        except ValueError as e:
            return jsonify({'error': str(e)}), 400

    if data:
        try:
            cognitive.update_element(ce_id, data)
        except ValueError as e:
            return jsonify({'error': str(e)}), 400

    return jsonify(cognitive.get_element(ce_id))


@app.route('/ainstein/api/brains/<int:brain_id>/cognitive-relations', methods=['GET'])
def list_cognitive_relations(brain_id: int):
    """列出认知关系。可选 query: src_id / dst_id / relation / element_id (取该节点全部边)。"""
    import cognitive
    _, err = _ensure_brain(brain_id)
    if err:
        return err

    element_id = request.args.get('element_id', type=int)
    if element_id is not None:
        direction = request.args.get('direction', default='both')
        try:
            return jsonify({'items': cognitive.get_relations(element_id, direction=direction)})
        except ValueError as e:
            return jsonify({'error': str(e)}), 400

    src_id = request.args.get('src_id', type=int)
    dst_id = request.args.get('dst_id', type=int)
    relation = request.args.get('relation')
    rows = db.get_cognitive_relations(brain_id, src_id=src_id, dst_id=dst_id, relation=relation)
    return jsonify({'items': rows})


@app.route('/ainstein/api/brains/<int:brain_id>/cognitive-relations', methods=['POST'])
def create_cognitive_relation_api(brain_id: int):
    """创建认知关系。请求体：source_id / target_id / relation_type / weight / created_by_agent_id。"""
    import cognitive
    _, err = _ensure_brain(brain_id)
    if err:
        return err
    data = request.get_json() or {}
    try:
        rel = cognitive.create_relation(
            source_id=int(data['source_id']),
            target_id=int(data['target_id']),
            relation_type=data.get('relation_type') or data.get('relation'),
            weight=data.get('weight', 0.5),
            created_by_agent_id=data.get('created_by_agent_id'),
        )
    except (KeyError, TypeError) as e:
        return jsonify({'error': f'missing field: {e}'}), 400
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    if not rel or rel.get('brain_id') != brain_id:
        return jsonify({'error': 'relation not created or brain mismatch'}), 400
    return jsonify(rel), 201


@app.route('/ainstein/api/brains/<int:brain_id>/knowledge-graph', methods=['GET'])
def get_knowledge_graph_api(brain_id: int):
    """返回前端力导向图所需的 nodes + edges 结构。

    Query 参数：
      - ``types``: 逗号分隔的 CE 类型白名单
      - ``limit``: 节点上限，默认 200
    """
    import cognitive
    _, err = _ensure_brain(brain_id)
    if err:
        return err
    types_param = request.args.get('types')
    ce_types = [t.strip() for t in types_param.split(',')] if types_param else None
    limit = request.args.get('limit', default=200, type=int)
    try:
        graph = cognitive.get_knowledge_graph(brain_id, ce_types=ce_types, limit=limit)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify(graph)


@app.route('/ainstein/api/brains/<int:brain_id>/frontier', methods=['GET'])
def get_frontier_api(brain_id: int):
    """获取大脑认知边界（最近 / 低置信度 / 未被支撑 三类元素的并集）。"""
    import cognitive
    _, err = _ensure_brain(brain_id)
    if err:
        return err
    limit = request.args.get('limit', default=50, type=int)
    ceiling = request.args.get('confidence_ceiling', default=0.7, type=float)
    return jsonify(cognitive.get_frontier(
        brain_id, limit=limit, confidence_ceiling=ceiling
    ))


if __name__ == '__main__':
    db.init_db()
    app.run(debug=True, port=9089)
