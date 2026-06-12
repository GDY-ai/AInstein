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


if __name__ == '__main__':
    db.init_db()
    app.run(debug=True, port=9089)
