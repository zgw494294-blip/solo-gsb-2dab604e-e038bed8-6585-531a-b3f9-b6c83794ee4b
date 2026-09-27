"""Request/response schemas and input validation.

All validation failures raise ``pydantic.ValidationError`` which FastAPI turns
into HTTP 422 responses.
"""

from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    model_validator,
)

# StrictInt rejects booleans and floats (e.g. ``true`` / ``1.0``).
PositiveInt = Annotated[StrictInt, Field(gt=0)]

MAX_PACKAGES = 8
MAX_VERSIONS_PER_PACKAGE = 5


def _check_bounds(interval: list[int]) -> list[int]:
    """Reject inverted closed intervals such as ``[3, 1]``."""
    low, high = interval
    if low > high:
        raise ValueError("interval lower bound must be less than or equal to upper bound")
    return interval


# A closed interval ``[min, max]`` given in JSON as a two-element integer array.
Interval = Annotated[
    list[PositiveInt],
    Field(min_length=2, max_length=2),
    AfterValidator(_check_bounds),
]


class VersionEntry(BaseModel):
    """One concrete package version and the dependency ranges it requires."""

    model_config = ConfigDict(extra="forbid")

    version: PositiveInt
    dependencies: dict[str, Interval] = Field(default_factory=dict)


class SolveRequest(BaseModel):
    """Payload for ``POST /solve``."""

    model_config = ConfigDict(extra="forbid")

    catalog: dict[
        str,
        Annotated[list[VersionEntry], Field(min_length=1, max_length=MAX_VERSIONS_PER_PACKAGE)],
    ]
    roots: dict[str, Interval] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_catalog(self) -> "SolveRequest":
        if len(self.catalog) > MAX_PACKAGES:
            raise ValueError(
                f"catalog must contain at most {MAX_PACKAGES} packages, "
                f"got {len(self.catalog)}"
            )

        known_packages = set(self.catalog)
        for name, entries in self.catalog.items():
            if not name:
                raise ValueError("package name must be a non-empty string")

            seen_versions: set[int] = set()
            for entry in entries:
                if entry.version in seen_versions:
                    raise ValueError(
                        f"duplicate version {entry.version} for package {name!r}"
                    )
                seen_versions.add(entry.version)

                unknown = sorted(set(entry.dependencies) - known_packages)
                if unknown:
                    raise ValueError(
                        "dependency references unknown package(s): " + ", ".join(unknown)
                    )

        unknown_roots = sorted(set(self.roots) - known_packages)
        if unknown_roots:
            raise ValueError(
                "root references unknown package(s): " + ", ".join(unknown_roots)
            )
        return self


class SolveResponse(BaseModel):
    """Result of a solve attempt."""

    satisfiable: bool
    selected: dict[str, int]


class ConflictsResponse(BaseModel):
    """Result of a conflict-analysis attempt.

    When the request is satisfiable both ``conflict_roots`` and
    ``witnesses`` are empty. Otherwise ``conflict_roots`` is the
    minimum-cardinality unsatisfiable root subset and ``witnesses`` maps
    each of its members to the selection obtained without that member.
    """

    satisfiable: bool
    conflict_roots: list[str]
    witnesses: dict[str, dict[str, int]]
