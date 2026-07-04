from dataclasses import dataclass

@dataclass(frozen=True)
class Chunk:
    chunk_index: int
    section: str
    text: str
    token_count: int | None = None

def build_title_abstract_chunk(title: str | None, abstract: str | None) -> Chunk | None:
    # Strip empty values and keep title before abstract.
    parts = [part.strip() for part in [title, abstract] if part and part.strip()]
    if not parts:
        return None  # bare stub: nothing to embed yet
    # Separate title and abstract with a blank line so the embedding sees both clearly.
    text = "\n\n".join(parts)
    return Chunk(
        chunk_index=0,
        section="title_abstract",
        text=text,
        token_count=max(1, len(text.split())),  # word count as a cheap proxy
    )