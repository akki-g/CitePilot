from uuid import UUID, uuid4

from app.retrieval.fusion import rrf_fuse


def test_rrf_rewards_consensus_over_single_top_rank():
    a, b, c = uuid4(), uuid4(), uuid4()
    # a: rank2 + rank2 + rank1 across three lists; b: single rank1
    fused = rrf_fuse({"one": [b, a], "two": [c, a], "three": [a]}, k=60)
    assert fused[0].paper_id == a
    assert set(fused[0].retrieval_sources) == {"one", "two", "three"}


def test_rrf_empty_input():
    assert rrf_fuse({}) == []
    assert rrf_fuse({"empty": []}) == []


def test_rrf_dedupes_within_one_list():
    a = uuid4()
    fused = rrf_fuse({"one": [a, a, a]}, k=60)
    assert len(fused) == 1
    assert abs(fused[0].score - 1.0 / 61) < 1e-12   # counted once, at rank 1


def test_rrf_tie_order_is_deterministic():
    a = UUID("00000000-0000-0000-0000-00000000000a")
    b = UUID("00000000-0000-0000-0000-00000000000b")
    first = rrf_fuse({"one": [a], "two": [b]})
    second = rrf_fuse({"two": [b], "one": [a]})   # same input, different dict order
    assert [c.paper_id for c in first] == [c.paper_id for c in second] == [a, b]
