from app.graph.queries import two_hop_neighborhood


class FakeDriver:
    async def execute_query(self, query, **parameters):
        assert parameters == {"paper_id": "seed", "per_hop": 5}
        seed = {
            "id": "seed",
            "title": "Seed paper",
            "year": 2024,
            "cited_by_count": 10,
            "is_stub": False,
        }
        shared = {
            "id": "shared",
            "title": "Mutual citation",
            "year": 2023,
            "cited_by_count": 8,
            "is_stub": False,
        }
        placeholder = {
            "id": "stub",
            "title": None,
            "year": None,
            "cited_by_count": 0,
            "is_stub": True,
        }
        return ([{"seed": seed, "references": [shared, placeholder], "citers": [shared]}], None, None)


async def test_neighborhood_preserves_direction_and_reports_hidden_stubs():
    graph = await two_hop_neighborhood(FakeDriver(), "seed", per_hop=5)

    by_id = {node["id"]: node for node in graph["nodes"]}
    assert by_id["seed"]["role"] == "seed"
    assert by_id["shared"]["role"] == "both"
    assert graph["edges"] == [
        {"source": "seed", "target": "shared", "type": "CITES"},
        {"source": "seed", "target": "stub", "type": "CITES"},
        {"source": "shared", "target": "seed", "type": "CITES"},
    ]
    assert graph["stats"] == {
        "total_neighbors": 2,
        "visible_neighbors": 1,
        "hidden_stubs": 1,
    }
