from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from app.api.routes.latex import get_latest_compilation
from app.db.models import LatexCompilation


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeSession:
    def __init__(self, results):
        self.results = iter(results)

    async def get(self, model, object_id):
        return object()

    async def scalar(self, statement):
        return object()

    async def execute(self, statement):
        return ScalarResult(next(self.results))


def compilation(project_id, status, created_at, *, pdf_path=None, completed_at=None):
    row = LatexCompilation(
        id=uuid4(),
        project_id=project_id,
        status=status,
        main_file_path="main.tex",
        pdf_path=pdf_path,
    )
    row.created_at = created_at
    row.completed_at = completed_at
    row.logs = None
    row.error = "tectonic failed" if status == "failed" else None
    return row


async def test_latest_state_keeps_successful_pdf_when_newer_refresh_failed():
    project_id = uuid4()
    compiled_at = datetime(2026, 7, 15, 12, tzinfo=UTC)
    successful = compilation(
        project_id,
        "completed",
        compiled_at,
        pdf_path="/artifacts/last-good.pdf",
        completed_at=compiled_at + timedelta(seconds=3),
    )
    failed = compilation(
        project_id,
        "failed",
        compiled_at + timedelta(minutes=2),
        completed_at=compiled_at + timedelta(minutes=2, seconds=2),
    )
    source_updated_at = compiled_at + timedelta(minutes=1)
    session = FakeSession([successful, failed, source_updated_at])

    state = await get_latest_compilation(
        project_id,
        session=session,
        user=SimpleNamespace(id=uuid4()),
    )

    assert state["compilation"]["id"] == str(successful.id)
    assert state["compilation"]["has_pdf"] is True
    assert state["latest_attempt"]["id"] == str(failed.id)
    assert state["latest_attempt"]["status"] == "failed"
    assert state["is_stale"] is True
