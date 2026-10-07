"""Text → retrievable chunks.

Chunking is metadata-aware: a chunk remembers its source, lesson, page and
position so an answer can always be cited back to *book → chapter → page*.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

WHITESPACE = re.compile(r"[ \t]+")
SENTENCE = re.compile(r"(?<=[.!؟?؛\n])\s+")


@dataclass(slots=True)
class Chunk:
    seq: int
    text: str
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def title(self) -> str:
        return str(self.meta.get("title", ""))

    @property
    def citation(self) -> str:
        return str(self.meta.get("citation", ""))


def clean_text(text: str) -> str:
    """Normalise without destroying Arabic shaping."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    text = re.sub(r"[ \t\u200f\u200e]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_sentences(text: str) -> list[str]:
    parts = SENTENCE.split(text)
    return [p.strip() for p in parts if p and p.strip()]


def chunk_text(
    text: str,
    *,
    chunk_size: int = 900,
    overlap: int = 150,
    meta: dict[str, Any] | None = None,
) -> list[Chunk]:
    """Pack sentences into overlapping windows, never splitting mid-word."""
    text = clean_text(text)
    if not text:
        return []

    sentences = _split_sentences(text) or [text]
    base = dict(meta or {})
    chunks: list[Chunk] = []
    current: list[str] = []
    size = 0

    def flush() -> None:
        nonlocal current, size
        if not current:
            return
        body = " ".join(current).strip()
        if body:
            chunks.append(Chunk(seq=len(chunks), text=body, meta=dict(base)))
        current = []
        size = 0

    for sentence in sentences:
        if len(sentence) > chunk_size:
            flush()
            for start in range(0, len(sentence), chunk_size - overlap):
                piece = sentence[start : start + chunk_size].strip()
                if piece:
                    chunks.append(Chunk(seq=len(chunks), text=piece, meta=dict(base)))
            continue
        if size + len(sentence) + 1 > chunk_size and current:
            flush()
            # carry an overlapping tail forward
            tail = current_tail(chunks, overlap)
            if tail:
                current = [tail]
                size = len(tail)
        current.append(sentence)
        size += len(sentence) + 1
    flush()
    return chunks


def current_tail(chunks: list[Chunk], overlap: int) -> str:
    if not chunks:
        return ""
    last = chunks[-1].text
    if len(last) <= overlap:
        return ""
    cut = last.rfind(" ", len(last) - overlap)
    return last[cut + 1 :] if cut != -1 else last[-overlap:]


def chunk_pages(
    pages: list[tuple[int, str]],
    *,
    chunk_size: int = 900,
    overlap: int = 150,
    meta: dict[str, Any] | None = None,
) -> list[Chunk]:
    """Chunk page by page so page numbers survive into the citation."""
    out: list[Chunk] = []
    base = dict(meta or {})
    for page_number, text in pages:
        page_meta = dict(base)
        page_meta["page"] = page_number
        for chunk in chunk_text(text, chunk_size=chunk_size, overlap=overlap, meta=page_meta):
            chunk.seq = len(out)
            out.append(chunk)
    return out


__all__ = ["Chunk", "clean_text", "chunk_text", "chunk_pages"]
