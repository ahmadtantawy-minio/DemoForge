import re


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[dict]:
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if not sentences:
        return []

    chunks = []
    current_chunk = ""
    chunk_index = 0

    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 > chunk_size and current_chunk:
            chunks.append({"text": current_chunk.strip(), "index": chunk_index})
            chunk_index += 1
            # Slide back by overlap
            if overlap > 0 and len(current_chunk) > overlap:
                current_chunk = current_chunk[-overlap:]
            else:
                current_chunk = ""
        current_chunk += (" " if current_chunk else "") + sentence

    if current_chunk.strip():
        chunks.append({"text": current_chunk.strip(), "index": chunk_index})

    return chunks
