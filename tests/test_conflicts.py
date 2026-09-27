"""End-to-end tests for POST /conflicts (same payload + validation as /solve)."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def conflicts(payload):
    return client.post("/conflicts", json=payload)


def entry(version, dependencies=None):
    return {"version": version, "dependencies": dependencies or {}}


# --------------------------------------------------------------------------
# Satisfiable requests
# --------------------------------------------------------------------------

def test_satisfiable_request_has_no_conflicts():
    payload = {
        "catalog": {
            "app": [
                entry(1, {"lib": [1, 2]}),
                entry(2, {"lib": [2, 3]}),
            ],
            "lib": [entry(1), entry(2), entry(3)],
        },
        "roots": {"app": [1, 2]},
    }
    resp = conflicts(payload)
    assert resp.status_code == 200
    assert resp.json() == {
        "satisfiable": True,
        "conflict_roots": [],
        "witnesses": {},
    }


# --------------------------------------------------------------------------
# Unsatisfiable requests: minimum-cardinality root subsets
# --------------------------------------------------------------------------

def test_single_unsatisfiable_root_has_empty_witness():
    payload = {
        "catalog": {"app": [entry(1), entry(2)]},
        "roots": {"app": [3, 4]},
    }
    resp = conflicts(payload)
    assert resp.status_code == 200
    assert resp.json() == {
        "satisfiable": False,
        "conflict_roots": ["app"],
        "witnesses": {"app": {}},
    }


def test_singleton_conflict_found_among_multiple_roots():
    payload = {
        "catalog": {
            "app": [entry(1), entry(2)],
            "lib": [entry(1)],
        },
        "roots": {"app": [3, 4], "lib": [1, 1]},
    }
    resp = conflicts(payload)
    assert resp.json() == {
        "satisfiable": False,
        "conflict_roots": ["app"],
        "witnesses": {"app": {}},
    }


def test_pairwise_conflict_witnesses():
    # web needs lib in [2, 3], cli needs lib == 1: together they clash,
    # each alone is fine.
    payload = {
        "catalog": {
            "web": [entry(1, {"lib": [2, 3]})],
            "cli": [entry(1, {"lib": [1, 1]})],
            "lib": [entry(1), entry(2), entry(3)],
        },
        "roots": {"web": [1, 1], "cli": [1, 1]},
    }
    resp = conflicts(payload)
    assert resp.json() == {
        "satisfiable": False,
        "conflict_roots": ["cli", "web"],
        "witnesses": {
            "cli": {"web": 1, "lib": 3},
            "web": {"cli": 1, "lib": 1},
        },
    }


def test_witness_uses_solve_version_vector_rule():
    # With b removed, a alone has two solutions and must pick the max vector
    # (a=2, lib=3) instead of (a=1, lib=2).
    payload = {
        "catalog": {
            "a": [entry(1, {"lib": [2, 2]}), entry(2, {"lib": [2, 3]})],
            "b": [entry(1, {"lib": [1, 1]})],
            "lib": [entry(1), entry(2), entry(3)],
        },
        "roots": {"a": [1, 2], "b": [1, 1]},
    }
    resp = conflicts(payload)
    assert resp.json() == {
        "satisfiable": False,
        "conflict_roots": ["a", "b"],
        "witnesses": {
            "a": {"b": 1, "lib": 1},
            "b": {"a": 2, "lib": 3},
        },
    }


def test_minimal_subset_ignores_innocent_roots():
    # b and c clash over lib; a is an unrelated root and must not appear.
    payload = {
        "catalog": {
            "a": [entry(1)],
            "b": [entry(1, {"lib": [1, 1]})],
            "c": [entry(1, {"lib": [2, 2]})],
            "lib": [entry(1), entry(2)],
        },
        "roots": {"a": [1, 1], "b": [1, 1], "c": [1, 1]},
    }
    resp = conflicts(payload)
    assert resp.json() == {
        "satisfiable": False,
        "conflict_roots": ["b", "c"],
        "witnesses": {
            "b": {"c": 1, "lib": 2},
            "c": {"b": 1, "lib": 1},
        },
    }


def test_tie_break_picks_lexicographically_smallest_subset():
    # Both {a, d} (clash over x) and {b, c} (clash over y) are minimum
    # unsatisfiable subsets; ["a", "d"] < ["b", "c"].
    payload = {
        "catalog": {
            "a": [entry(1, {"x": [1, 1]})],
            "b": [entry(1, {"y": [1, 1]})],
            "c": [entry(1, {"y": [2, 2]})],
            "d": [entry(1, {"x": [2, 2]})],
            "x": [entry(1), entry(2)],
            "y": [entry(1), entry(2)],
        },
        "roots": {
            "a": [1, 1],
            "b": [1, 1],
            "c": [1, 1],
            "d": [1, 1],
        },
    }
    resp = conflicts(payload)
    assert resp.json()["satisfiable"] is False
    assert resp.json()["conflict_roots"] == ["a", "d"]
    assert resp.json()["witnesses"] == {
        "a": {"d": 1, "x": 2},
        "d": {"a": 1, "x": 1},
    }


def test_dependency_induced_conflict_reaches_transitive_packages():
    # web v2 pulls lib v3 which needs util v2, but util only has v1. The
    # single root is therefore unsatisfiable.
    payload = {
        "catalog": {
            "web": [entry(2, {"lib": [3, 3]})],
            "lib": [entry(3, {"util": [2, 2]})],
            "util": [entry(1)],
        },
        "roots": {"web": [2, 2]},
    }
    resp = conflicts(payload)
    assert resp.json() == {
        "satisfiable": False,
        "conflict_roots": ["web"],
        "witnesses": {"web": {}},
    }


# --------------------------------------------------------------------------
# Validation shared with /solve (HTTP 422)
# --------------------------------------------------------------------------

def test_422_on_inverted_interval():
    payload = {
        "catalog": {"app": [entry(1)]},
        "roots": {"app": [2, 1]},
    }
    assert conflicts(payload).status_code == 422


def test_422_on_empty_roots():
    payload = {"catalog": {"app": [entry(1)]}, "roots": {}}
    assert conflicts(payload).status_code == 422


def test_422_on_unknown_root_package():
    payload = {
        "catalog": {"app": [entry(1)]},
        "roots": {"ghost": [1, 1]},
    }
    assert conflicts(payload).status_code == 422


def test_422_on_extra_top_level_field():
    payload = {
        "catalog": {"app": [entry(1)]},
        "roots": {"app": [1, 1]},
        "extra": 1,
    }
    assert conflicts(payload).status_code == 422
