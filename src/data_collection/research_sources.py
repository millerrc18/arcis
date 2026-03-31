"""Research source crawlers for nightly paper collection.

Called by: research_collector.py
Calls: requests, xml.etree, Reddit/GitHub/arXiv/HF feeds
"""

import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger(__name__)
TZ = ZoneInfo("America/New_York")
USER_AGENT = "Arcis Research Collector halcyonlabai@gmail.com"

RELEVANCE_KEYWORDS = [
    "trading", "portfolio", "equity", "stock", "fine-tun", "lora", "qlora",
    "rlhf", "dpo", "grpo", "regime", "volatility", "momentum", "mean-reversion",
    "pullback", "sentiment", "financial language model", "market prediction",
    "swing trad", "position siz", "risk manage", "backtest", "walk-forward",
]


def _get(url: str, timeout: int = 15, **kwargs) -> requests.Response:
    """HTTP GET with standard User-Agent and timeout."""
    headers = kwargs.pop("headers", {})
    headers.setdefault("User-Agent", USER_AGENT)
    return requests.get(url, headers=headers, timeout=timeout, **kwargs)


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
    except Exception as exc:
        logger.warning("[RESEARCH] arXiv fetch failed: %s", exc)
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
            author.findtext("atom:name", "", ns) for author in entry.findall("atom:author", ns)
        )
        link = entry.findtext("atom:id", "", ns) or ""

        if not any(keyword in (title + " " + abstract).lower() for keyword in RELEVANCE_KEYWORDS):
            continue

        papers.append(
            {
                "source": "arxiv",
                "external_id": f"arxiv:{arxiv_id}",
                "title": title,
                "authors": authors,
                "abstract": abstract[:2000],
                "url": link,
                "published_date": published,
            }
        )
    return papers


def crawl_huggingface(max_results: int = 20) -> list[dict]:
    """Crawl HuggingFace daily papers API."""
    try:
        resp = _get(f"https://huggingface.co/api/daily_papers?limit={max_results}")
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("[RESEARCH] HuggingFace fetch failed: %s", exc)
        return []

    papers = []
    for item in data:
        paper = item.get("paper", {})
        title = paper.get("title", "")
        abstract = paper.get("summary", "")
        if not any(keyword in (title + " " + abstract).lower() for keyword in RELEVANCE_KEYWORDS):
            continue
        papers.append(
            {
                "source": "huggingface",
                "external_id": f"hf:{paper.get('id', '')}",
                "title": title,
                "authors": ", ".join(author.get("name", "") for author in paper.get("authors", [])),
                "abstract": abstract[:2000],
                "url": f"https://huggingface.co/papers/{paper.get('id', '')}",
                "published_date": item.get("publishedAt", "")[:10],
            }
        )
    return papers


def crawl_reddit() -> list[dict]:
    """Crawl top posts from quantitative trading subreddits."""
    papers = []
    for subreddit in ["quant", "algotrading"]:
        try:
            resp = _get(
                f"https://www.reddit.com/r/{subreddit}/top/.json?t=day&limit=10",
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("[RESEARCH] Reddit r/%s fetch failed: %s", subreddit, exc)
            continue

        for child in data.get("data", {}).get("children", []):
            post = child.get("data", {})
            if post.get("score", 0) < 20:
                continue
            if post.get("link_flair_text", "").lower() in ("meme", "meta"):
                continue
            papers.append(
                {
                    "source": "reddit",
                    "external_id": f"reddit:{post.get('id', '')}",
                    "title": post.get("title", ""),
                    "authors": post.get("author", ""),
                    "abstract": (post.get("selftext", "") or "")[:1000],
                    "url": f"https://reddit.com{post.get('permalink', '')}",
                    "published_date": datetime.fromtimestamp(
                        post.get("created_utc", 0), tz=TZ
                    ).strftime("%Y-%m-%d"),
                }
            )
        time.sleep(2)
    return papers


def crawl_github_trending() -> list[dict]:
    """Check GitHub trending repos for finance/trading/ML."""
    yesterday = (datetime.now(TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
    url = (
        "https://api.github.com/search/repositories?"
        f"q=created:>{yesterday}+stars:>10&sort=stars&per_page=20"
    )
    try:
        resp = _get(url)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("[RESEARCH] GitHub fetch failed: %s", exc)
        return []

    papers = []
    for repo in data.get("items", []):
        combined = ((repo.get("description") or "") + " " + (repo.get("name") or "")).lower()
        if not any(keyword in combined for keyword in ["trading", "quant", "lora", "financial", "portfolio", "backtest"]):
            continue
        papers.append(
            {
                "source": "github",
                "external_id": f"gh:{repo.get('full_name', '')}",
                "title": repo.get("full_name", ""),
                "authors": repo.get("owner", {}).get("login", ""),
                "abstract": (repo.get("description") or "")[:500],
                "url": repo.get("html_url", ""),
                "published_date": (repo.get("created_at") or "")[:10],
            }
        )
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

            for item in root.findall(".//item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                desc = (item.findtext("description") or "").strip()
                pub = (item.findtext("pubDate") or "")[:10]
                papers.append(
                    {
                        "source": source,
                        "external_id": f"{source}:{link}",
                        "title": title,
                        "authors": source.replace("_blog", "").title(),
                        "abstract": desc[:1000],
                        "url": link,
                        "published_date": pub,
                    }
                )

            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("atom:entry", ns):
                title = (entry.findtext("atom:title", "", ns) or "").strip()
                link_el = entry.find("atom:link", ns)
                link = link_el.get("href", "") if link_el is not None else ""
                desc = (entry.findtext("atom:summary", "", ns) or "").strip()
                pub = (entry.findtext("atom:published", "", ns) or "")[:10]
                papers.append(
                    {
                        "source": source,
                        "external_id": f"{source}:{link}",
                        "title": title,
                        "authors": source.replace("_blog", "").title(),
                        "abstract": desc[:1000],
                        "url": link,
                        "published_date": pub,
                    }
                )
        except Exception as exc:
            logger.warning("[RESEARCH] %s fetch failed: %s", source, exc)

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
    except Exception as exc:
        logger.warning("[RESEARCH] SSRN fetch failed: %s", exc)
        return []

    papers = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        desc = (item.findtext("description") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not any(keyword in (title + " " + desc).lower() for keyword in RELEVANCE_KEYWORDS):
            continue
        ssrn_id = re.search(r"abstract_id=(\d+)", link)
        external_id = f"ssrn:{ssrn_id.group(1)}" if ssrn_id else f"ssrn:{link}"
        papers.append(
            {
                "source": "ssrn",
                "external_id": external_id,
                "title": title,
                "authors": "",
                "abstract": desc[:2000],
                "url": link,
                "published_date": (item.findtext("pubDate") or "")[:10],
            }
        )
    return papers
