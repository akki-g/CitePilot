import pytest

from app.latex.sanitizer import UnsafePathError, sanitize_project_path


@pytest.mark.parametrize("path", ["main.tex", "sections/intro.tex", "figures/plot-1.pdf"])
def test_safe_paths(path):
    assert sanitize_project_path(path) == path


@pytest.mark.parametrize(
    "path",
    ["/etc/passwd", "../x", "a/../b", ".env", "a/.hidden/b.tex", "a\\.tex", "a b.tex", "a\x00b", ""],
)
def test_unsafe_paths(path):
    with pytest.raises(UnsafePathError):
        sanitize_project_path(path)
