# reciprocal rank fusion (RRF) not weighted decisions 
# each method retrieves their top k results and RRF combines them into one entire ranked list

from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

@dataclass(frozen=True)
class FusedCandidate:
    paper_id: UUID
    score: float
    retrieval_sources: list[str]


def rrf_fuse(ranked_lists: dict[str, list[UUID]], k: int = 60) -> list[FusedCandidate]:
    """
    RRF: score(paper) = sum over lists of 1 / (k + rank)

    ranks start at 1. Duplicates withing one list count once, at their best rank.
    ties break on paper_id str for determinism
    """

    scores: dict[UUID, float] = defaultdict(float)
    sources: dict[UUID, list[str]] = defaultdict(list)

    # iterate over each independent retrieval signal
    for source_name, papers in ranked_lists.items():
        # a paper duplicated within one list should only count once
        seen: set[UUID] = set()
        # rank is counted after deduping
        rank = 0 
        for paper_id in papers:
            if paper_id in seen:
                continue
            seen.add(paper_id)

            rank += 1
            # RRF contribution: high ranks add slightly more than low ranks
            scores[paper_id] += 1.0 / (k + rank)
            sources[paper_id].append(source_name)

    return sorted(
        (
            FusedCandidate(paper_id=paper_id, score=score, retrieval_sources=sources[paper_id])
            for paper_id, score in scores.items()
        ),
        key=lambda c: (-c.score, str(c.paper_id)),
    )


# inputs are paper Id lists, not raw similarity/count scores
# rrf deliberately ignored scale differences across vector similarity and graph counts
# k=60 dampens rank differences so cross-signal consensus matters
# deterministic tie-breaking makes tests stable