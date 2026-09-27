"""FastAPI application exposing the offline dependency solver."""

from fastapi import FastAPI

from .schemas import ConflictsResponse, SolveRequest, SolveResponse
from .solver import find_minimal_conflict, solve

app = FastAPI(
    title="Offline Dependency Solver",
    summary="Resolve package versions from a self-contained catalog. "
    "No external package repository is ever contacted.",
    version="1.1.0",
)


def _solver_inputs(request: SolveRequest):
    """Convert a validated request into the solver's native structures."""
    catalog = {
        name: {
            entry.version: {
                dep: (interval[0], interval[1])
                for dep, interval in entry.dependencies.items()
            }
            for entry in entries
        }
        for name, entries in request.catalog.items()
    }
    roots = {
        name: (interval[0], interval[1]) for name, interval in request.roots.items()
    }
    return catalog, roots


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/solve", response_model=SolveResponse)
def solve_endpoint(request: SolveRequest) -> SolveResponse:
    catalog, roots = _solver_inputs(request)

    selected = solve(catalog, roots)
    if selected is None:
        return SolveResponse(satisfiable=False, selected={})
    return SolveResponse(satisfiable=True, selected=selected)


@app.post("/conflicts", response_model=ConflictsResponse)
def conflicts_endpoint(request: SolveRequest) -> ConflictsResponse:
    catalog, roots = _solver_inputs(request)

    result = find_minimal_conflict(catalog, roots)
    if result is None:
        return ConflictsResponse(satisfiable=True, conflict_roots=[], witnesses={})
    conflict_roots, witnesses = result
    return ConflictsResponse(
        satisfiable=False, conflict_roots=conflict_roots, witnesses=witnesses
    )
