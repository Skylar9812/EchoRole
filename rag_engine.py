"""Embedding-based local RAG v2 for EchoRole AI Coach Chat.

This module loads markdown notes from ``rag_docs/books`` recursively and keeps a
lexical fallback in memory. Retrieval now prefers local embeddings stored in a
persistent Chroma index, while preserving the original public retrieval
function. If embedding retrieval fails for any reason, the module falls back to
the lexical scorer instead of interrupting AI Coach.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Dict, List, Optional

DEFAULT_EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

_RAG_CACHE: Dict[str, object] = {
    "root": None,
    "docs": None,
    "embedding_model_name": None,
    "embedding_model": None,
    "chroma_path": None,
    "collection_name": None,
    "chroma_client": None,
    "collection": None,
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


def _resolve_chroma_root(chroma_dir=None):
    if chroma_dir:
        return Path(chroma_dir).resolve()
    return (Path(__file__).resolve().parent / "rag_index" / "chroma").resolve()


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
    path_parts = Path(relative_path).parts
    book = path_parts[0] if len(path_parts) > 1 else path.parent.name
    category = path.parent.name
    preview = " ".join(content.split())
    if len(preview) > 900:
        preview = preview[:897] + "..."

    token_source = " ".join([title, book, category, relative_path, content])
    tokens = _tokenize(token_source)
    doc_hash = hashlib.sha1(content.encode("utf-8", errors="ignore")).hexdigest()

    return {
        "doc_id": relative_path,
        "doc_hash": doc_hash,
        "path": str(path),
        "relative_path": relative_path,
        "book": book,
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


def _retrieve_relevant_notes_lexical(query_text, *, top_k=4, root_dir=None):
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
            "book": doc.get("book", ""),
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


def _get_embedding_model(model_name=DEFAULT_EMBEDDING_MODEL_NAME):
    cached_name = _RAG_CACHE.get("embedding_model_name")
    cached_model = _RAG_CACHE.get("embedding_model")
    if cached_model is not None and cached_name == model_name:
        return cached_model

    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)
    _RAG_CACHE["embedding_model_name"] = model_name
    _RAG_CACHE["embedding_model"] = model
    _log_rag_event(
        "rag_embedding_model_loaded",
        model_name=model_name
    )
    return model


def _collection_name_for_root(root: Path):
    root_hash = hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:10]
    return f"echorole_rag_docs_v2_{root_hash}"


def _get_chroma_collection(root: Path, *, chroma_dir=None, rebuild=False):
    persist_root = _resolve_chroma_root(chroma_dir)
    persist_root.mkdir(parents=True, exist_ok=True)
    collection_name = _collection_name_for_root(root)

    cached_path = _RAG_CACHE.get("chroma_path")
    cached_collection_name = _RAG_CACHE.get("collection_name")
    cached_collection = _RAG_CACHE.get("collection")
    if (
        not rebuild
        and cached_collection is not None
        and cached_path == str(persist_root)
        and cached_collection_name == collection_name
    ):
        return cached_collection

    import chromadb

    client = chromadb.PersistentClient(path=str(persist_root))
    if rebuild:
        try:
            client.delete_collection(collection_name)
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"}
    )

    _RAG_CACHE["chroma_path"] = str(persist_root)
    _RAG_CACHE["collection_name"] = collection_name
    _RAG_CACHE["chroma_client"] = client
    _RAG_CACHE["collection"] = collection
    return collection


def _embedding_rows_for_docs(docs):
    documents = [str(doc.get("content") or "") for doc in docs]
    metadatas = []
    for doc in docs:
        metadatas.append({
            "title": str(doc.get("title") or ""),
            "relative_path": str(doc.get("relative_path") or ""),
            "category": str(doc.get("category") or ""),
            "book": str(doc.get("book") or ""),
            "preview": str(doc.get("preview") or ""),
            "path": str(doc.get("path") or ""),
            "doc_hash": str(doc.get("doc_hash") or ""),
        })
    ids = [str(doc.get("doc_id") or doc.get("relative_path") or "") for doc in docs]
    return ids, documents, metadatas


def _ensure_chroma_index(*, root_dir=None, chroma_dir=None, rebuild=False):
    root = _resolve_rag_root(root_dir)
    docs = load_rag_docs(root_dir=root_dir)
    if not docs:
        _log_rag_event(
            "rag_chroma_index_ready",
            collection_count=0,
            root=str(root),
            no_docs=True
        )
        return None

    model = _get_embedding_model()
    expected_ids, documents, metadatas = _embedding_rows_for_docs(docs)
    collection = _get_chroma_collection(root, chroma_dir=chroma_dir, rebuild=rebuild)

    collection_count = int(collection.count())
    should_rebuild = rebuild or collection_count == 0
    if not should_rebuild and collection_count != len(expected_ids):
        should_rebuild = True

    if should_rebuild:
        if not rebuild:
            collection = _get_chroma_collection(root, chroma_dir=chroma_dir, rebuild=True)

        embeddings = model.encode(documents, show_progress_bar=False)
        if hasattr(embeddings, "tolist"):
            embeddings = embeddings.tolist()

        collection.add(
            ids=expected_ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )
        collection_count = int(collection.count())

    _log_rag_event(
        "rag_chroma_index_ready",
        collection_count=collection_count,
        root=str(root),
        rebuilt=should_rebuild,
        chroma_path=str(_resolve_chroma_root(chroma_dir))
    )
    return collection


def rebuild_rag_index(*, root_dir=None, chroma_dir=None):
    collection = _ensure_chroma_index(
        root_dir=root_dir,
        chroma_dir=chroma_dir,
        rebuild=True
    )
    if collection is None:
        return 0
    return int(collection.count())


def retrieve_relevant_notes(query_text, *, top_k=4, root_dir=None):
    try:
        docs = load_rag_docs(root_dir=root_dir)
        _log_rag_event(
            "rag_embedding_retrieval_started",
            query_preview=(query_text or "")[:180],
            doc_count=len(docs),
            top_k=top_k
        )

        if not docs:
            _log_rag_event(
                "rag_retrieval_failed_using_empty_context",
                reason="no_docs_available"
            )
            return []

        if not str(query_text or "").strip():
            _log_rag_event(
                "rag_embedding_retrieval_completed",
                result_count=0,
                top_titles=[],
                top_sources=[]
            )
            return []

        docs_by_id = {
            str(doc.get("doc_id") or doc.get("relative_path") or ""): doc
            for doc in docs
        }
        collection = _ensure_chroma_index(root_dir=root_dir)
        if collection is None:
            return []

        model = _get_embedding_model()
        query_embedding = model.encode([str(query_text)], show_progress_bar=False)
        if hasattr(query_embedding, "tolist"):
            query_embedding = query_embedding.tolist()

        query_result = collection.query(
            query_embeddings=query_embedding,
            n_results=max(1, int(top_k)),
            include=["documents", "metadatas", "distances"]
        )

        ids = (query_result.get("ids") or [[]])[0]
        metadatas = (query_result.get("metadatas") or [[]])[0]
        documents = (query_result.get("documents") or [[]])[0]
        distances = (query_result.get("distances") or [[]])[0]

        results = []
        for index, doc_id in enumerate(ids):
            metadata = metadatas[index] if index < len(metadatas) else {}
            document = documents[index] if index < len(documents) else ""
            distance = distances[index] if index < len(distances) else None
            cached_doc = docs_by_id.get(str(doc_id), {})

            preview = str(metadata.get("preview") or cached_doc.get("preview") or "").strip()
            if preview == "":
                preview = " ".join(str(document or "").split())
                if len(preview) > 900:
                    preview = preview[:897] + "..."

            results.append({
                "path": str(metadata.get("path") or cached_doc.get("path") or ""),
                "relative_path": str(metadata.get("relative_path") or cached_doc.get("relative_path") or ""),
                "book": str(metadata.get("book") or cached_doc.get("book") or ""),
                "category": str(metadata.get("category") or cached_doc.get("category") or ""),
                "title": str(metadata.get("title") or cached_doc.get("title") or f"Note {index + 1}"),
                "content": str(document or cached_doc.get("content") or ""),
                "preview": preview,
                "score": (1.0 - float(distance)) if distance is not None else 0.0,
            })

        _log_rag_event(
            "rag_embedding_retrieval_completed",
            result_count=len(results),
            top_titles=[note["title"] for note in results],
            top_sources=[note["relative_path"] for note in results]
        )
        return results
    except Exception as exc:
        _log_rag_event(
            "rag_embedding_retrieval_failed_using_lexical_fallback",
            exception_type=type(exc).__name__,
            exception_message=str(exc)
        )
        try:
            return _retrieve_relevant_notes_lexical(
                query_text,
                top_k=top_k,
                root_dir=root_dir
            )
        except Exception as fallback_exc:
            _log_rag_event(
                "rag_retrieval_failed_using_empty_context",
                exception_type=type(fallback_exc).__name__,
                exception_message=str(fallback_exc)
            )
            return []
