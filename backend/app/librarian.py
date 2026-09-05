from __future__ import annotations

import concurrent.futures
import ipaddress
import json
import re
import socket
import sqlite3
import tempfile
import time
import unicodedata
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import feedparser
from pypdf import PdfReader

from .kb import create_job, fail_job, load_job, load_paper, list_papers, now_iso, save_job, save_paper, slugify, unique_path, update_job

INDEX_VERSION = 1
MAX_PDF_BYTES = 100 * 1024 * 1024
ACTION_TTL_HOURS = 24

SUPPORTED_VENUES = {
    "cvpr", "iccv", "eccv", "aaai", "ijcai", "nips", "iclr", "icml",
    "mm", "kdd", "www", "acl", "emnlp", "naacl", "tpami", "nmi",
    "pnas", "ijcv", "if", "tip", "taffc", "interspeech", "icassp", "tsp",
    "pieee", "tnnls", "iotj", "tcom", "cacm", "csur", "jacm", "nature", "tog",
}

VENUE_ALIASES = {
    "neurips": "nips", "neuripsconference": "nips", "nips": "nips",
    "acmmm": "mm", "acmmultimedia": "mm", "multimedia": "mm",
    "thewebconference": "www", "webconference": "www",
    "ieeetpami": "tpami", "pami": "tpami",
    "naturemachineintelligence": "nmi",
}


def normalize_venues(values: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    unsupported: list[str] = []
    for value in values:
        key = re.sub(r"[^a-z0-9]", "", str(value).casefold())
        key = re.sub(r"(?:19|20)\d{2}$", "", key)
        venue = VENUE_ALIASES.get(key, key)
        if venue not in SUPPORTED_VENUES:
            unsupported.append(str(value))
        elif venue not in normalized:
            normalized.append(venue)
    if unsupported:
        raise ValueError(
            "The venue catalogue does not support venue(s): " + ", ".join(unsupported)
            + ". Supported examples include NeurIPS/NIPS, ICLR, ICML, CVPR, ACL, and EMNLP."
        )
    if not normalized:
        raise ValueError("At least one supported venue is required.")
    return normalized




def normalize_doi(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text)
    return re.sub(r"^doi:\s*", "", text).strip().rstrip(".")


def normalize_arxiv_id(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"^https?://arxiv\.org/(?:abs|pdf)/", "", text)
    return re.sub(r"v\d+$", "", text.removesuffix(".pdf")).strip()


def normalize_title(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.findall(r"[\w]+", text, flags=re.UNICODE))


def _nonempty(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def find_import_match(root: Path, candidate: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    doi = normalize_doi(candidate.get("doi"))
    arxiv_id = normalize_arxiv_id(candidate.get("arxiv_id"))
    title = normalize_title(candidate.get("title"))
    papers = list_papers(root)
    if doi:
        for paper in papers:
            if normalize_doi(paper.get("doi")) == doi:
                return paper, "doi"
    if arxiv_id:
        for paper in papers:
            if normalize_arxiv_id(paper.get("arxiv_id")) == arxiv_id:
                return paper, "arxiv_id"
    if title:
        for paper in papers:
            if normalize_title(paper.get("title")) != title:
                continue
            existing_doi = normalize_doi(paper.get("doi"))
            existing_arxiv = normalize_arxiv_id(paper.get("arxiv_id"))
            if (doi and existing_doi and doi != existing_doi) or (arxiv_id and existing_arxiv and arxiv_id != existing_arxiv):
                return None, "identifier_conflict"
            return paper, "title"
    return None, None


IMPORT_FIELDS = (
    "title", "authors", "year", "venue", "abstract", "doi", "arxiv_id",
    "paper_url", "pdf_url", "pages",
)


def merge_metadata(root: Path, candidate: dict[str, Any]) -> dict[str, Any]:
    title = str(candidate.get("title") or "").strip()
    if not title:
        raise ValueError("Paper metadata requires a title.")
    existing, matched_by = find_import_match(root, candidate)
    if matched_by == "identifier_conflict":
        return {"status": "conflict", "reason": matched_by, "candidate": candidate}
    created = existing is None
    if existing is None:
        used = {str(p.get("id")) for p in list_papers(root)}
        base = slugify(title)[:80].strip("_") or "paper"
        paper_id = base
        suffix = 2
        while paper_id in used:
            paper_id = f"{base}_{suffix}"
            suffix += 1
        paper = {
            "id": paper_id, "title": title, "created_at": now_iso(),
            "tags": [], "reading_status": "unread", "priority": "normal",
            "needs_review": True, "review_notes": [], "agent_reviews": [],
        }
    else:
        paper = dict(existing)
    for field in IMPORT_FIELDS:
        incoming = candidate.get(field)
        if _nonempty(incoming) and not _nonempty(paper.get(field)):
            paper[field] = incoming
    source = candidate.get("metadata_source") or candidate.get("source")
    source_url = candidate.get("source_url") or candidate.get("paper_url")
    if source:
        provenance = {"provider": str(source), "url": str(source_url or ""), "retrieved_at": now_iso()}
        sources = list(paper.get("metadata_sources") or [])
        if not any(item.get("provider") == provenance["provider"] and item.get("url") == provenance["url"] for item in sources if isinstance(item, dict)):
            sources.append(provenance)
        paper["metadata_sources"] = sources
    save_paper(root, paper)
    return {"status": "created" if created else "merged", "matched_by": matched_by, "paper": paper}


def actions_dir(root: Path) -> Path:
    path = root / "logs/librarian_actions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_action(root: Path, kind: str, items: list[dict[str, Any]], *, session_id: str | None = None) -> dict[str, Any]:
    created = datetime.now(timezone.utc)
    action = {
        "id": uuid.uuid4().hex, "kind": kind, "status": "pending",
        "items": items, "session_id": session_id, "created_at": created.isoformat(),
        "expires_at": (created + timedelta(hours=ACTION_TTL_HOURS)).isoformat(),
    }
    (actions_dir(root) / f"{action['id']}.json").write_text(json.dumps(action, ensure_ascii=False, indent=2), encoding="utf-8")
    return action


def load_action(root: Path, action_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"[a-f0-9]{32}", action_id):
        raise FileNotFoundError("Action not found.")
    path = actions_dir(root) / f"{action_id}.json"
    if not path.exists():
        raise FileNotFoundError("Action not found.")
    action = json.loads(path.read_text(encoding="utf-8"))
    if datetime.fromisoformat(action["expires_at"]) < datetime.now(timezone.utc):
        action["status"] = "expired"
    return action


def save_action(root: Path, action: dict[str, Any]) -> None:
    (actions_dir(root) / f"{action['id']}.json").write_text(json.dumps(action, ensure_ascii=False, indent=2), encoding="utf-8")


def import_action(root: Path, action_id: str, selected: list[int] | None = None) -> dict[str, Any]:
    action = load_action(root, action_id)
    if action.get("kind") != "metadata_import":
        raise ValueError("Action is not a metadata import.")
    if action.get("status") == "completed":
        return action
    if action.get("status") != "pending":
        raise ValueError(f"Action is {action.get('status')}.")
    indexes = selected if selected is not None else list(range(len(action["items"])))
    action["results"] = [merge_metadata(root, action["items"][index]) for index in indexes if 0 <= index < len(action["items"])]
    action["status"] = "completed"
    action["completed_at"] = now_iso()
    save_action(root, action)
    return action


def index_path(root: Path) -> Path:
    return root / "metadata/fulltext.sqlite3"


def _index_connection(root: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(index_path(root))
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS paper_chunks USING fts5(paper_id UNINDEXED, page UNINDEXED, chunk_index UNINDEXED, content)")
    conn.execute("CREATE TABLE IF NOT EXISTS index_meta (paper_id TEXT PRIMARY KEY, version INTEGER NOT NULL, indexed_at TEXT NOT NULL)")
    return conn


def _chunks(text: str, size: int = 1800, overlap: int = 200) -> Iterable[str]:
    normalized = " ".join(text.split())
    start = 0
    while start < len(normalized):
        yield normalized[start:start + size]
        start += max(1, size - overlap)


def build_fulltext_index(root: Path, paper_id: str) -> dict[str, Any]:
    paper = load_paper(root, paper_id)
    source = paper.get("source_pdf")
    if not source:
        raise ValueError("Paper has no local PDF.")
    pdf = (root / str(source)).resolve()
    pdf.relative_to(root.resolve())
    if not pdf.exists():
        raise ValueError("Local PDF is unavailable.")
    paper["index_status"] = "indexing"
    paper["index_error"] = ""
    save_paper(root, paper)
    try:
        rows: list[tuple[str, int, int, str]] = []
        reader = PdfReader(str(pdf))
        for page_number, page in enumerate(reader.pages, 1):
            for chunk_index, content in enumerate(_chunks(page.extract_text() or "")):
                if content:
                    rows.append((paper_id, page_number, chunk_index, content))
        with _index_connection(root) as conn:
            conn.execute("DELETE FROM paper_chunks WHERE paper_id = ?", (paper_id,))
            conn.executemany("INSERT INTO paper_chunks(paper_id,page,chunk_index,content) VALUES (?,?,?,?)", rows)
            conn.execute("INSERT OR REPLACE INTO index_meta(paper_id,version,indexed_at) VALUES (?,?,?)", (paper_id, INDEX_VERSION, now_iso()))
        paper = load_paper(root, paper_id)
        paper.update({"index_status": "indexed", "indexed_at": now_iso(), "index_version": INDEX_VERSION, "index_error": ""})
        save_paper(root, paper)
        return {"paper_id": paper_id, "chunks": len(rows), "pages": len(reader.pages)}
    except Exception as exc:
        paper = load_paper(root, paper_id)
        paper.update({"index_status": "failed", "index_error": str(exc)})
        save_paper(root, paper)
        raise


def search_fulltext(root: Path, query: str, paper_ids: list[str] | None = None, limit: int = 12) -> list[dict[str, Any]]:
    allowed = {p["id"] for p in list_papers(root) if p.get("index_status") == "indexed"}
    if paper_ids:
        allowed &= set(paper_ids)
    if not allowed or not index_path(root).exists():
        return []
    terms = re.findall(r"[\w]+", query, flags=re.UNICODE)
    if not terms:
        return []
    fts_query = " AND ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms[:20])
    with _index_connection(root) as conn:
        rows = conn.execute(
            "SELECT paper_id,page,chunk_index,snippet(paper_chunks,3,'<mark>','</mark>',' … ',24),bm25(paper_chunks) FROM paper_chunks WHERE paper_chunks MATCH ? ORDER BY bm25(paper_chunks) LIMIT ?",
            (fts_query, max(limit * 4, limit)),
        ).fetchall()
    return [{"paper_id": row[0], "page": row[1], "chunk_index": row[2], "snippet": row[3], "score": row[4]} for row in rows if row[0] in allowed][:limit]


def _assert_public_http_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only public HTTP(S) URLs are allowed.")
    for info in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)):
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise ValueError("Private, local, and reserved network targets are forbidden.")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        _assert_public_http_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_pdf(root: Path, paper_id: str, url: str) -> dict[str, Any]:
    _assert_public_http_url(url)
    paper = load_paper(root, paper_id)
    paper.update({"pdf_url": url, "download_status": "downloading", "download_error": ""})
    save_paper(root, paper)
    temp_path: Path | None = None
    try:
        opener = urllib.request.build_opener(_SafeRedirect())
        request = urllib.request.Request(url, headers={"User-Agent": "NeuNote/1.2 paper librarian"})
        with opener.open(request, timeout=30) as response, tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as handle:
            temp_path = Path(handle.name)
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_PDF_BYTES:
                    raise ValueError("PDF exceeds the 100 MiB limit.")
                handle.write(chunk)
        if temp_path.read_bytes()[:5] != b"%PDF-":
            raise ValueError("URL did not return a PDF file.")
        reader = PdfReader(str(temp_path))
        page_count = len(reader.pages)
        if not page_count:
            raise ValueError("Downloaded PDF has no readable pages.")
        destination = unique_path(root / "originals/papers" / f"{slugify(paper_id)}.pdf")
        temp_path.replace(destination)
        temp_path = None
        paper = load_paper(root, paper_id)
        paper.update({"source_pdf": str(destination.relative_to(root)), "pages": page_count, "download_status": "downloaded", "downloaded_at": now_iso(), "download_error": "", "index_status": "not_indexed"})
        save_paper(root, paper)
        return paper
    except Exception as exc:
        paper = load_paper(root, paper_id)
        paper.update({"download_status": "failed", "download_error": str(exc)})
        save_paper(root, paper)
        raise
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


DBLP_STREAMS = {
    "nips": "nips", "iclr": "iclr", "icml": "icml", "cvpr": "cvpr",
    "iccv": "iccv", "eccv": "eccv", "aaai": "aaai", "ijcai": "ijcai",
    "acl": "acl", "emnlp": "emnlp", "naacl": "naacl", "kdd": "kdd",
    "www": "www", "mm": "mm", "interspeech": "interspeech", "icassp": "icassp",
}


def _http_json(url: str, params: dict[str, Any], attempts: int = 3) -> dict[str, Any]:
    query = urllib.parse.urlencode(params, doseq=True)
    request = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": "NeuNote/1.2 (paper metadata aggregator)"})
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504} or attempt + 1 >= attempts:
                raise
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            time.sleep(min(float(retry_after or (attempt + 1)), 5.0))
        except (TimeoutError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt + 1 >= attempts:
                raise
            time.sleep(attempt + 1)
    raise RuntimeError(str(last_error or "Metadata provider failed."))


def _authors_from_dblp(value: Any) -> list[str]:
    if isinstance(value, dict) and "author" in value:
        value = value["author"]
    if not isinstance(value, list):
        value = [value] if value else []
    return [str(item.get("text") if isinstance(item, dict) else item).strip() for item in value if item]


def _query_matches_title(title: str, query: str) -> bool:
    if not query.strip() or query.strip() == "*":
        return True
    normalized = normalize_title(title)
    parts = [normalize_title(part) for part in re.split(r"\s+or\s+", query, flags=re.I)]
    if len(parts) > 1:
        return any(part and part in normalized for part in parts)
    terms = [term for term in re.findall(r"[\w]+", normalize_title(query)) if term not in {"and", "or", "not"}]
    return all(term in normalized for term in terms)


def search_dblp_venues(conferences: list[str], years: list[int], query: str = "*", limit: int = 5000) -> list[dict[str, Any]]:
    venues = normalize_venues(conferences)
    results: list[dict[str, Any]] = []
    for venue in venues:
        stream = DBLP_STREAMS.get(venue)
        if not stream:
            raise ValueError(f"DBLP venue-list provider is not configured for {venue}.")
        for year in years:
            offset = 0
            while len(results) < limit:
                data = _http_json("https://dblp.org/search/publ/api", {
                    "q": f"stream:streams/conf/{stream}: year:{int(year)}", "format": "json", "h": 1000, "f": offset,
                })
                hits_node = data.get("result", {}).get("hits", {})
                hits = hits_node.get("hit") or []
                if isinstance(hits, dict):
                    hits = [hits]
                for hit in hits:
                    info = hit.get("info") or {}
                    title = re.sub(r"<[^>]+>", "", str(info.get("title") or "")).rstrip(".").strip()
                    if not title or not _query_matches_title(title, query):
                        continue
                    ee = info.get("ee") or ""
                    if isinstance(ee, list):
                        ee = next((str(item) for item in ee if item), "")
                    paper_url = str(ee or info.get("url") or "")
                    pdf_url = ""
                    if "papers.nips.cc" in paper_url and "-Abstract-Conference.html" in paper_url:
                        pdf_url = paper_url.replace("-Abstract-Conference.html", "-Paper-Conference.pdf")
                    results.append({
                        "title": title, "authors": _authors_from_dblp(info.get("authors")),
                        "year": int(info.get("year") or year), "venue": str(info.get("venue") or venue.upper()),
                        "abstract": "", "doi": normalize_doi(info.get("doi")), "arxiv_id": "",
                        "paper_url": paper_url, "pdf_url": pdf_url,
                        "metadata_source": "DBLP", "source_url": paper_url,
                    })
                    if len(results) >= limit:
                        break
                total = int(hits_node.get("@total") or 0)
                offset += len(hits)
                if not hits or offset >= total or len(results) >= limit:
                    break
    return results


def _openalex_abstract(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    positions: list[tuple[int, str]] = []
    for word, indexes in value.items():
        positions.extend((int(index), str(word)) for index in indexes)
    return " ".join(word for _, word in sorted(positions))


def search_openalex(query: str, years: list[int], limit: int = 50) -> list[dict[str, Any]]:
    filters = []
    if years:
        filters.extend([f"from_publication_date:{min(years)}-01-01", f"to_publication_date:{max(years)}-12-31"])
    params: dict[str, Any] = {"search": query, "per-page": min(limit, 100)}
    if filters:
        params["filter"] = ",".join(filters)
    data = _http_json("https://api.openalex.org/works", params)
    results = []
    for work in data.get("results") or []:
        primary = work.get("primary_location") or {}
        best = work.get("best_oa_location") or {}
        ids = work.get("ids") or {}
        results.append({
            "title": re.sub(r"<[^>]+>", "", work.get("title") or ""),
            "authors": [item.get("author", {}).get("display_name") for item in work.get("authorships") or [] if item.get("author", {}).get("display_name")],
            "year": work.get("publication_year"),
            "venue": (primary.get("source") or {}).get("display_name") or "",
            "abstract": _openalex_abstract(work.get("abstract_inverted_index")),
            "doi": normalize_doi(work.get("doi")), "arxiv_id": normalize_arxiv_id(ids.get("arxiv")),
            "paper_url": primary.get("landing_page_url") or work.get("id") or "",
            "pdf_url": best.get("pdf_url") or primary.get("pdf_url") or "",
            "metadata_source": "OpenAlex", "source_url": work.get("id") or "",
        })
    return [item for item in results if item["title"]]


def search_crossref(query: str, years: list[int], limit: int = 50) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"query.bibliographic": query, "rows": min(limit, 100), "select": "DOI,title,author,published,container-title,abstract,URL,link"}
    if years:
        params["filter"] = f"from-pub-date:{min(years)}-01-01,until-pub-date:{max(years)}-12-31"
    data = _http_json("https://api.crossref.org/works", params)
    results = []
    for item in data.get("message", {}).get("items") or []:
        date_parts = ((item.get("published") or {}).get("date-parts") or [[]])[0]
        links = item.get("link") or []
        pdf_url = next((link.get("URL") for link in links if "pdf" in str(link.get("content-type") or "").lower()), "")
        results.append({
            "title": re.sub(r"<[^>]+>", "", " ".join(item.get("title") or [])).strip(),
            "authors": [" ".join(filter(None, [author.get("given"), author.get("family")])) for author in item.get("author") or []],
            "year": date_parts[0] if date_parts else None,
            "venue": " ".join(item.get("container-title") or []),
            "abstract": re.sub(r"<[^>]+>", " ", item.get("abstract") or "").strip(),
            "doi": normalize_doi(item.get("DOI")), "arxiv_id": "",
            "paper_url": item.get("URL") or "", "pdf_url": pdf_url or "",
            "metadata_source": "Crossref", "source_url": item.get("URL") or "",
        })
    return [item for item in results if item["title"]]


def search_arxiv(query: str, years: list[int], limit: int = 50) -> list[dict[str, Any]]:
    phrase = query.replace('"', " ").strip()
    search_query = f'all:"{phrase}"'
    if years:
        search_query += f" AND submittedDate:[{min(years)}01010000 TO {max(years)}12312359]"
    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode({"search_query": search_query, "start": 0, "max_results": min(limit, 100), "sortBy": "relevance"})
    request = urllib.request.Request(url, headers={"User-Agent": "NeuNote/1.2 (paper metadata aggregator)"})
    with urllib.request.urlopen(request, timeout=30) as response:
        feed = feedparser.parse(response.read())
    results = []
    for entry in feed.entries:
        published = str(entry.get("published") or "")
        year = int(published[:4]) if published[:4].isdigit() else None
        if years and year not in years:
            continue
        arxiv_id = normalize_arxiv_id(entry.get("id"))
        results.append({
            "title": re.sub(r"<[^>]+>", "", " ".join(str(entry.get("title") or "").split())),
            "authors": [author.get("name") for author in entry.get("authors") or [] if author.get("name")],
            "year": year, "venue": "arXiv", "abstract": " ".join(str(entry.get("summary") or "").split()),
            "doi": normalize_doi(entry.get("arxiv_doi")), "arxiv_id": arxiv_id,
            "paper_url": f"https://arxiv.org/abs/{arxiv_id}", "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
            "metadata_source": "arXiv", "source_url": entry.get("id") or "",
        })
    return [item for item in results if item["title"]]


def _merge_discovery_candidates(items: Iterable[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in items:
        key = normalize_doi(item.get("doi")) or normalize_arxiv_id(item.get("arxiv_id")) or normalize_title(item.get("title"))
        if not key:
            continue
        if key not in merged:
            merged[key] = dict(item)
            merged[key]["metadata_sources"] = [item.get("metadata_source")]
            continue
        current = merged[key]
        for field in IMPORT_FIELDS:
            if not _nonempty(current.get(field)) and _nonempty(item.get(field)):
                current[field] = item[field]
        source = item.get("metadata_source")
        if source and source not in current["metadata_sources"]:
            current["metadata_sources"].append(source)
    return list(merged.values())[:limit]


def search_papers_aggregated(conferences: list[str], years: list[int], query: str = "*", limit: int = 5000) -> tuple[list[dict[str, Any]], list[str]]:
    if conferences:
        years = years or [datetime.now(timezone.utc).year]
        try:
            return search_dblp_venues(conferences, years, query, limit), []
        except Exception as exc:
            return [], [f"DBLP: {type(exc).__name__}: {exc}"]
    effective_query = query.strip() if query.strip() and query.strip() != "*" else "computer science"
    providers = {"OpenAlex": search_openalex, "Crossref": search_crossref, "arXiv": search_arxiv}
    batches: dict[str, list[dict[str, Any]]] = {}
    warnings: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(fn, effective_query, years, min(limit, 50)): name for name, fn in providers.items()}
        for future, name in [(future, futures[future]) for future in futures]:
            try:
                batches[name] = future.result()
            except Exception as exc:
                warnings.append(f"{name}: {type(exc).__name__}: {exc}")
    gathered: list[dict[str, Any]] = []
    max_batch = max((len(batch) for batch in batches.values()), default=0)
    for index in range(max_batch):
        for name in providers:
            batch = batches.get(name) or []
            if index < len(batch):
                gathered.append(batch[index])
    return _merge_discovery_candidates(gathered, limit), warnings


def run_librarian_job(root: Path, job_id: str, project_root: Path) -> None:
    job = load_job(root, job_id)
    kind = job.get("kind")
    payload = job.get("payload") or {}
    try:
        if kind == "metadata_search":
            update_job(root, job_id, status="running", stage="crawling", progress=10, message="Fetching paper metadata.")
            candidates, warnings = search_papers_aggregated(payload.get("conferences") or [], payload.get("years") or [], payload.get("query") or "*")
            action = create_action(root, "metadata_import", candidates, session_id=payload.get("session_id"))
            job = load_job(root, job_id)
            job["result"] = {"action_id": action["id"], "candidate_count": len(candidates), "candidates": candidates[:200], "warnings": warnings}
            save_job(root, job)
            message = f"Found {len(candidates)} papers; confirmation required."
            if warnings:
                message += f" {len(warnings)} provider(s) failed."
            update_job(root, job_id, status="completed", stage="awaiting_confirmation", progress=100, message=message)
        elif kind == "pdf_download":
            paper_id = str(job.get("paper_id") or payload.get("paper_id") or "")
            update_job(root, job_id, status="running", stage="downloading", progress=10, message="Downloading PDF.")
            paper = download_pdf(root, paper_id, str(payload["url"]))
            update_job(root, job_id, stage="indexing", progress=60, message="Building full-text index.")
            result = build_fulltext_index(root, paper_id)
            follow_up = create_job(root, paper_id, paper.get("title") or paper_id, kind="enrichment")
            result["enrichment_job_id"] = follow_up["id"]
            job = load_job(root, job_id)
            job["result"] = result
            save_job(root, job)
            update_job(root, job_id, status="completed", stage="completed", progress=100, message="PDF downloaded and indexed.")
        elif kind == "fulltext_index":
            paper_id = str(job.get("paper_id") or "")
            update_job(root, job_id, status="running", stage="indexing", progress=20, message="Building full-text index.")
            result = build_fulltext_index(root, paper_id)
            job = load_job(root, job_id)
            job["result"] = result
            save_job(root, job)
            update_job(root, job_id, status="completed", stage="completed", progress=100, message="Full-text index completed.")
        else:
            raise ValueError(f"Unsupported librarian job kind: {kind}")
    except Exception as exc:
        fail_job(root, job_id, str(exc))
