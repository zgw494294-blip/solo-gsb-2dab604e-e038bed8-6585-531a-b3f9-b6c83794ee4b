"""End-to-end tests for POST /solve (solver semantics + 422 validation)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def solve(payload):
    return client.post("/solve", json=payload)


def entry(version, dependencies=None):
    return {"version": version, "dependencies": dependencies or {}}


# --------------------------------------------------------------------------
# Solving semantics
# --------------------------------------------------------------------------

def test_simple_resolution_picks_lexicographic_max_vector():
    # Candidates (app, lib): (1,1), (1,2), (2,2), (2,3) -> max is (2,3).
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
    resp = solve(payload)
    assert resp.status_code == 200
    assert resp.json() == {"satisfiable": True, "selected": {"app": 2, "lib": 3}}


def test_unreachable_packages_are_not_selected():
    payload = {
        "catalog": {
            "app": [entry(1)],
            "unused": [entry(1), entry(2)],
        },
        "roots": {"app": [1, 1]},
    }
    resp = solve(payload)
    assert resp.status_code == 200
    assert resp.json() == {"satisfiable": True, "selected": {"app": 1}}


def test_lexicographic_max_prefers_earlier_package_over_later_ones():
    # (a=2, b=1) beats (a=1, b=5): the first package name dominates.
    payload = {
        "catalog": {
            "a": [entry(1, {"b": [5, 5]}), entry(2, {"b": [1, 1]})],
            "b": [entry(1), entry(5)],
        },
        "roots": {"a": [1, 2]},
    }
    resp = solve(payload)
    assert resp.json() == {"satisfiable": True, "selected": {"a": 2, "b": 1}}


def test_selecting_a_package_beats_leaving_it_unselected():
    # Vector (a=1, b=2) > (a=1, b=0): any selected version outranks 0.
    payload = {
        "catalog": {
            "a": [entry(1, {"b": [1, 2]})],
            "b": [entry(1), entry(2)],
        },
        "roots": {"a": [1, 1]},
    }
    resp = solve(payload)
    assert resp.json() == {"satisfiable": True, "selected": {"a": 1, "b": 2}}


def test_satisfiable_circular_dependency():
    payload = {
        "catalog": {
            "a": [entry(1, {"b": [1, 1]})],
            "b": [entry(1, {"a": [1, 1]})],
        },
        "roots": {"a": [1, 1]},
    }
    resp = solve(payload)
    assert resp.json() == {"satisfiable": True, "selected": {"a": 1, "b": 1}}


def test_backtracking_on_conflict():
    # app=2 needs lib>=3, but lib=3 needs util>=2 while util only has v1,
    # so the solver must backtrack to app=1.
    payload = {
        "catalog": {
            "app": [entry(1, {"lib": [1, 1]}), entry(2, {"lib": [3, 3]})],
            "lib": [entry(1), entry(3, {"util": [2, 2]})],
            "util": [entry(1)],
        },
        "roots": {"app": [1, 2]},
    }
    resp = solve(payload)
    assert resp.json() == {"satisfiable": True, "selected": {"app": 1, "lib": 1}}


def test_transitive_dependency_chain():
    payload = {
        "catalog": {
            "a": [entry(1, {"b": [1, 2]})],
            "b": [entry(1), entry(2, {"c": [1, 1]})],
            "c": [entry(1)],
        },
        "roots": {"a": [1, 1]},
    }
    resp = solve(payload)
    # (1, 2, 1) beats (1, 1, 0): b=2 pulls in c.
    assert resp.json() == {
        "satisfiable": True,
        "selected": {"a": 1, "b": 2, "c": 1},
    }


def test_unsatisfiable_root_range():
    payload = {
        "catalog": {"app": [entry(1), entry(2)]},
        "roots": {"app": [3, 4]},
    }
    resp = solve(payload)
    assert resp.status_code == 200
    assert resp.json() == {"satisfiable": False, "selected": {}}


def test_unsatisfiable_dependency_range():
    payload = {
        "catalog": {
            "app": [entry(1, {"lib": [5, 9]})],
            "lib": [entry(1), entry(2)],
        },
        "roots": {"app": [1, 1]},
    }
    resp = solve(payload)
    assert resp.json() == {"satisfiable": False, "selected": {}}


def test_root_range_narrows_available_versions():
    payload = {
        "catalog": {"app": [entry(1), entry(2), entry(3)]},
        "roots": {"app": [1, 2]},
    }
    resp = solve(payload)
    assert resp.json() == {"satisfiable": True, "selected": {"app": 2}}


# --------------------------------------------------------------------------
# Validation (HTTP 422)
# --------------------------------------------------------------------------

def test_422_on_inverted_interval():
    payload = {
        "catalog": {"app": [entry(1)]},
        "roots": {"app": [2, 1]},
    }
    assert solve(payload).status_code == 422


def test_422_on_non_positive_interval_bound():
    payload = {
        "catalog": {"app": [entry(1)]},
        "roots": {"app": [0, 1]},
    }
    assert solve(payload).status_code == 422


def test_422_on_malformed_interval():
    payload = {
        "catalog": {"app": [entry(1)]},
        "roots": {"app": [1, 2, 3]},
    }
    assert solve(payload).status_code == 422


def test_422_on_duplicate_version_in_same_package():
    payload = {
        "catalog": {"app": [entry(1), entry(1)]},
        "roots": {"app": [1, 1]},
    }
    assert solve(payload).status_code == 422


def test_422_on_unknown_dependency_package():
    payload = {
        "catalog": {"app": [entry(1, {"ghost": [1, 1]})]},
        "roots": {"app": [1, 1]},
    }
    assert solve(payload).status_code == 422


def test_422_on_unknown_root_package():
    payload = {
        "catalog": {"app": [entry(1)]},
        "roots": {"ghost": [1, 1]},
    }
    assert solve(payload).status_code == 422


def test_422_on_empty_roots():
    payload = {"catalog": {"app": [entry(1)]}, "roots": {}}
    assert solve(payload).status_code == 422


def test_422_on_more_than_eight_packages():
    payload = {
        "catalog": {f"pkg{i}": [entry(1)] for i in range(9)},
        "roots": {"pkg0": [1, 1]},
    }
    assert solve(payload).status_code == 422


def test_422_on_more_than_five_versions():
    payload = {
        "catalog": {"app": [entry(i) for i in range(1, 7)]},
        "roots": {"app": [1, 6]},
    }
    assert solve(payload).status_code == 422


def test_422_on_package_without_versions():
    payload = {"catalog": {"app": []}, "roots": {"app": [1, 1]}}
    assert solve(payload).status_code == 422


def test_422_on_non_positive_version():
    payload = {"catalog": {"app": [entry(0)]}, "roots": {"app": [1, 1]}}
    assert solve(payload).status_code == 422


def test_422_on_boolean_version():
    payload = {
        "catalog": {"app": [{"version": True, "dependencies": {}}]},
        "roots": {"app": [1, 1]},
    }
    assert solve(payload).status_code == 422


def test_422_on_unknown_top_level_field():
    payload = {
        "catalog": {"app": [entry(1)]},
        "roots": {"app": [1, 1]},
        "extra": 1,
    }
    assert solve(payload).status_code == 422


def test_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.parametrize("size", [8])
def test_maximum_catalog_size_is_accepted(size):
    # 8 packages x 5 versions, fully connected: solver must cope.
    catalog = {}
    for i in range(size):
        name = f"pkg{i}"
        deps = {f"pkg{i + 1}": [1, 5]} if i + 1 < size else {}
        catalog[name] = [entry(v, deps) for v in range(1, 6)]
    resp = solve({"catalog": catalog, "roots": {"pkg0": [1, 5]}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["satisfiable"] is True
    assert body["selected"] == {f"pkg{i}": 5 for i in range(size)}
