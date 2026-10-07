"""Papers — the whiteboard of pages/blocks (notes, worksheets, posters).

Block content is deliberately schema-light (`type` + JSON `content`) so the
renderer can evolve without a migration; every type is validated on write so
the client can never store something unreadable.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..ai import AIRequest, ask, chunks_to_context, lesson_context, retrieve
from ..config import settings
from ..core.errors import NotFoundError, ValidationError
from ..db import Lesson, Paper, PaperBlock, PaperPage, PaperSource, Source, utcnow
from ..mors import EventType, bus

BLOCK_TYPES = {
    "text",
    "heading",
    "list",
    "formula",
    "image",
    "mcq",
    "divider",
    "table",
    "answer",
}

DEFAULT_LAYOUT = [
    {"type": "heading", "content": {"text": "العنوان"}},
    {"type": "text", "content": {"text": ""}},
]


# --------------------------------------------------------------------------- #
# papers
# --------------------------------------------------------------------------- #
def create_paper(
    db: Session,
    student_id: str,
    *,
    title: str,
    kind: str = "note",
    subject_id: str | None = None,
    lesson_id: str | None = None,
    emoji: str = "",
    color: str = "#2f8ff7",
    tags: list[str] | None = None,
) -> Paper:
    title = (title or "").strip()
    if not title:
        raise ValidationError("عنوان الورقة مطلوب.")
    paper = Paper(
        student_id=student_id,
        title=title[:220],
        kind=kind,
        subject_id=subject_id,
        lesson_id=lesson_id,
        emoji=emoji,
        color=color,
        tags=[str(t) for t in (tags or [])][:8],
        created_by_ai=False,
    )
    db.add(paper)
    db.flush()
    page = PaperPage(paper_id=paper.id, position=0, title=title[:220])
    db.add(page)
    db.flush()
    for position, block in enumerate(DEFAULT_LAYOUT):
        db.add(
            PaperBlock(
                page_id=page.id,
                type=block["type"],
                content=block["content"],
                position=position,
            )
        )
    db.flush()
    bus.emit(db, student_id, EventType.PAPER_CREATED, {"paper_id": paper.id, "kind": kind})
    return paper


def update_paper(
    db: Session, student_id: str, paper_id: str, data: dict[str, Any]
) -> Paper:
    paper = _owned(db, student_id, paper_id)
    if "title" in data:
        paper.title = str(data["title"]).strip()[:220] or paper.title
    if "emoji" in data:
        paper.emoji = str(data["emoji"])[:8]
    if "color" in data:
        paper.color = str(data["color"])[:16]
    if "tags" in data:
        paper.tags = [str(t) for t in (data["tags"] or [])][:8]
    if "archived" in data:
        paper.archived = bool(data["archived"])
    db.flush()
    return paper


def delete_paper(db: Session, student_id: str, paper_id: str) -> bool:
    paper = _owned(db, student_id, paper_id)
    db.delete(paper)
    db.flush()
    return True


def _owned(db: Session, student_id: str, paper_id: str) -> Paper:
    paper = db.get(Paper, paper_id)
    if paper is None or paper.student_id != student_id:
        raise NotFoundError("الورقة غير موجودة.")
    return paper


def paper_payload(db: Session, paper: Paper, *, with_blocks: bool = True) -> dict[str, Any]:
    pages_out = []
    page_ids = [p.id for p in paper.pages]
    blocks_by_page: dict[str, list[PaperBlock]] = {}
    if with_blocks and page_ids:
        rows = (
            db.query(PaperBlock)
            .filter(PaperBlock.page_id.in_(page_ids))
            .order_by(PaperBlock.position)
            .all()
        )
        for block in rows:
            blocks_by_page.setdefault(block.page_id, []).append(block)

    for page in sorted(paper.pages, key=lambda p: p.position):
        page_data: dict[str, Any] = {
            "id": page.id,
            "position": page.position,
            "title": page.title,
            "background": page.background,
            "blocks": [],
        }
        if with_blocks:
            page_data["blocks"] = [
                {
                    "id": b.id,
                    "type": b.type,
                    "content": b.content or {},
                    "position": b.position,
                    "x": b.x,
                    "y": b.y,
                    "width": b.width,
                    "height": b.height,
                }
                for b in blocks_by_page.get(page.id, [])
            ]
        pages_out.append(page_data)
    return {
        "id": paper.id,
        "title": paper.title,
        "kind": paper.kind,
        "subject_id": paper.subject_id,
        "lesson_id": paper.lesson_id,
        "emoji": paper.emoji,
        "color": paper.color,
        "tags": paper.tags or [],
        "archived": paper.archived,
        "created_by_ai": paper.created_by_ai,
        "page_count": len(pages_out),
        "pages": pages_out,
        "updated_at": paper.updated_at.isoformat() if paper.updated_at else None,
    }


def list_papers(
    db: Session,
    student_id: str,
    *,
    subject_id: str | None = None,
    kind: str | None = None,
    query: str = "",
    include_archived: bool = False,
    limit: int = 60,
) -> list[dict[str, Any]]:
    q = db.query(Paper).filter(Paper.student_id == student_id)
    if not include_archived:
        q = q.filter(Paper.archived.is_(False))
    if subject_id:
        q = q.filter(Paper.subject_id == subject_id)
    if kind:
        q = q.filter(Paper.kind == kind)
    if query:
        q = q.filter(Paper.title.like(f"%{query.strip()}%"))
    rows = q.order_by(Paper.updated_at.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "title": r.title,
            "kind": r.kind,
            "emoji": r.emoji,
            "color": r.color,
            "tags": r.tags or [],
            "subject_id": r.subject_id,
            "lesson_id": r.lesson_id,
            "page_count": len(r.pages),
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


# --------------------------------------------------------------------------- #
# editing
# --------------------------------------------------------------------------- #
def save_blocks(
    db: Session,
    student_id: str,
    *,
    page_id: str,
    blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    page = db.get(PaperPage, page_id)
    if page is None or page.paper.student_id != student_id:
        raise NotFoundError("الصفحة غير موجودة.")

    clean: list[dict[str, Any]] = []
    for index, raw in enumerate(blocks):
        block_type = str(raw.get("type", "text"))
        if block_type not in BLOCK_TYPES:
            raise ValidationError(f"نوع الكتلة غير مدعوم: {block_type}")
        content = raw.get("content")
        if not isinstance(content, dict):
            raise ValidationError("محتوى الكتلة غير صالح.")
        clean.append((index, block_type, content, raw))

    existing = {b.id: b for b in page.blocks}
    seen: set[str] = set()
    for position, block_type, content, raw in clean:
        block_id = str(raw.get("id") or "")
        row = existing.get(block_id) if block_id else None
        if row is None:
            row = PaperBlock(page_id=page.id, type=block_type, content=content, position=position)
            db.add(row)
        else:
            row.type = block_type
            row.content = content
            row.position = position
            row.x = int(raw.get("x", row.x) or 0)
            row.y = int(raw.get("y", row.y) or 0)
            row.width = int(raw.get("width", row.width) or 100)
        db.flush()
        seen.add(row.id)

    for block_id, row in list(existing.items()):
        if block_id not in seen:
            db.delete(row)
    db.flush()
    page.paper.updated_at = utcnow()
    db.flush()
    return paper_payload(db, page.paper)["pages"]


def add_page(
    db: Session, student_id: str, paper_id: str, *, title: str = "", background: str = "plain"
) -> dict[str, Any]:
    paper = _owned(db, student_id, paper_id)
    position = len(paper.pages)
    page = PaperPage(
        paper_id=paper.id, position=position, title=title[:220], background=background
    )
    db.add(page)
    db.flush()
    return {"id": page.id, "position": page.position, "title": page.title, "blocks": []}


# --------------------------------------------------------------------------- #
# AI generation
# --------------------------------------------------------------------------- #
def _local_paper(lesson: Lesson | None, title: str) -> list[dict[str, Any]]:
    objectives = [str(o) for o in (lesson.objectives or []) if o] if lesson else []
    blocks: list[dict[str, Any]] = [
        {"type": "heading", "content": {"text": title or (lesson.title if lesson else "ورقة")}},
    ]
    if lesson and lesson.summary:
        blocks.append({"type": "text", "content": {"text": lesson.summary}})
    if objectives:
        blocks.append({"type": "list", "content": {"items": objectives}})
    for index, objective in enumerate(objectives[:4], start=1):
        blocks.append(
            {
                "type": "mcq",
                "content": {
                    "question": f"{index}. {objective}",
                    "options": [objective, "غير ذي صلة", "عكس ما هو مذكور", "لا ينطبق"],
                    "answer_index": 0,
                },
            }
        )
    if lesson and lesson.keywords:
        keywords = ", ".join(str(k) for k in lesson.keywords)
        blocks.append({"type": "text", "content": {"text": f"المصطلحات: {keywords}"}})
    return blocks


def generate_paper(
    db: Session,
    student_id: str,
    *,
    title: str = "",
    lesson_id: str | None = None,
    subject_id: str | None = None,
    kind: str = "worksheet",
    use_ai: bool = True,
) -> dict[str, Any]:
    lesson = db.get(Lesson, lesson_id) if lesson_id else None
    if lesson and not subject_id:
        subject_id = lesson.subject_id
    final_title = title or (f"ورقة عمل — {lesson.title}" if lesson else "ورقة عمل")

    blocks = _local_paper(lesson, final_title)
    generated_by = "rules"

    if use_ai:
        chunks = retrieve(
            db,
            lesson.title if lesson else final_title,
            student_id=student_id,
            subject_id=subject_id,
            lesson_id=lesson_id,
            top_k=settings.rag_top_k,
        )
        try:
            answer = ask(
                db,
                AIRequest(
                    task="paper",
                    input=f"{kind}: {final_title}",
                    student_id=student_id,
                    subject_id=subject_id,
                    lesson_id=lesson_id,
                    context={
                        "الدرس": lesson_context(db, lesson_id),
                        "مصدر": chunks_to_context(chunks),
                    },
                    constraints="استند للسياق فقط. اكتب بالعربية.",
                    schema=(
                        '{"title":"...","blocks":[{"type":"heading|text|list|mcq|formula|divider",'
                        '"content":{}}]}'
                    ),
                    want_json=True,
                    max_tokens=2000,
                ),
            )
            raw_blocks = (answer.data or {}).get("blocks") if isinstance(answer.data, dict) else None
            if isinstance(raw_blocks, list) and raw_blocks:
                valid = [
                    {"type": str(b.get("type", "text")), "content": b.get("content") or {}}
                    for b in raw_blocks
                    if isinstance(b, dict)
                    and str(b.get("type", "")) in BLOCK_TYPES
                    and isinstance(b.get("content"), dict)
                ]
                if valid:
                    blocks = valid
                    generated_by = "ai"
                    final_title = str((answer.data or {}).get("title") or final_title)
        except Exception:  # noqa: BLE001
            pass

    paper = create_paper(
        db,
        student_id,
        title=final_title,
        kind=kind,
        subject_id=subject_id,
        lesson_id=lesson_id,
        tags=[kind],
    )
    paper.created_by_ai = generated_by == "ai"
    page = paper.pages[0]
    for block in page.blocks:
        db.delete(block)
    db.flush()
    for position, block in enumerate(blocks[:40]):
        db.add(
            PaperBlock(
                page_id=page.id,
                type=block["type"],
                content=block["content"],
                position=position,
            )
        )
    db.flush()

    if lesson and lesson.source_id:
        source = db.get(Source, lesson.source_id)
        if source is not None:
            paper.sources.append(
                PaperSource(paper_id=paper.id, source_id=source.id, note="مرجع الدرس")
            )
    db.flush()
    payload = paper_payload(db, paper)
    payload["generated_by"] = generated_by
    return payload


__all__ = [
    "BLOCK_TYPES",
    "create_paper",
    "update_paper",
    "delete_paper",
    "paper_payload",
    "list_papers",
    "save_blocks",
    "add_page",
    "generate_paper",
]
