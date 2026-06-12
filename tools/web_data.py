"""External data fetching tools: Google, Wikipedia, arXiv, web."""
import logging
import requests
from urllib.parse import quote

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'AInstein-Research/1.0 (research@example.com)'
}


def web_search(query, num_results=10):
    """Search the web via DuckDuckGo Instant Answer API + Wikipedia fallback."""
    try:
        results = []
        # DuckDuckGo Instant Answer API (structured, no HTML parsing needed)
        url = 'https://api.duckduckgo.com/'
        params = {'q': query, 'format': 'json', 'no_html': 1, 'skip_disambig': 1}
        resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
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
        # Also search Wikipedia as supplementary source
        wiki_results = wikipedia_search(query, lang='en', limit=3)
        if 'results' in wiki_results:
            for wr in wiki_results['results']:
                results.append({
                    'title': wr['title'],
                    'url': wr['url'],
                    'snippet': wr['summary'][:200],
                    'source': 'Wikipedia',
                })
        return {'query': query, 'count': len(results), 'results': results[:num_results]}
    except Exception as e:
        logger.error(f"web_search failed: {e}")
        return {'error': str(e)}


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
        resp = requests.get(search_url, params=params, headers=HEADERS, timeout=15)
        data = resp.json()
        results = []
        for item in data.get('query', {}).get('search', []):
            title = item['title']
            # Get summary
            summary_url = f'https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(title)}'
            try:
                s_resp = requests.get(summary_url, headers=HEADERS, timeout=10)
                summary = s_resp.json().get('extract', '')
            except Exception:
                summary = item.get('snippet', '')
            results.append({
                'title': title,
                'summary': summary,
                'url': f'https://{lang}.wikipedia.org/wiki/{quote(title.replace(" ", "_"))}',
            })
        return {'query': query, 'lang': lang, 'count': len(results), 'results': results}
    except Exception as e:
        logger.error(f"wikipedia_search failed: {e}")
        return {'error': str(e)}


def arxiv_search(query, max_results=10):
    """Search arXiv for academic papers."""
    try:
        url = 'http://export.arxiv.org/api/query'
        search_q = f'all:"{query}"' if ' ' in query else f'all:{query}'
        params = {
            'search_query': search_q,
            'start': 0,
            'max_results': max_results,
            'sortBy': 'relevance',
        }
        resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            return {'error': f'HTTP {resp.status_code}'}
        # Parse Atom XML
        import xml.etree.ElementTree as ET
        root = ET.fromstring(resp.text)
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
        logger.error(f"arxiv_search failed: {e}")
        return {'error': str(e)}


def google_trends(query, geo='', timeframe='today 5-y'):
    """Fetch Google Trends data via pytrends (if available)."""
    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl='en-US', tz=360)
        keywords = [query] if isinstance(query, str) else query[:5]
        pytrends.build_payload(keywords, cat=0, timeframe=timeframe, geo=geo)
        interest = pytrends.interest_over_time()
        if interest.empty:
            return {'query': query, 'error': 'no data available'}
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
        return {'error': 'pytrends not installed. Run: pip install pytrends'}
    except Exception as e:
        logger.error(f"google_trends failed: {e}")
        return {'error': str(e)}
