import pytest
from sqlalchemy import func, select

from app.db.models import FileVersion, ProjectFile
from app.latex.patcher import (
    InsertAfterPatch,
    PatchError,
    ReplaceTextPatch,
    apply_patch,
    preview_patch,
)

CONTENT = "\\section{Intro}\nStart writing here.\n\\section{Methods}\nTBD.\n"


@pytest.fixture
async def tex_file(db_session, project) -> ProjectFile:
    file = ProjectFile(project_id=project.id, path="main.tex", content=CONTENT, version=1)
    db_session.add(file)
    await db_session.commit()
    return file


async def _snapshot_count(db_session, file) -> int:
    return (
        await db_session.execute(
            select(func.count()).select_from(FileVersion).where(FileVersion.file_id == file.id)
        )
    ).scalar_one()


async def test_replace_success_bumps_version_and_snapshots(db_session, tex_file):
    patch = ReplaceTextPatch(
        operation="replace_text", path="main.tex", base_version=1,
        old_text="Start writing here.", new_text="A brand new intro.",
    )
    result = await apply_patch(db_session, tex_file.project_id, patch)
    assert result == {"status": "applied", "path": "main.tex", "new_version": 2}
    await db_session.refresh(tex_file)
    assert "A brand new intro." in tex_file.content
    assert tex_file.version == 2
    snapshot = (
        await db_session.execute(
            select(FileVersion).where(FileVersion.file_id == tex_file.id, FileVersion.version == 2)
        )
    ).scalar_one()
    assert snapshot.created_by == "agent"


async def test_insert_after_success(db_session, tex_file):
    patch = InsertAfterPatch(
        operation="insert_after", path="main.tex", base_version=1,
        anchor_text="\\section{Intro}", new_text="\n\\label{sec:intro}",
    )
    await apply_patch(db_session, tex_file.project_id, patch)
    await db_session.refresh(tex_file)
    assert "\\section{Intro}\n\\label{sec:intro}" in tex_file.content


async def test_stale_version_rejected_without_mutation(db_session, tex_file):
    patch = ReplaceTextPatch(
        operation="replace_text", path="main.tex", base_version=99,
        old_text="Start writing here.", new_text="nope",
    )
    with pytest.raises(PatchError) as err:
        await apply_patch(db_session, tex_file.project_id, patch)
    assert err.value.code == "stale_version"
    assert err.value.details["current_version"] == 1
    await db_session.refresh(tex_file)
    assert tex_file.content == CONTENT and tex_file.version == 1
    assert await _snapshot_count(db_session, tex_file) == 0


async def test_anchor_not_found(db_session, tex_file):
    patch = ReplaceTextPatch(
        operation="replace_text", path="main.tex", base_version=1,
        old_text="THIS TEXT DOES NOT EXIST", new_text="x",
    )
    with pytest.raises(PatchError) as err:
        await apply_patch(db_session, tex_file.project_id, patch)
    assert err.value.code == "anchor_not_found"
    await db_session.refresh(tex_file)
    assert tex_file.content == CONTENT


async def test_anchor_ambiguous_reports_count(db_session, tex_file):
    patch = ReplaceTextPatch(
        operation="replace_text", path="main.tex", base_version=1,
        old_text="\\section", new_text="\\subsection",   # occurs twice
    )
    with pytest.raises(PatchError) as err:
        await apply_patch(db_session, tex_file.project_id, patch)
    assert err.value.code == "anchor_ambiguous"
    assert err.value.details["occurrences"] == 2


async def test_multiline_anchor(db_session, tex_file):
    patch = ReplaceTextPatch(
        operation="replace_text", path="main.tex", base_version=1,
        old_text="Start writing here.\n\\section{Methods}",
        new_text="Rewritten.\n\\section{Methods}",
    )
    result = await apply_patch(db_session, tex_file.project_id, patch)
    assert result["new_version"] == 2


async def test_preview_does_not_apply(db_session, tex_file):
    patch = ReplaceTextPatch(
        operation="replace_text", path="main.tex", base_version=1,
        old_text="Start writing here.", new_text="Previewed.",
    )
    preview = await preview_patch(db_session, tex_file.project_id, patch)
    assert "Previewed." in preview["after"]
    assert preview["before"] == CONTENT
    await db_session.refresh(tex_file)
    assert tex_file.content == CONTENT and tex_file.version == 1
