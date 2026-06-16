"""External data fetching tools: Google, Wikipedia, arXiv, web.

错误处理规范（v2）：
- 成功：返回 {"results": [...], "count": N, ...}
- 失败：返回 {"error": "描述", "recoverable": bool}，绝不抛异常给调用方
- 网络类异常（超时/连接错误）标记 recoverable=True，调用方可重试或后续再尝试
- 解析/参数类异常标记 recoverable=False
"""
import logging
import os
import time
import requests
from urllib.parse import quote

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'AInstein-Research/1.0 (research@example.com)'
}

# 代理：优先使用环境变量中的 HTTP_PROXY/HTTPS_PROXY（requests 默认会读取，
# 这里显式构造以便日志记录与单元测试覆盖）
def _build_proxies():
    http_proxy = os.environ.get('HTTP_PROXY') or os.environ.get('http_proxy')
    https_proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
    if not http_proxy and not https_proxy:
        return None
    return {
        'http': http_proxy or https_proxy,
        'https': https_proxy or http_proxy,
    }


def _request_with_retry(method, urls, *, max_retries=3, base_backoff=2.0,
                        timeout=30, **kwargs):
    """带指数退避的 HTTP 请求。

    :param urls: 候选 URL 列表（首选 + 备用镜像），从前到后依次尝试。
    :param max_retries: 每个 URL 的最大重试次数。
    :param base_backoff: 退避基数，第 i 次重试等待 base_backoff * 2**i 秒。
    :return: (response, None) 或 (None, error_dict)
    """
    proxies = _build_proxies()
    last_err = None
    for url in urls:
        for attempt in range(max_retries):
            try:
                resp = requests.request(
                    method, url, timeout=timeout, headers=HEADERS,
                    proxies=proxies, **kwargs,
                )
                if resp.status_code == 200:
                    return resp, None
                last_err = f'HTTP {resp.status_code} from {url}'
                # 4xx 不重试
                if 400 <= resp.status_code < 500:
                    break
            except (requests.Timeout, requests.ConnectionError) as e:
                last_err = f'{type(e).__name__}: {e}'
                logger.warning(
                    "HTTP retry url=%s attempt=%d/%d err=%s",
                    url, attempt + 1, max_retries, last_err,
                )
            except requests.RequestException as e:
                last_err = f'{type(e).__name__}: {e}'
                # 其他请求异常不重试，换下一个 URL
                break

            if attempt < max_retries - 1:
                time.sleep(base_backoff * (2 ** attempt))

    return None, {'error': last_err or 'unknown network error', 'recoverable': True}


def web_search(query, num_results=10):
    """Search the web via DuckDuckGo Instant Answer API + Wikipedia fallback."""
    try:
        results = []
        url = 'https://api.duckduckgo.com/'
        params = {'q': query, 'format': 'json', 'no_html': 1, 'skip_disambig': 1}
        resp, err = _request_with_retry(
            'GET', [url], max_retries=2, timeout=20, params=params,
        )
        if resp is not None:
            try:
                data = resp.json()
            except Exception as e:
                logger.warning("web_search DDG json decode failed: %s", e)
                data = {}
            if data.get('AbstractText'):
                results.append({
                    'title': data.get('Heading', query),
                    'url': data.get('AbstractURL', ''),
                    'snippet': data['AbstractText'],
                    'source': data.get('AbstractSource', ''),
                })
            for topic in data.get('RelatedTopics', [])[:num_results]:
                if isinstance(topic, dict) and 'Text' in topic:
                    results.append({
                        'title': topic.get('Text', '')[:80],
                        'url': topic.get('FirstURL', ''),
                        'snippet': topic.get('Text', ''),
                    })
        else:
            logger.warning("web_search DDG failed: %s", err)
        # 维基百科补充
        wiki_results = wikipedia_search(query, lang='en', limit=3)
        if 'results' in wiki_results:
            for wr in wiki_results['results']:
                results.append({
                    'title': wr['title'],
                    'url': wr['url'],
                    'snippet': wr['summary'][:200],
                    'source': 'Wikipedia',
                })
        if not results:
            return {
                'error': 'no results from any source',
                'recoverable': True,
                'query': query,
            }
        return {'query': query, 'count': len(results), 'results': results[:num_results]}
    except Exception as e:
        logger.exception("web_search unexpected failure")
        return {'error': str(e), 'recoverable': False}


def wikipedia_search(query, lang='en', limit=5):
    """Search Wikipedia and return article summaries."""
    try:
        search_url = f'https://{lang}.wikipedia.org/w/api.php'
        params = {
            'action': 'query',
            'list': 'search',
            'srsearch': query,
            'srlimit': limit,
            'format': 'json',
        }
        resp, err = _request_with_retry(
            'GET', [search_url], max_retries=3, timeout=20, params=params,
        )
        if resp is None:
            logger.error("wikipedia_search failed: %s", err)
            return {**(err or {}), 'query': query, 'lang': lang}
        try:
            data = resp.json()
        except Exception as e:
            return {'error': f'wikipedia json decode failed: {e}',
                    'recoverable': False}
        results = []
        for item in data.get('query', {}).get('search', []):
            title = item['title']
            summary_url = (
                f'https://{lang}.wikipedia.org/api/rest_v1/page/summary/'
                f'{quote(title)}'
            )
            summary = item.get('snippet', '')
            s_resp, _ = _request_with_retry(
                'GET', [summary_url], max_retries=2, timeout=15,
            )
            if s_resp is not None:
                try:
                    summary = s_resp.json().get('extract', summary)
                except Exception:
                    pass
            results.append({
                'title': title,
                'summary': summary,
                'url': f'https://{lang}.wikipedia.org/wiki/{quote(title.replace(" ", "_"))}',
            })
        return {'query': query, 'lang': lang, 'count': len(results), 'results': results}
    except Exception as e:
        logger.exception("wikipedia_search unexpected failure")
        return {'error': str(e), 'recoverable': False}


def arxiv_search(query, max_results=10):
    """Search arXiv for academic papers.

    超时/重试策略：
    - 单次请求 timeout=30s
    - 每个端点最多 3 次重试，间隔 2、4、8 秒（指数退避）
    - 主端点 export.arxiv.org，备用 arxiv.org（http，部分网络环境下更可达）
    - 若 ARXIV_MIRROR 环境变量已设置，优先使用该镜像
    """
    try:
        search_q = f'all:"{query}"' if ' ' in query else f'all:{query}'
        params = {
            'search_query': search_q,
            'start': 0,
            'max_results': max_results,
            'sortBy': 'relevance',
        }

        # 端点列表：主 → 备用 → （可选）国内镜像
        endpoints = [
            'http://export.arxiv.org/api/query',
            'http://arxiv.org/api/query',
        ]
        custom_mirror = os.environ.get('ARXIV_MIRROR')
        if custom_mirror:
            endpoints.insert(0, custom_mirror.rstrip('/'))

        resp, err = _request_with_retry(
            'GET', endpoints, max_retries=3, base_backoff=2.0,
            timeout=30, params=params,
        )
        if resp is None:
            logger.error("arxiv_search exhausted retries: %s", err)
            return {
                **(err or {'error': 'arxiv unreachable', 'recoverable': True}),
                'query': query,
            }

        # Parse Atom XML
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError as e:
            return {'error': f'arxiv xml parse failed: {e}',
                    'recoverable': False, 'query': query}
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        results = []
        for entry in root.findall('atom:entry', ns):
            title = entry.find('atom:title', ns)
            summary = entry.find('atom:summary', ns)
            published = entry.find('atom:published', ns)
            authors = [a.find('atom:name', ns).text for a in entry.findall('atom:author', ns)]
            link = entry.find('atom:id', ns)
            results.append({
                'title': title.text.strip() if title is not None else '',
                'authors': authors[:5],
                'published': published.text[:10] if published is not None else '',
                'summary': summary.text.strip()[:500] if summary is not None else '',
                'url': link.text.strip() if link is not None else '',
            })
        return {'query': query, 'count': len(results), 'results': results}
    except Exception as e:
        logger.exception("arxiv_search unexpected failure")
        return {'error': str(e), 'recoverable': False}


def google_trends(query, geo='', timeframe='today 5-y'):
    """Fetch Google Trends data via pytrends (if available)."""
    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl='en-US', tz=360)
        keywords = [query] if isinstance(query, str) else query[:5]
        pytrends.build_payload(keywords, cat=0, timeframe=timeframe, geo=geo)
        interest = pytrends.interest_over_time()
        if interest.empty:
            return {'query': query, 'error': 'no data available', 'recoverable': True}
        # Summarize: mean, max, trend direction
        summary = {}
        for kw in keywords:
            if kw in interest.columns:
                series = interest[kw]
                recent = series.tail(52).mean()
                earlier = series.head(52).mean()
                trend = 'rising' if recent > earlier * 1.1 else ('falling' if recent < earlier * 0.9 else 'stable')
                summary[kw] = {
                    'mean': round(float(series.mean()), 1),
                    'max': int(series.max()),
                    'recent_52w_mean': round(float(recent), 1),
                    'earlier_52w_mean': round(float(earlier), 1),
                    'trend': trend,
                }
        related = {}
        try:
            rq = pytrends.related_queries()
            for kw in keywords:
                if kw in rq and rq[kw]['top'] is not None:
                    related[kw] = rq[kw]['top'].head(10).to_dict('records')
        except Exception:
            pass
        return {'query': query, 'timeframe': timeframe, 'geo': geo, 'interest': summary, 'related': related}
    except ImportError:
        return {'error': 'pytrends not installed. Run: pip install pytrends',
                'recoverable': False}
    except Exception as e:
        logger.exception("google_trends unexpected failure")
        return {'error': str(e), 'recoverable': True}
