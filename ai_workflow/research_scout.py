from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable


ARXIV_API = "https://export.arxiv.org/api/query"
CROSSREF_API = "https://api.crossref.org/works"
USER_AGENT = "ai-workflow-control-plane/2.3 (+https://github.com/Taki7980/ai-workflow-control-plane-v2)"
TRUSTED_RESEARCH_HOSTS = frozenset({"export.arxiv.org", "api.crossref.org"})
MAX_RESEARCH_RESPONSE_BYTES = 8 * 1024 * 1024

PROJECT_TERMS = {
    "agent": 2,
    "agents": 2,
    "agentic": 3,
    "code agent": 4,
    "coding agent": 4,
    "repository": 3,
    "software engineering": 3,
    "retrieval": 3,
    "context selection": 4,
    "context compression": 4,
    "prompt compression": 4,
    "token efficiency": 4,
    "token-efficient": 4,
    "memory": 2,
    "rag": 2,
    "llm": 2,
    "large language model": 2,
    "multi-agent": 3,
    "tool use": 2,
    "planning": 2,
    "uncertainty": 2,
    "calibration": 2,
    "abstention": 3,
    "ranking": 2,
    "bm25": 4,
    "reciprocal rank fusion": 4,
    "rrf": 3,
    "maximal marginal relevance": 4,
    "mmr": 3,
    "submodular": 4,
    "facility location": 4,
    "graph retrieval": 4,
    "code graph": 4,
    "program analysis": 3,
    "static analysis": 3,
    "benchmark": 2,
    "mathematical optimization": 3,
    "optimization": 1,
}

RELEVANT_CATEGORIES = {
    "cs.AI", "cs.CL", "cs.LG", "cs.SE", "cs.IR", "cs.PL", "cs.MA",
    "stat.ML", "math.OC", "math.CO",
}


@dataclass(frozen=True)
class Paper:
    arxiv_id: str
    title: str
    summary: str
    authors: tuple[str, ...]
    categories: tuple[str, ...]
    published: str
    updated: str
    doi: str | None
    url: str
    verification: str = "arxiv-primary"
    crossref_url: str | None = None


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _validated_research_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("research URL must use a trusted HTTPS endpoint") from exc

    hostname = (parsed.hostname or "").rstrip(".").lower()
    if (
        parsed.scheme.lower() != "https"
        or hostname not in TRUSTED_RESEARCH_HOSTS
        or parsed.username
        or parsed.password
        or port not in (None, 443)
    ):
        raise ValueError("research URL must use a trusted HTTPS endpoint")
    return url


def _request(url: str, timeout: int = 25) -> bytes:
    validated = _validated_research_url(url)
    req = urllib.request.Request(  # noqa: S310 - exact HTTPS host allowlist above
        validated,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, application/atom+xml",
        },
    )
    opener = urllib.request.build_opener(_NoRedirectHandler())
    with opener.open(  # noqa: S310 - redirects disabled; exact host allowlist above
        req,
        timeout=timeout,
    ) as response:
        raw = response.read(MAX_RESEARCH_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESEARCH_RESPONSE_BYTES:
        raise ValueError("research response exceeded maximum allowed size")
    return raw


def _parse_arxiv_xml(raw: bytes) -> ET.Element:
    lowered = raw.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise ValueError("arXiv XML DTD/entity declarations are not allowed")
    return ET.fromstring(  # noqa: S314 - bounded input; DTD/entities rejected above
        raw
    )


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def title_similarity(a: str, b: str) -> float:
    """Dice overlap over normalized title tokens.

    Crossref title matching needs to ignore punctuation/hyphenation while not
    rewarding unrelated titles merely because their character sequences happen
    to align. Token overlap is deterministic and conservative for corroboration.
    """
    tokens = lambda value: set(re.findall(r"[a-z0-9]+", value.lower()))
    left, right = tokens(a), tokens(b)
    if not left or not right:
        return 0.0
    return (2.0 * len(left & right)) / (len(left) + len(right))


def score_paper(paper: Paper) -> int:
    haystack = f"{paper.title}\n{paper.summary}".lower()
    score = sum(weight for term, weight in PROJECT_TERMS.items() if term in haystack)
    score += min(4, sum(1 for category in paper.categories if category in RELEVANT_CATEGORIES))
    if any(term in paper.title.lower() for term in ("agent", "retrieval", "context", "repository", "token", "code")):
        score += 2
    return score


def _arxiv_query(days: int, max_results: int) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    start = now - dt.timedelta(days=max(1, days))
    start_s = start.strftime("%Y%m%d%H%M")
    end_s = now.strftime("%Y%m%d%H%M")
    category_query = " OR ".join(f"cat:{category}" for category in sorted(RELEVANT_CATEGORIES))
    search_query = f"({category_query}) AND submittedDate:[{start_s} TO {end_s}]"
    params = {
        "search_query": search_query,
        "start": "0",
        "max_results": str(max_results),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    return ARXIV_API + "?" + urllib.parse.urlencode(params)


def fetch_arxiv(days: int = 3, max_results: int = 80) -> list[Paper]:
    raw = _request(_arxiv_query(days, max_results))
    root = _parse_arxiv_xml(raw)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    papers: list[Paper] = []
    for entry in root.findall("atom:entry", ns):
        identifier = _clean(entry.findtext("atom:id", namespaces=ns)).rsplit("/", 1)[-1]
        identifier = identifier.split("v", 1)[0] if re.search(r"v\d+$", identifier) else identifier
        links = entry.findall("atom:link", ns)
        abstract_url = next((link.attrib.get("href", "") for link in links if link.attrib.get("rel") == "alternate"), f"https://arxiv.org/abs/{identifier}")
        doi = _clean(entry.findtext("arxiv:doi", namespaces=ns)) or None
        papers.append(Paper(
            arxiv_id=identifier,
            title=_clean(entry.findtext("atom:title", namespaces=ns)),
            summary=_clean(entry.findtext("atom:summary", namespaces=ns)),
            authors=tuple(_clean(node.findtext("atom:name", namespaces=ns)) for node in entry.findall("atom:author", ns)),
            categories=tuple(node.attrib.get("term", "") for node in entry.findall("atom:category", ns)),
            published=_clean(entry.findtext("atom:published", namespaces=ns)),
            updated=_clean(entry.findtext("atom:updated", namespaces=ns)),
            doi=doi,
            url=abstract_url,
        ))
    return papers


def corroborate_crossref(paper: Paper) -> Paper:
    params = urllib.parse.urlencode({"query.title": paper.title, "rows": "3", "select": "DOI,title,URL,published,author"})
    try:
        payload = json.loads(_request(CROSSREF_API + "?" + params).decode("utf-8"))
    except Exception:
        return paper
    for item in payload.get("message", {}).get("items", []):
        titles = item.get("title") or []
        if not titles:
            continue
        if title_similarity(paper.title, titles[0]) >= 0.90:
            return Paper(**{
                **asdict(paper),
                "verification": "arxiv+crossref",
                "crossref_url": item.get("URL"),
                "doi": paper.doi or item.get("DOI"),
            })
    return paper


def rank_papers(papers: Iterable[Paper], minimum_score: int = 5, limit: int = 12) -> list[Paper]:
    unique: dict[str, Paper] = {}
    for paper in papers:
        if paper.arxiv_id not in unique or paper.updated > unique[paper.arxiv_id].updated:
            unique[paper.arxiv_id] = paper
    ranked = sorted(unique.values(), key=lambda paper: (score_paper(paper), paper.published), reverse=True)
    return [paper for paper in ranked if score_paper(paper) >= minimum_score][:limit]


def render_markdown(papers: list[Paper], generated_at: str) -> str:
    lines = [
        "# Daily research scout",
        "",
        f"Generated: {generated_at}",
        "",
        "This report is evidence-first. arXiv metadata is treated as the primary scholarly record; Crossref corroboration is recorded when title matching is strong. A paper appearing here is an improvement candidate, not proof that its method should be merged.",
        "",
        "## Candidate papers",
        "",
    ]
    if not papers:
        lines += ["No new papers crossed the project-relevance threshold in this run.", ""]
    for paper in papers:
        authors = ", ".join(paper.authors[:6]) + (" et al." if len(paper.authors) > 6 else "")
        categories = ", ".join(paper.categories)
        lines += [
            f"### {paper.title}",
            "",
            f"- relevance score: {score_paper(paper)}",
            f"- verification: {paper.verification}",
            f"- arXiv: {paper.url}",
            f"- arXiv id: `{paper.arxiv_id}`",
            f"- published: {paper.published}",
            f"- authors: {authors}",
            f"- categories: {categories}",
        ]
        if paper.doi:
            lines.append(f"- DOI: https://doi.org/{paper.doi}")
        if paper.crossref_url:
            lines.append(f"- Crossref record: {paper.crossref_url}")
        lines += ["", f"**Abstract summary from source:** {paper.summary[:1200]}", ""]
    lines += [
        "## Promotion gate",
        "",
        "A candidate should influence project logic only when all of the following are true:",
        "",
        "1. the paper addresses an actual bottleneck measured in this repository;",
        "2. the proposed mechanism can be implemented behind a deterministic or optional boundary;",
        "3. a benchmark or regression test demonstrates improvement over the current baseline;",
        "4. token/context claims are measured rather than inferred from paper language;",
        "5. safety routing, provenance, and abstention behavior do not regress.",
        "",
    ]
    return "\n".join(lines)


def run(output: Path, archive_dir: Path | None = None, days: int = 3, max_results: int = 80, minimum_score: int = 5, limit: int = 12) -> dict:
    generated = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    papers = rank_papers(fetch_arxiv(days=days, max_results=max_results), minimum_score=minimum_score, limit=limit)
    verified = [corroborate_crossref(paper) for paper in papers]
    markdown = render_markdown(verified, generated)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown + "\n", encoding="utf-8")
    archive_path = None
    if archive_dir is not None:
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = archive_dir / f"{dt.date.today().isoformat()}.md"
        archive_path.write_text(markdown + "\n", encoding="utf-8")
    return {
        "generated_at": generated,
        "papers": len(verified),
        "output": str(output),
        "archive": str(archive_path) if archive_path else None,
        "arxiv_ids": [paper.arxiv_id for paper in verified],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-workflow-research", description="Fetch and rank recent research relevant to the control plane.")
    parser.add_argument("--output", default="docs/research/daily/latest.md")
    parser.add_argument("--archive-dir", default="docs/research/daily/archive")
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--max-results", type=int, default=80)
    parser.add_argument("--minimum-score", type=int, default=5)
    parser.add_argument("--limit", type=int, default=12)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = run(
        Path(args.output),
        Path(args.archive_dir) if args.archive_dir else None,
        days=args.days,
        max_results=args.max_results,
        minimum_score=args.minimum_score,
        limit=args.limit,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
