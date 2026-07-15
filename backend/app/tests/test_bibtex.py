from app.ingestion.bibtex import (
    BibtexPaper,
    generate_bibtex_key,
    generate_fallback_bibtex,
    rekey_bibtex,
)


def _paper(**overrides) -> BibtexPaper:
    base = dict(
        title="P&L of Q&A systems: 100% _better_",
        publication_year=2024,
        venue_name="Conf & Journal",
        doi="10.1000/foo_bar",
        url=None,
        authors=["Ada Lovelace"],
    )
    base.update(overrides)
    return BibtexPaper(**base)


def test_key_format_and_collisions():
    paper = _paper()
    # first alphanumeric token of the title is "P" -> "p"
    assert generate_bibtex_key(paper, set()) == "lovelace2024p"
    assert generate_bibtex_key(paper, {"lovelace2024p"}) == "lovelace2024pa"
    assert generate_bibtex_key(paper, {"lovelace2024p", "lovelace2024pa"}) == "lovelace2024pb"


def test_key_handles_missing_fields():
    paper = _paper(title=None, publication_year=None, authors=[])
    assert generate_bibtex_key(paper, set()) == "unknownndpaper"


def test_escapes_hostile_title():
    paper = _paper()
    key = generate_bibtex_key(paper, set())
    bibtex = generate_fallback_bibtex(key, paper)
    assert r"\&" in bibtex
    assert r"\%" in bibtex
    assert r"\_" in bibtex
    assert "&" not in bibtex.replace(r"\&", "")   # no unescaped ampersand survives
    assert bibtex.startswith(f"@article{{{key},")


def test_rekey_bibtex_swaps_only_the_key():
    entry = "@article{Whatever_2020,\n  title = {Something},\n}\n"
    rekeyed = rekey_bibtex(entry, "lewis2020retrieval")
    assert rekeyed.startswith("@article{lewis2020retrieval,")
    assert "title = {Something}" in rekeyed
