"""Dataset loading utilities."""
import os
import logging
import pandas as pd
from config import DATA_DIR

logger = logging.getLogger(__name__)


def load_dataset(project_id, dataset_name):
    """Load a dataset file into a DataFrame."""
    proj_dir = os.path.join(DATA_DIR, str(project_id))
    filepath = os.path.join(proj_dir, dataset_name)
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Dataset not found: {filepath}")
    ext = os.path.splitext(filepath)[1].lower()
    if ext == '.csv':
        return pd.read_csv(filepath)
    elif ext in ('.json', '.jsonl'):
        return pd.read_json(filepath)
    elif ext in ('.xlsx', '.xls'):
        return pd.read_excel(filepath)
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def get_dataset_summary(project_id, datasets):
    """Build a text summary of available datasets for LLM context."""
    if not datasets:
        return "No datasets available."
    lines = []
    for ds in datasets:
        schema = ds.get('schema_json')
        if isinstance(schema, str):
            import json
            try:
                schema = json.loads(schema)
            except Exception:
                schema = []
        cols = ', '.join(f"{c['name']}({c['dtype']})" for c in (schema or []))
        lines.append(f"- {ds['name']}: {ds.get('row_count', 0)} rows, columns: {cols}")
    return '\n'.join(lines)
