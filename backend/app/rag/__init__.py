"""RAG pipeline: chunk → embed → index → hybrid retrieval."""

from .chunker import Chunk, chunk_pages, chunk_text, clean_text
from .embedder import cosine, embed, embed_batch, term_frequencies, tokens
from .ingest import index_book, index_chunks, index_extraction, ingest_upload
from .ocr import Extraction, detect_lesson, extract_image, extract_pdf, ocr_available
from .search import clear_query_cache, hybrid_search

__all__ = [
    "Chunk",
    "chunk_text",
    "chunk_pages",
    "clean_text",
    "embed",
    "embed_batch",
    "cosine",
    "tokens",
    "term_frequencies",
    "hybrid_search",
    "clear_query_cache",
    "index_chunks",
    "index_extraction",
    "index_book",
    "ingest_upload",
    "Extraction",
    "extract_pdf",
    "extract_image",
    "ocr_available",
    "detect_lesson",
]
