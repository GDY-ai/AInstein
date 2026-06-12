"""Generic statistical tools for research."""
import logging
import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

logger = logging.getLogger(__name__)


def descriptive_stats(df, columns=None):
    """Compute descriptive statistics for numeric columns."""
    if columns:
        df = df[columns]
    numeric = df.select_dtypes(include=[np.number])
    result = numeric.describe().to_dict()
    return {'stats': result, 'columns': list(numeric.columns), 'rows': len(df)}


def correlation(df, col_a, col_b, method='pearson'):
    """Compute correlation between two columns."""
    a = pd.to_numeric(df[col_a], errors='coerce').dropna()
    b = pd.to_numeric(df[col_b], errors='coerce').dropna()
    aligned = pd.concat([a, b], axis=1).dropna()
    if len(aligned) < 3:
        return {'error': f'insufficient data: {len(aligned)} rows'}
    if method == 'pearson':
        r, p = scipy_stats.pearsonr(aligned[col_a], aligned[col_b])
    elif method == 'spearman':
        r, p = scipy_stats.spearmanr(aligned[col_a], aligned[col_b])
    else:
        return {'error': f'unknown method: {method}'}
    return {'correlation': round(r, 4), 'p_value': round(p, 6), 'n': len(aligned), 'method': method}


def t_test(df, col, group_col, group_a, group_b):
    """Independent t-test between two groups."""
    a = pd.to_numeric(df[df[group_col] == group_a][col], errors='coerce').dropna()
    b = pd.to_numeric(df[df[group_col] == group_b][col], errors='coerce').dropna()
    if len(a) < 2 or len(b) < 2:
        return {'error': f'insufficient data: group_a={len(a)}, group_b={len(b)}'}
    t, p = scipy_stats.ttest_ind(a, b)
    return {
        't_statistic': round(t, 4), 'p_value': round(p, 6),
        'mean_a': round(a.mean(), 4), 'mean_b': round(b.mean(), 4),
        'n_a': len(a), 'n_b': len(b),
    }


def regression(df, y_col, x_cols):
    """Multiple linear regression."""
    sub = df[[y_col] + x_cols].apply(pd.to_numeric, errors='coerce').dropna()
    if len(sub) < len(x_cols) + 2:
        return {'error': f'insufficient data: {len(sub)} rows'}
    y = sub[y_col].values
    X = sub[x_cols].values
    X_with_const = np.column_stack([np.ones(len(X)), X])
    try:
        coeffs, residuals, rank, sv = np.linalg.lstsq(X_with_const, y, rcond=None)
    except np.linalg.LinAlgError as e:
        return {'error': str(e)}
    y_pred = X_with_const @ coeffs
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    result = {'intercept': round(coeffs[0], 4), 'r_squared': round(r_squared, 4), 'n': len(sub)}
    for i, col in enumerate(x_cols):
        result[f'coef_{col}'] = round(coeffs[i + 1], 4)
    return result


def anomaly_detection(df, col, method='zscore', threshold=3.0):
    """Detect anomalies in a column."""
    series = pd.to_numeric(df[col], errors='coerce').dropna()
    if len(series) < 5:
        return {'error': f'insufficient data: {len(series)} rows'}
    if method == 'zscore':
        z = np.abs(scipy_stats.zscore(series))
        anomalies = series[z > threshold]
    elif method == 'iqr':
        q1, q3 = series.quantile(0.25), series.quantile(0.75)
        iqr = q3 - q1
        anomalies = series[(series < q1 - 1.5 * iqr) | (series > q3 + 1.5 * iqr)]
    else:
        return {'error': f'unknown method: {method}'}
    return {
        'total': len(series), 'anomalies': len(anomalies),
        'anomaly_pct': round(len(anomalies) / len(series) * 100, 2),
        'mean': round(series.mean(), 4), 'std': round(series.std(), 4),
        'anomaly_indices': anomalies.index[:20].tolist(),
    }


def distribution_fit(df, col):
    """Test normality and return distribution stats."""
    series = pd.to_numeric(df[col], errors='coerce').dropna()
    if len(series) < 8:
        return {'error': f'insufficient data: {len(series)} rows'}
    stat, p = scipy_stats.shapiro(series[:5000])
    return {
        'shapiro_statistic': round(stat, 4), 'p_value': round(p, 6),
        'is_normal': p > 0.05, 'n': len(series),
        'skewness': round(float(series.skew()), 4),
        'kurtosis': round(float(series.kurtosis()), 4),
    }


def group_stats(df, value_col, group_col):
    """Compute per-group statistics."""
    numeric_vals = pd.to_numeric(df[value_col], errors='coerce')
    grouped = numeric_vals.groupby(df[group_col])
    result = {}
    for name, group in grouped:
        result[str(name)] = {
            'count': int(group.count()),
            'mean': round(float(group.mean()), 4),
            'std': round(float(group.std()), 4),
            'median': round(float(group.median()), 4),
        }
    return result
