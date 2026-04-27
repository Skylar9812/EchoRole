"""Minimal local RAG v1 for EchoRole AI Coach Chat.

This module loads markdown notes from rag_docs/books recursively, keeps them in
memory, and returns the most relevant notes with a lightweight lexical score.
It is intentionally simple and fully local-first.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

_RAG_CACHE: Dict[str, object] = {
    "root": None,
    "docs": None,
}

_STOPWORDS = {
    "about", "after", "again", "also", "because", "before", "being", "between",
    "could", "does", "doing", "from", "have", "into", "just", "more", "most",
    "other", "over", "really", "some", "such", "than", "that", "their", "them",
    "then", "there", "these", "they", "this", "those", "through", "very", "what",
    "when", "where", "which", "while", "will", "with", "would", "your", "yours",
}


def _log_rag_event(event, **fields):
    field_parts = []
    for key, value in fields.items():
        if value is None:
            continue
        field_parts.append(f"{key}={value!r}")

    suffix = ""
    if field_parts:
        suffix = " " + " ".join(field_parts)

    print(f"[EchoRole][RAG] event={event}{suffix}", flush=True)


def _resolve_rag_root(root_dir=None):
    if root_dir:
        return Path(root_dir).resolve()
    return (Path(__file__).resolve().parent / "rag_docs" / "books").resolve()


def _strip_frontmatter(text):
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return text

    lines = stripped.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        return text

    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[index + 1:]).strip()

    return text


def _extract_title(path, text):
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return path.stem.replace("_", " ").strip()


def _tokenize(text):
    tokens = []
    for token in re.findall(r"[a-zA-Z']+", (text or "").lower()):
        if len(token) < 3 or token in _STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def _build_note_record(path: Path, root: Path):
    raw_text = path.read_text(encoding="utf-8", errors="replace")
    content = _strip_frontmatter(raw_text)
    title = _extract_title(path, content)
    relative_path = path.relative_to(root).as_posix()
    category = path.parent.name
    preview = " ".join(content.split())
    if len(preview) > 900:
        preview = preview[:897] + "..."

    token_source = " ".join([title, category, relative_path, content])
    tokens = _tokenize(token_source)

    return {
        "path": str(path),
        "relative_path": relative_path,
        "category": category,
        "title": title,
        "content": content,
        "preview": preview,
        "tokens": tokens,
    }


def load_rag_docs(root_dir=None):
    root = _resolve_rag_root(root_dir)

    cached_root = _RAG_CACHE.get("root")
    cached_docs = _RAG_CACHE.get("docs")
    if cached_root == str(root) and cached_docs is not None:
        return list(cached_docs)

    if not root.exists() or not root.is_dir():
        _RAG_CACHE["root"] = str(root)
        _RAG_CACHE["docs"] = []
        _log_rag_event("rag_docs_loaded", root=str(root), doc_count=0, missing=True)
        return []

    docs: List[Dict[str, object]] = []
    for path in sorted(root.rglob("*.md")):
        if not path.is_file():
            continue
        try:
            docs.append(_build_note_record(path, root))
        except OSError:
            continue

    _RAG_CACHE["root"] = str(root)
    _RAG_CACHE["docs"] = docs
    _log_rag_event("rag_docs_loaded", root=str(root), doc_count=len(docs), missing=False)
    return list(docs)


def retrieve_relevant_notes(query_text, *, top_k=4, root_dir=None):
    try:
        docs = load_rag_docs(root_dir=root_dir)
        _log_rag_event(
            "rag_retrieval_started",
            query_preview=(query_text or "")[:180],
            doc_count=len(docs)
        )

        if not docs:
            _log_rag_event(
                "rag_retrieval_failed_using_empty_context",
                reason="no_docs_available"
            )
            return []

        query_tokens = _tokenize(query_text)
        if not query_tokens:
            _log_rag_event(
                "rag_retrieval_completed",
                result_count=0,
                query_token_count=0
            )
            return []

        query_set = set(query_tokens)
        scored_docs = []
        for doc in docs:
            token_list = doc.get("tokens") or []
            token_set = set(token_list)
            overlap = query_set.intersection(token_set)
            if not overlap:
                continue

            title_tokens = set(_tokenize(str(doc.get("title") or "")))
            category_tokens = set(_tokenize(str(doc.get("category") or "")))
            score = len(overlap)
            score += len(query_set.intersection(title_tokens)) * 2
            score += len(query_set.intersection(category_tokens))

            preview = str(doc.get("preview") or "").lower()
            for token in query_set:
                if token in preview:
                    score += 0.2

            scored_docs.append((score, doc))

        scored_docs.sort(
            key=lambda item: (
                -item[0],
                str(item[1].get("category") or ""),
                str(item[1].get("title") or "")
            )
        )

        results = []
        for score, doc in scored_docs[:top_k]:
            results.append({
                "path": doc["path"],
                "relative_path": doc["relative_path"],
                "category": doc["category"],
                "title": doc["title"],
                "content": doc["content"],
                "preview": doc["preview"],
                "score": score,
            })

        _log_rag_event(
            "rag_retrieval_completed",
            result_count=len(results),
            query_token_count=len(query_set),
            top_titles=[note["title"] for note in results],
            top_sources=[note["relative_path"] for note in results]
        )
        return results
    except Exception as exc:
        _log_rag_event(
            "rag_retrieval_failed_using_empty_context",
            exception_type=type(exc).__name__,
            exception_message=str(exc)
        )
        return []
