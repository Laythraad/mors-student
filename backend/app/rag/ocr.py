"""Document text extraction: PDF, plain text and images (OCR).

OCR backends are pluggable and *optional* — the pipeline reports which engine
answered, and degrades to a clear "OCR unavailable" status instead of
pretending it read handwriting it never read.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..core.errors import UnsupportedFeatureError

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Extraction:
    pages: list[tuple[int, str]]
    engine: str
    chars: int

    @property
    def text(self) -> str:
        return "\n\n".join(body for _, body in self.pages)


def extract_pdf(path: str | Path, *, max_pages: int = 400) -> Extraction:
    """PDF → (page_number, text) using pypdf. No network, no key required."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise UnsupportedFeatureError("مكتبة قراءة PDF غير مثبتة.") from exc

    reader = PdfReader(str(path))
    pages: list[tuple[int, str]] = []
    for index, page in enumerate(reader.pages[:max_pages], start=1):
        try:
            body = page.extract_text() or ""
        except Exception:  # noqa: BLE001 - a single bad page must not kill the run
            body = ""
        if body.strip():
            pages.append((index, body))
    return Extraction(pages=pages, engine="pypdf", chars=sum(len(b) for _, b in pages))


def extract_text_file(path: str | Path) -> Extraction:
    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    pages = [(i + 1, block) for i, block in enumerate(raw.split("\f")) if block.strip()]
    if not pages:
        pages = [(1, raw)]
    return Extraction(pages=pages, engine="text", chars=len(raw))


def _tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def ocr_available() -> dict[str, bool]:
    has_tesseract = _tesseract_available()
    try:
        import pytesseract  # noqa: F401

        has_tesseract = has_tesseract and True
    except ImportError:
        has_tesseract = False
    from ..config import settings

    return {
        "tesseract": has_tesseract,
        "gemini_vision": bool(settings.gemini_api_key) and settings.ai_provider == "gemini",
    }


def extract_image(path: str | Path, *, hint: str = "", use_vision_model: bool = True) -> Extraction:
    """Image → text.

    Order: local Tesseract (fast, offline) → Gemini vision (accurate,
    handles handwriting) → explicit failure. The chosen engine is recorded so
    nobody mistakes OCR output for verified text.
    """
    availability = ocr_available()

    if availability["tesseract"]:
        try:
            import pytesseract
            from PIL import Image

            with Image.open(path) as image:
                text = pytesseract.image_to_string(image, lang="ara+eng")
            if text.strip():
                return Extraction(pages=[(1, text)], engine="tesseract", chars=len(text))
        except Exception as exc:  # noqa: BLE001
            logger.warning("tesseract failed: %s", exc)

    if use_vision_model and availability["gemini_vision"]:
        try:
            text = _vision_ocr(path, hint=hint)
            if text.strip():
                return Extraction(pages=[(1, text)], engine="gemini-vision", chars=len(text))
        except Exception as exc:  # noqa: BLE001
            logger.warning("vision OCR failed: %s", exc)

    raise UnsupportedFeatureError(
        "قراءة الصور غير مفعّلة في هذه البيئة. ثبّت Tesseract أو أضف GEMINI_API_KEY."
    )


def _vision_ocr(path: str | Path, *, hint: str = "") -> str:
    import base64

    from ..ai.base import ChatMessage, get_provider

    data = Path(path).read_bytes()
    mime = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
    image_url = f"data:{mime};base64,{base64.b64encode(data).decode()}"
    prompt = (
        "استخرج كل النص من هذه الصورة بدقة، مع الحفاظ على ترتيب الأسطر. "
        "إذا كان handwriting اذكر ذلك. لا تعلّق ولا تلخّص."
        + (f"\nتلميح: {hint}" if hint else "")
    )
    result = get_provider().complete(
        [ChatMessage(role="user", content=prompt, images=[image_url])],
        tier="vision",
        temperature=0.0,
        max_tokens=4096,
    )
    return result.text


def detect_lesson(text: str, lessons: list[tuple[str, str, list[str]]]) -> tuple[str | None, str | None]:
    """Cheap keyword match against (id, title, keywords) — no model call."""
    lowered = text.lower()
    best: tuple[int, str, str] | None = None
    for lesson_id, title, keywords in lessons:
        score = 0
        if title and title.lower() in lowered:
            score += 5
        for keyword in keywords:
            if keyword and keyword.lower() in lowered:
                score += 1
        if score and (best is None or score > best[0]):
            best = (score, lesson_id, title)
    if best is None:
        return None, None
    return best[1], best[2]


__all__ = [
    "Extraction",
    "extract_pdf",
    "extract_text_file",
    "extract_image",
    "ocr_available",
    "detect_lesson",
]
