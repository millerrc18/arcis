"""Research intelligence collector — discovers and scores papers/posts nightly.

Sources: arXiv, SSRN, HuggingFace daily papers, Reddit, GitHub trending,
         Anthropic/OpenAI blogs, SEC/FINRA regulatory.

Relevance scoring via Ollama (zero API cost).
Runs as collector #13 in the overnight pipeline.
"""

import json
import logging
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger(__name__)
TZ = ZoneInfo("America/New_York")

USER_AGENT = "Halcyon Lab Research Collector halcyonlabai@gmail.com"

# Keywords for filtering relevant papers
RELEVANCE_KEYWORDS = [
    "trading", "portfolio", "equity", "stock", "fine-tun", "lora", "qlora",
    "rlhf", "dpo", "grpo", "regime", "volatility", "momentum", "mean-reversion",
    "pullback", "sentiment", "financial language model", "market prediction",
    "swing trad", "position siz", "risk manage", "backtest", "walk-forward",
]

RELEVANCE_PROMPT = """Rate how relevant this paper/post is to an AI-powered equity swing trading system that:
- Fine-tunes Qwen3 8B via QLoRA for trade commentary generation
- Uses pullback-in-uptrend strategy on S&P 100 stocks (2-15 day holds)
- Has a self-blinding training pipeline with DPO preference optimization
- Monitors market regimes and adapts position sizing
- Is building toward walk-forward validated, statistically proven edge

Score 0.0 to 1.0 where:
0.0 = completely irrelevant
0.3 = tangentially related (general ML or general finance)
0.6 = moderately relevant (touches one of our focus areas)
0.8 = highly relevant (directly applicable technique or finding)
1.0 = critical (must-read, directly impacts our architecture)

Respond with ONLY a JSON object: {{"score": 0.X, "reason": "one sentence why"}}

TITLE: {title}
ABSTRACT: {abstract}
"""


def _get(url: str, timeout: int = 15, **kwargs) -> requests.Response:
    """HTTP GET with standard User-Agent and timeout."""
    headers = kwargs.pop("headers", {})
    headers.setdefault("User-Agent", USER_AGENT)
    return requests.get(url, headers=headers, timeout=timeout, **kwargs)


# ── Source Crawlers ──────────────────────────────────────────────────


def crawl_arxiv(max_results: int = 30) -> list[dict]:
    """Crawl arXiv for quantitative finance and ML papers from last 48 hours."""
    url = (
        "http://export.arxiv.org/api/query?"
        "search_query=cat:q-fin.*+OR+cat:cs.LG&"
        f"sortBy=submittedDate&sortOrder=descending&max_results={max_results}"
    )
    try:
        resp = _get(url, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        logger.warning("[RESEARCH] arXiv fetch failed: %s", e)
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(resp.text)
    papers = []
    for entry in root.findall("atom:entry", ns):
        title = (entry.findtext("atom:title", "", ns) or "").strip().replace("\n", " ")
        abstract = (entry.findtext("atom:summary", "", ns) or "").strip().replace("\n", " ")
        arxiv_id = (entry.findtext("atom:id", "", ns) or "").split("/abs/")[-1]
        published = (entry.findtext("atom:published", "", ns) or "")[:10]
        authors = ", ".join(
            a.findtext("atom:name", "", ns) for a in entry.findall("atom:author", ns)
        )
        link = entry.findtext("atom:id", "", ns) or ""

        # Filter by keywords
        text_lower = (title + " " + abstract).lower()
        if not any(kw in text_lower for kw in RELEVANCE_KEYWORDS):
            continue

        papers.append({
            "source": "arxiv",
            "external_id": f"arxiv:{arxiv_id}",
            "title": title,
            "authors": authors,
            "abstract": abstract[:2000],
            "url": link,
            "published_date": published,
        })

    return papers


def crawl_huggingface(max_results: int = 20) -> list[dict]:
    """Crawl HuggingFace daily papers API."""
    try:
        resp = _get(f"https://huggingface.co/api/daily_papers?limit={max_results}")
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("[RESEARCH] HuggingFace fetch failed: %s", e)
        return []

    papers = []
    for item in data:
        paper = item.get("paper", {})
        title = paper.get("title", "")
        abstract = paper.get("summary", "")

        text_lower = (title + " " + abstract).lower()
        if not any(kw in text_lower for kw in RELEVANCE_KEYWORDS):
            continue

        papers.append({
            "source": "huggingface",
            "external_id": f"hf:{paper.get('id', '')}",
            "title": title,
            "authors": ", ".join(a.get("name", "") for a in paper.get("authors", [])),
            "abstract": abstract[:2000],
            "url": f"https://huggingface.co/papers/{paper.get('id', '')}",
            "published_date": item.get("publishedAt", "")[:10],
        })

    return papers


def crawl_reddit() -> list[dict]:
    """Crawl top posts from quantitative trading subreddits."""
    papers = []
    for sub in ["quant", "algotrading"]:
        try:
            resp = _get(
                f"https://www.reddit.com/r/{sub}/top/.json?t=day&limit=10",
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("[RESEARCH] Reddit r/%s fetch failed: %s", sub, e)
            continue

        for child in data.get("data", {}).get("children", []):
            post = child.get("data", {})
            if post.get("score", 0) < 20:
                continue
            if post.get("link_flair_text", "").lower() in ("meme", "meta"):
                continue

            papers.append({
                "source": "reddit",
                "external_id": f"reddit:{post.get('id', '')}",
                "title": post.get("title", ""),
                "authors": post.get("author", ""),
                "abstract": (post.get("selftext", "") or "")[:1000],
                "url": f"https://reddit.com{post.get('permalink', '')}",
                "published_date": datetime.fromtimestamp(
                    post.get("created_utc", 0), tz=TZ
                ).strftime("%Y-%m-%d"),
            })
        time.sleep(2)  # Reddit rate limit

    return papers


def crawl_github_trending() -> list[dict]:
    """Check GitHub trending repos for finance/trading/ML."""
    yesterday = (datetime.now(TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
    url = (
        f"https://api.github.com/search/repositories?"
        f"q=created:>{yesterday}+stars:>10&sort=stars&per_page=20"
    )
    try:
        resp = _get(url)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("[RESEARCH] GitHub fetch failed: %s", e)
        return []

    papers = []
    for repo in data.get("items", []):
        desc = (repo.get("description") or "").lower()
        name = (repo.get("name") or "").lower()
        combined = desc + " " + name
        if not any(kw in combined for kw in ["trading", "quant", "lora", "financial", "portfolio", "backtest"]):
            continue

        papers.append({
            "source": "github",
            "external_id": f"gh:{repo.get('full_name', '')}",
            "title": repo.get("full_name", ""),
            "authors": repo.get("owner", {}).get("login", ""),
            "abstract": repo.get("description", "")[:500],
            "url": repo.get("html_url", ""),
            "published_date": (repo.get("created_at") or "")[:10],
        })

    return papers


def crawl_ai_blogs() -> list[dict]:
    """Check Anthropic and OpenAI blogs for new posts."""
    papers = []
    feeds = [
        ("anthropic_blog", "https://www.anthropic.com/feed.xml"),
        ("openai_blog", "https://openai.com/blog/rss/"),
    ]

    for source, url in feeds:
        try:
            resp = _get(url, timeout=15)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)

            # Try RSS format
            for item in root.findall(".//item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                desc = (item.findtext("description") or "").strip()
                pub = (item.findtext("pubDate") or "")[:10]

                papers.append({
                    "source": source,
                    "external_id": f"{source}:{link}",
                    "title": title,
                    "authors": source.replace("_blog", "").title(),
                    "abstract": desc[:1000],
                    "url": link,
                    "published_date": pub,
                })

            # Try Atom format
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("atom:entry", ns):
                title = (entry.findtext("atom:title", "", ns) or "").strip()
                link_el = entry.find("atom:link", ns)
                link = link_el.get("href", "") if link_el is not None else ""
                desc = (entry.findtext("atom:summary", "", ns) or "").strip()
                pub = (entry.findtext("atom:published", "", ns) or "")[:10]

                papers.append({
                    "source": source,
                    "external_id": f"{source}:{link}",
                    "title": title,
                    "authors": source.replace("_blog", "").title(),
                    "abstract": desc[:1000],
                    "url": link,
                    "published_date": pub,
                })
        except Exception as e:
            logger.warning("[RESEARCH] %s fetch failed: %s", source, e)

    return papers


def crawl_ssrn() -> list[dict]:
    """Crawl SSRN new finance papers RSS feed."""
    url = (
        "https://papers.ssrn.com/sol3/Jrnl_SSRN_Rss.cfm?"
        "npage=1&nstartper=0&nsortby=ab_approval_date&abstractlength=500&lim=10&ntype=1"
    )
    try:
        resp = _get(url, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
    except Exception as e:
        logger.warning("[RESEARCH] SSRN fetch failed: %s", e)
        return []

    papers = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        desc = (item.findtext("description") or "").strip()
        link = (item.findtext("link") or "").strip()

        text_lower = (title + " " + desc).lower()
        if not any(kw in text_lower for kw in RELEVANCE_KEYWORDS):
            continue

        ssrn_id = re.search(r'abstract_id=(\d+)', link)
        ext_id = f"ssrn:{ssrn_id.group(1)}" if ssrn_id else f"ssrn:{link}"

        papers.append({
            "source": "ssrn",
            "external_id": ext_id,
            "title": title,
            "authors": "",
            "abstract": desc[:2000],
            "url": link,
            "published_date": (item.findtext("pubDate") or "")[:10],
        })

    return papers
# ── Deduplication ────────────────────────────────────────────────────


def is_duplicate(external_id: str, db_path: str) -> bool:
    """Check if paper already exists in database."""
    try:
        with sqlite3.connect(db_path) as conn:
            return conn.execute(
                'SELECT 1 FROM research_papers WHERE external_id = ?', (external_id,)
            ).fetchone() is not None
    except Exception:
        return False


# ── Relevance Scoring ────────────────────────────────────────────────


def score_relevance(title: str, abstract: str) -> tuple[float, str]:
    """Score paper relevance using Ollama (zero API cost)."""
    try:
        from src.llm.client import generate
        prompt = RELEVANCE_PROMPT.format(title=title, abstract=(abstract or "")[:1000])
        response = generate(prompt, "You are a research relevance scorer. Respond only with JSON.", temperature=0.1)

        if response:
            # Try to parse JSON from response
            json_match = re.search(r'\{[^}]+\}', response)
            if json_match:
                data = json.loads(json_match.group())
                score = float(data.get("score", 0.3))
                reason = data.get("reason", "")
                return max(0.0, min(1.0, score)), reason
    except Exception as e:
        logger.debug("[RESEARCH] Relevance scoring failed: %s", e)

    # Default: keyword-based scoring
    text = (title + " " + (abstract or "")).lower()
    hits = sum(1 for kw in RELEVANCE_KEYWORDS if kw in text)
    default_score = min(0.9, 0.2 + hits * 0.1)
    return default_score, "keyword-based score (LLM unavailable)"


# ── Storage ──────────────────────────────────────────────────────────


def _store_paper(paper: dict, score: float, reason: str,
                 db_path: str) -> None:
    """Store a paper in the research_papers table."""
    now = datetime.now(TZ).isoformat()
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """INSERT OR IGNORE INTO research_papers
                   (source, external_id, title, authors, abstract, url,
                    published_date, relevance_score, relevance_reason, collected_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    paper.get("source", ""),
                    paper.get("external_id", ""),
                    paper.get("title", ""),
                    paper.get("authors", ""),
                    paper.get("abstract", ""),
                    paper.get("url", ""),
                    paper.get("published_date", ""),
                    score,
                    reason,
                    now,
                ),
            )
    except Exception as e:
        logger.warning("[RESEARCH] Failed to store paper: %s", e)


# ── Main Collector ───────────────────────────────────────────────────


def collect_research_papers(db_path: str = "ai_research_desk.sqlite3") -> dict:
    """Nightly research paper collection. Returns {source: count} dict."""
    results = {}
    all_papers = []

    for name, crawler in [
        ("arxiv", crawl_arxiv),
        ("ssrn", crawl_ssrn),
        ("huggingface", crawl_huggingface),
        ("reddit", crawl_reddit),
        ("github", crawl_github_trending),
        ("ai_blogs", crawl_ai_blogs),
    ]:
        try:
            papers = crawler()
            new_papers = [p for p in papers if not is_duplicate(p.get("external_id", ""), db_path)]
            all_papers.extend(new_papers)
            results[name] = len(new_papers)
            logger.info("[RESEARCH] %s: %d new papers", name, len(new_papers))
        except Exception as e:
            logger.warning("[RESEARCH] %s crawl failed: %s", name, e)
            results[name] = 0

    # Score relevance and store
    stored = 0
    for paper in all_papers:
        score, reason = score_relevance(paper["title"], paper.get("abstract", ""))
        if score >= 0.4:
            _store_paper(paper, score, reason, db_path)
            stored += 1
        time.sleep(0.5)  # Rate limit Ollama calls

    results["total_new"] = stored
    results["total_crawled"] = len(all_papers)

    logger.info("[RESEARCH] Collection complete: %d stored, %d crawled from %d sources",
                stored, len(all_papers), len(results) - 2)

    return results
