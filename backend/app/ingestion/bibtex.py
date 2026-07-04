# Regex handles key parsing and acronym protection.
import re
# unicodedata strips accents for ASCII-safe citation keys.
import unicodedata
# dataclass gives a tiny typed input object.
from dataclasses import dataclass

# Mapping of LaTeX special chars to safe escaped text.
LATEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


@dataclass(frozen=True)
class BibtexPaper:
    # Minimal paper shape needed to generate keys and fallback BibTeX.
    title: str | None
    publication_year: int | None
    venue_name: str | None
    doi: str | None
    url: str | None
    authors: list[str]


def latex_escape(value: str) -> str:
    # Replace every special character, leave ordinary characters unchanged.
    return "".join(LATEX_ESCAPES.get(ch, ch) for ch in value)


def ascii_slug(value: str) -> str:
    # Strip accents, lowercase, remove non-alphanumerics.
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", normalized.lower())


def first_title_word(title: str | None) -> str:
    # Used in keys like lewis2020retrieval.
    if not title:
        return "paper"
    for word in re.findall(r"[A-Za-z0-9]+", title):
        slug = ascii_slug(word)
        if slug:
            return slug
    return "paper"


def protect_acronyms(title: str) -> str:
    """Brace-protect ALL-CAPS tokens so BibTeX styles don't lowercase them."""
    return re.sub(r"\b([A-Z]{2,}[A-Za-z0-9-]*)\b", r"{\1}", title)


def generate_bibtex_key(paper: BibtexPaper, existing_keys: set[str]) -> str:
    """{firstauthorlastname}{year}{firsttitleword}, lowercase ASCII; collisions
    append a, b, c within the project."""
    last_name = "unknown"
    if paper.authors:
        last_name = ascii_slug(paper.authors[0].split()[-1]) or "unknown"
    year = str(paper.publication_year or "nd")
    base = f"{last_name}{year}{first_title_word(paper.title)}"
    key = base
    suffix_ord = ord("a")
    while key in existing_keys:
        # Collision handling: key, keya, keyb, ...
        key = f"{base}{chr(suffix_ord)}"
        suffix_ord += 1
    return key


def rekey_bibtex(bibtex: str, new_key: str) -> str:
    """Swap the entry key of the first BibTeX entry (Crossref returns its own key;
    the entry must match the key we put into \\cite{...})."""
    return re.sub(r"^(\s*@\w+\s*\{)[^,\n]*", lambda m: m.group(1) + new_key, bibtex, count=1)


def generate_fallback_bibtex(key: str, paper: BibtexPaper) -> str:
    # Build only fields we actually know.
    fields: list[tuple[str, str]] = []
    if paper.title:
        fields.append(("title", protect_acronyms(latex_escape(paper.title))))
    if paper.authors:
        fields.append(("author", " and ".join(latex_escape(a) for a in paper.authors)))
    if paper.publication_year:
        fields.append(("year", str(paper.publication_year)))
    if paper.venue_name:
        fields.append(("journal", latex_escape(paper.venue_name)))
    if paper.doi:
        fields.append(("doi", latex_escape(paper.doi)))
    if paper.url:
        fields.append(("url", latex_escape(paper.url)))
    body = ",\n".join(f"  {name} = {{{value}}}" for name, value in fields)
    return f"@article{{{key},\n{body}\n}}\n"