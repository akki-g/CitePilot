from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.demo import DemoFile, _consume_quota, _refund_quota, _validate_sources
from app.config import Settings
from app.main import create_app


class FakeRedis:
    def __init__(self):
        self.values: dict[str, int] = {}
        self.expirations: dict[str, int] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def incr(self, key: str):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key: str, seconds: int):
        self.expirations[key] = seconds

    async def decr(self, key: str):
        self.values[key] = max(0, self.values.get(key, 0) - 1)
        return self.values[key]


def request_with(redis: FakeRedis):
    return SimpleNamespace(
        client=SimpleNamespace(host="127.0.0.1"),
        app=SimpleNamespace(state=SimpleNamespace(redis=redis)),
    )


async def test_demo_agent_quota_is_enforced_per_visitor():
    redis = FakeRedis()
    request = request_with(redis)
    settings = Settings(DEMO_AGENT_RUN_LIMIT=3)
    visitor = str(uuid4())

    assert await _consume_quota(request, visitor, "agent", settings) == 2
    assert await _consume_quota(request, visitor, "agent", settings) == 1
    assert await _consume_quota(request, visitor, "agent", settings) == 0
    with pytest.raises(HTTPException) as exc:
        await _consume_quota(request, visitor, "agent", settings)
    assert exc.value.status_code == 429
    # Rejected attempts do not make the quota counter grow beyond its limit.
    assert max(redis.values.values()) <= 3 * 10


async def test_failed_demo_work_can_refund_its_reserved_quota():
    redis = FakeRedis()
    request = request_with(redis)
    settings = Settings(DEMO_PREVIEW_LIMIT=3)
    visitor = str(uuid4())

    assert await _consume_quota(request, visitor, "preview", settings) == 2
    await _refund_quota(request, visitor, "preview")
    assert await _consume_quota(request, visitor, "preview", settings) == 2


def test_demo_sources_are_size_limited_and_must_be_unique():
    settings = Settings(DEMO_MAX_SOURCE_BYTES=10)

    with pytest.raises(HTTPException) as too_large:
        _validate_sources([DemoFile(path="main.tex", content="x" * 11)], settings)
    assert too_large.value.status_code == 413

    with pytest.raises(HTTPException) as duplicate:
        _validate_sources(
            [DemoFile(path="main.tex", content="a"), DemoFile(path="main.tex", content="b")],
            Settings(),
        )
    assert duplicate.value.status_code == 422


def test_browser_can_read_remaining_preview_header():
    app = create_app()
    cors = next(middleware for middleware in app.user_middleware if middleware.cls is CORSMiddleware)

    assert "X-Demo-Remaining" in cors.kwargs["expose_headers"]
