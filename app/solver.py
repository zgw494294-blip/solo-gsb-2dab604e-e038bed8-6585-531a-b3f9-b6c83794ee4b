"""Backtracking dependency solver.

The solver works purely on the catalog supplied in the request; it never
touches the network or any external package repository.

Semantics
---------
* Every root package must be selected, with a version inside its root range.
* Selecting version ``v`` of package ``p`` requires every package listed in
  ``v``'s dependencies to be selected as well, with a version inside the
  declared closed interval. This applies transitively, so circular
  dependencies are allowed as long as consistent versions exist.
* Exactly the packages reachable from the roots along the chosen versions'
  dependencies are selected -- no more, no less -- and each selected package
  gets exactly one version.
* If several assignments satisfy all constraints, the winner is the one whose
  version vector (all catalog package names sorted ascending, unselected
  packages counted as 0) is lexicographically largest.
"""

from __future__ import annotations

import itertools

# catalog: package name -> {version number -> {dependency name -> (low, high)}}
Catalog = dict[str, dict[int, dict[str, tuple[int, int]]]]
# roots: package name -> (low, high)
Roots = dict[str, tuple[int, int]]


def solve(catalog: Catalog, roots: Roots) -> dict[str, int] | None:
    """Return the selected ``{package: version}`` mapping, or ``None`` if
    the constraints are unsatisfiable."""

    names = sorted(catalog)
    # Trying higher versions first tends to find strong candidates early, so
    # the branch-and-bound pruning can discard most of the remaining tree.
    # Correctness does not depend on this ordering: the optimistic bound
    # below is sound regardless of traversal order.
    version_lists = {name: sorted(catalog[name], reverse=True) for name in names}
    max_version = {name: version_lists[name][0] for name in names}

    assignment: dict[str, int] = {}
    # Inclusive version intervals accumulated per package (root ranges plus
    # every dependency edge pointing at the package).
    constraints: dict[str, list[tuple[int, int]]] = {name: [] for name in names}
    for name, interval in roots.items():
        constraints[name].append(interval)
    # Packages that must be selected: starts at the roots and grows along the
    # dependency edges of every assigned version.
    required: set[str] = set(roots)

    best_vector: tuple[int, ...] | None = None
    best_selection: dict[str, int] | None = None

    def record_solution() -> None:
        nonlocal best_vector, best_selection
        vector = tuple(assignment.get(name, 0) for name in names)
        if best_vector is None or vector > best_vector:
            best_vector = vector
            best_selection = dict(assignment)

    def optimistic_vector_le_best() -> bool:
        """True if even the most optimistic completion cannot beat ``best``.

        Fixed entries keep their version; every unassigned package
        optimistically gets its highest catalog version. The latter is loose
        (the package might stay unselected, value 0, or get constrained to a
        lower version), but it is a genuine componentwise upper bound on every
        completion -- an unselected package may still be pulled in later by a
        dependency edge, so assuming value 0 for it would be unsafe.
        """
        if best_vector is None:
            return False
        for index, name in enumerate(names):
            upper = assignment[name] if name in assignment else max_version[name]
            if upper > best_vector[index]:
                return False
            if upper < best_vector[index]:
                return True
        return True  # equal at best -- no need to explore

    def backtrack() -> None:
        if optimistic_vector_le_best():
            return
        # Depth-first over the still-unassigned required packages.
        target = next(
            (name for name in names if name in required and name not in assignment),
            None,
        )
        if target is None:
            # Every reachable package has exactly one version and all
            # constraints were checked on assignment: this is a solution.
            record_solution()
            return

        for version in version_lists[target]:
            if any(not low <= version <= high for low, high in constraints[target]):
                continue  # conflicts with an already-imposed range

            assignment[target] = version
            constrained: list[str] = []  # packages that gained an interval
            newly_required: list[str] = []  # packages added to `required`
            consistent = True
            for dep, (low, high) in catalog[target][version].items():
                constraints[dep].append((low, high))
                constrained.append(dep)
                if dep not in required:
                    required.add(dep)
                    newly_required.append(dep)
                if dep in assignment and not low <= assignment[dep] <= high:
                    consistent = False  # new edge contradicts a fixed version
                    break

            if consistent:
                backtrack()

            # Undo this branch before trying the next version.
            for dep in constrained:
                constraints[dep].pop()
            for dep in newly_required:
                required.discard(dep)
            del assignment[target]

    backtrack()
    return best_selection


def find_minimal_conflict(
    catalog: Catalog, roots: Roots
) -> tuple[list[str], dict[str, dict[str, int]]] | None:
    """Explain an unsatisfiable request, or return ``None`` if it is solvable.

    The result is a pair ``(conflict_roots, witnesses)``:

    * ``conflict_roots`` -- a minimum-cardinality subset of the root package
      names that is unsatisfiable on its own. Ties are broken by choosing the
      lexicographically smallest sorted name list. The names are returned
      sorted ascending.
    * ``witnesses`` -- for every name in ``conflict_roots``, the ``selected``
      mapping obtained by solving with only the *remaining* roots of the
      subset (same lexicographic-maximum rule as :func:`solve`). Minimality
      guarantees each such sub-problem is satisfiable. When no roots remain
      (singleton conflict) the witness is the empty mapping.
    """
    if solve(catalog, roots) is not None:
        return None

    names = sorted(roots)
    conflict: tuple[str, ...] | None = None
    # Subsets are enumerated by increasing size, and combinations over the
    # sorted names are yielded in lexicographic order, so the first
    # unsatisfiable subset found is exactly the required answer.
    for size in range(1, len(names) + 1):
        for combo in itertools.combinations(names, size):
            if solve(catalog, {name: roots[name] for name in combo}) is None:
                conflict = combo
                break
        if conflict is not None:
            break

    # The full root set is unsatisfiable, so some subset must be too.
    assert conflict is not None

    witnesses: dict[str, dict[str, int]] = {}
    for name in conflict:
        remaining = {other: roots[other] for other in conflict if other != name}
        if not remaining:
            witnesses[name] = {}
        else:
            selected = solve(catalog, remaining)
            # `conflict` is minimal, so dropping any member is satisfiable.
            assert selected is not None
            witnesses[name] = selected
    return list(conflict), witnesses
