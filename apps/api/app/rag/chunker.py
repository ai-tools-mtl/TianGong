"""章节分块器（设计 10.3）。"""

from dataclasses import dataclass

MAX_CHUNK_CHARS = 800
OVERLAP_CHARS = 100


@dataclass
class Chunk:
    content: str
    section_key: str | None
    chunk_index: int


def chunk_sections(sections: list[dict]) -> list[Chunk]:
    """把章节列表分块。"""
    chunks: list[Chunk] = []
    for sec in sections:
        text = sec.get("content", "").strip()
        if not text:
            continue
        key = sec.get("key")
        if len(text) <= MAX_CHUNK_CHARS:
            chunks.append(Chunk(content=text, section_key=key, chunk_index=len(chunks)))
        else:
            for i in range(0, len(text), MAX_CHUNK_CHARS - OVERLAP_CHARS):
                piece = text[i : i + MAX_CHUNK_CHARS]
                if piece.strip():
                    chunks.append(Chunk(content=piece, section_key=key, chunk_index=len(chunks)))
                if i + MAX_CHUNK_CHARS >= len(text):
                    break
    return chunks
