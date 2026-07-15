import json
from pathlib import Path

from app.ingestion.normalize import (
    normalize_doi,
    normalize_openalex_work,
    normalize_title_for_match,
    reconstruct_openalex_abstract,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_normalize_doi_strips_url_and_lowercases():
    assert normalize_doi("https://doi.org/10.1145/ABC.Def") == "10.1145/abc.def"
    assert normalize_doi("http://dx.doi.org/10.1000/XYZ") == "10.1000/xyz"
    assert normalize_doi(" 10.1000/Foo ") == "10.1000/foo"
    assert normalize_doi(None) is None
    assert normalize_doi("") is None


def test_normalize_title_for_match():
    assert normalize_title_for_match("GraphRAG:  A Survey!") == "graphrag a survey"
    assert normalize_title_for_match("  ") is None
    assert normalize_title_for_match(None) is None


def test_reconstruct_openalex_abstract_orders_words():
    inv = {"world": [1], "hello": [0], "again": [2]}
    assert reconstruct_openalex_abstract(inv) == "hello world again"
    assert reconstruct_openalex_abstract(None) is None
    assert reconstruct_openalex_abstract({}) is None


def test_normalize_openalex_work_fixture():
    work = json.loads((FIXTURES / "openalex_work.json").read_text())
    np = normalize_openalex_work(work)
    assert np.source == "openalex"
    assert np.source_id == "https://openalex.org/W123"
    assert np.doi == "10.1000/test.doi"                       # normalized from the URL form
    assert np.title == "Graph Retrieval Augmented Generation"
    assert np.abstract == "Graph retrieval uses citations"    # reconstructed
    assert np.publication_year == 2024
    assert np.venue_name == "Test Conference"
    assert np.pdf_url == "https://example.com/paper.pdf"
    assert np.reference_source_ids == [
        "https://openalex.org/WREF1",
        "https://openalex.org/WREF2",
    ]
    assert [a.name for a in np.authors] == ["Ada Lovelace"]
    assert {c.name for c in np.concepts} == {"Knowledge graphs", "Information retrieval"}
