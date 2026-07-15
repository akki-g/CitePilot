async def test_health_reports_all_services(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["postgres"] == "ok"
    assert body["neo4j"] == "ok"
    assert body["redis"] == "ok"
