"""Tool registry: maps tool names to implementations and provides LLM tool definitions."""
import logging
from tools import stats as stats_tools
from tools.data_access import load_dataset
from tools import web_data

logger = logging.getLogger(__name__)

_TOOLS = {}


def register_tool(name, func, schema):
    _TOOLS[name] = {'func': func, 'schema': schema}


def get_tool_names():
    return list(_TOOLS.keys())


def get_llm_tool_definitions():
    return [t['schema'] for t in _TOOLS.values()]


def dispatch(tool_name, params, project_id=None, datasets=None):
    """Execute a tool by name with given params. Returns result dict."""
    if tool_name not in _TOOLS:
        return {'error': f'unknown tool: {tool_name}'}
    tool = _TOOLS[tool_name]
    try:
        if tool_name in ('descriptive_stats', 'correlation', 't_test', 'regression',
                         'anomaly_detection', 'distribution_fit', 'group_stats'):
            ds_name = params.pop('dataset', None)
            if not ds_name and datasets:
                ds_name = datasets[0]['name']
            if not ds_name:
                return {'error': 'no dataset specified'}
            df = load_dataset(project_id, ds_name)
            return tool['func'](df, **params)
        return tool['func'](**params)
    except Exception as e:
        logger.error(f"Tool {tool_name} failed: {e}")
        return {'error': str(e)}


def _build_schema(name, description, properties, required):
    return {
        'name': name,
        'description': description,
        'input_schema': {
            'type': 'object',
            'properties': properties,
            'required': required,
        }
    }


# --- Register all built-in tools ---

register_tool('descriptive_stats', stats_tools.descriptive_stats, _build_schema(
    'descriptive_stats',
    'Compute descriptive statistics (mean, std, min, max, quartiles) for numeric columns.',
    {
        'dataset': {'type': 'string', 'description': 'Dataset filename'},
        'columns': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Column names (optional, defaults to all numeric)'},
    },
    ['dataset'],
))

register_tool('correlation', stats_tools.correlation, _build_schema(
    'correlation',
    'Compute correlation (Pearson or Spearman) between two numeric columns.',
    {
        'dataset': {'type': 'string', 'description': 'Dataset filename'},
        'col_a': {'type': 'string', 'description': 'First column name'},
        'col_b': {'type': 'string', 'description': 'Second column name'},
        'method': {'type': 'string', 'enum': ['pearson', 'spearman'], 'description': 'Correlation method'},
    },
    ['dataset', 'col_a', 'col_b'],
))

register_tool('t_test', stats_tools.t_test, _build_schema(
    't_test',
    'Independent t-test comparing a numeric column between two groups.',
    {
        'dataset': {'type': 'string', 'description': 'Dataset filename'},
        'col': {'type': 'string', 'description': 'Numeric column to compare'},
        'group_col': {'type': 'string', 'description': 'Column defining groups'},
        'group_a': {'type': 'string', 'description': 'First group value'},
        'group_b': {'type': 'string', 'description': 'Second group value'},
    },
    ['dataset', 'col', 'group_col', 'group_a', 'group_b'],
))

register_tool('regression', stats_tools.regression, _build_schema(
    'regression',
    'Multiple linear regression: predict Y from one or more X columns.',
    {
        'dataset': {'type': 'string', 'description': 'Dataset filename'},
        'y_col': {'type': 'string', 'description': 'Target variable column'},
        'x_cols': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Predictor columns'},
    },
    ['dataset', 'y_col', 'x_cols'],
))

register_tool('anomaly_detection', stats_tools.anomaly_detection, _build_schema(
    'anomaly_detection',
    'Detect anomalies/outliers in a numeric column using z-score or IQR method.',
    {
        'dataset': {'type': 'string', 'description': 'Dataset filename'},
        'col': {'type': 'string', 'description': 'Column to check'},
        'method': {'type': 'string', 'enum': ['zscore', 'iqr'], 'description': 'Detection method'},
        'threshold': {'type': 'number', 'description': 'Z-score threshold (default 3.0)'},
    },
    ['dataset', 'col'],
))

register_tool('distribution_fit', stats_tools.distribution_fit, _build_schema(
    'distribution_fit',
    'Test normality (Shapiro-Wilk) and return distribution characteristics (skewness, kurtosis).',
    {
        'dataset': {'type': 'string', 'description': 'Dataset filename'},
        'col': {'type': 'string', 'description': 'Column to analyze'},
    },
    ['dataset', 'col'],
))

register_tool('group_stats', stats_tools.group_stats, _build_schema(
    'group_stats',
    'Compute per-group statistics (count, mean, std, median) for a numeric column.',
    {
        'dataset': {'type': 'string', 'description': 'Dataset filename'},
        'value_col': {'type': 'string', 'description': 'Numeric column'},
        'group_col': {'type': 'string', 'description': 'Grouping column'},
    },
    ['dataset', 'value_col', 'group_col'],
))

# --- Web data tools ---

register_tool('web_search', web_data.web_search, _build_schema(
    'web_search',
    'Search the web for information. Returns titles, URLs, and snippets.',
    {
        'query': {'type': 'string', 'description': 'Search query'},
        'num_results': {'type': 'integer', 'description': 'Number of results (default 10)'},
    },
    ['query'],
))

register_tool('wikipedia_search', web_data.wikipedia_search, _build_schema(
    'wikipedia_search',
    'Search Wikipedia for article summaries. Supports multiple languages.',
    {
        'query': {'type': 'string', 'description': 'Search query'},
        'lang': {'type': 'string', 'description': 'Language code (en, zh, etc., default en)'},
        'limit': {'type': 'integer', 'description': 'Max results (default 5)'},
    },
    ['query'],
))

register_tool('arxiv_search', web_data.arxiv_search, _build_schema(
    'arxiv_search',
    'Search arXiv for academic papers. Returns titles, authors, abstracts.',
    {
        'query': {'type': 'string', 'description': 'Search query'},
        'max_results': {'type': 'integer', 'description': 'Max results (default 10)'},
    },
    ['query'],
))

register_tool('google_trends', web_data.google_trends, _build_schema(
    'google_trends',
    'Fetch Google Trends data: interest over time, trend direction, related queries.',
    {
        'query': {'type': 'string', 'description': 'Keyword or list of keywords (max 5)'},
        'geo': {'type': 'string', 'description': 'Geography code (e.g. US, CN, default worldwide)'},
        'timeframe': {'type': 'string', 'description': "Time range (default 'today 5-y')"},
    },
    ['query'],
))
