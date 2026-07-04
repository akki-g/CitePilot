# reasons are rendered from computed features, never LLM freeform, thus they cant be hallucinated, and makes it easier to debug retrieval

from dataclasses import dataclass

@dataclass(frozen=True)
class RetrievalFeatures:
    retrieval_sources: list[str]
    shared_reference_count: int = 0
    co_citation_count: int = 0
    shared_concept_names: tuple[str, ...] = ()
    min_graph_distance: int | None = None
    cited_by_count: int = 0 
    publication_year: int | None = None
    in_project: bool = False
    is_stub: bool = False

def render_reason(features: RetrievalFeatures) -> str:
    # accumulate short evidence-backed phrases
    parts: list[str] = []

    sources = set(features.retrieval_sources)

    if "vector" in sources:
        parts.append("semantically close to your paragraph")
    if "coupling" in sources:
        if features.shared_reference_count:
            parts.append(f"shares {features.shared_reference_count} references with relevant papers")
        else:
            parts.append("shares references with relevant papers")
    if "co_citation" in sources:
        if features.co_citation_count:
            parts.append(f"co-cited with relevant papers by {features.co_citation_count} papers")
        else:
            parts.append("co-cited with relevant papers")
    if "shared_concepts" in sources:
        if features.shared_concept_names:
            concepts = ", ".join(features.shared_concept_names[:3])
            parts.append(f"shares concepts such as {concepts}")
        else:
            parts.append("shares concepts with relevant papers")
    if "citation_neighbors" in sources:
        parts.append("one citation hop from the papers matching your text")
    if features.in_project:
        parts.append("already in your project")
    if features.is_stub:
        parts.append("metadata is incomplete — import the full paper before citing")

    if not parts:
        return "Matched by the retrieval system, but no strong explanatory feats were available"

    reason = ", ".join(parts)
    return reason[0].upper() + reason[1:] + "."

