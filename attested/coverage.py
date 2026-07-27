"""attested.coverage -- fail closed on incomplete verdict sets.

Extracted from two real uses of the same pattern: the blog-archive audit
(which read 2 of 18 content files and never stated its scope, so every
probe passed honestly while the site kept contradicting itself) and
check_wiki_claims.py (which enumerates every wiki page and requires a
verdict for each). Both needed the same guarantee: a verdict set is
only trustworthy if it covers exactly the items it claims to cover --
no item silently skipped, no phantom item that was never enumerated.

This is deliberately NOT about whether individual verdicts are correct.
verify() and its templates handle that. This is the one level up:
whether the set of things checked matches the set of things that
exist, so "all checks passed" can't be true because some checks
never ran.
"""
from __future__ import annotations

from ._gate import SpecError


def verify_coverage(items: list[str], verdicts: dict) -> None:
    """Raise SpecError unless verdicts covers items exactly.

    items: the full, ground-truth set of things that should have a
        verdict (e.g. every file enumerated from disk).
    verdicts: mapping of item -> anything (a verdict, a Result, a
        tuple) -- only the keys are inspected here.

    Raises SpecError, naming exactly what's wrong, for:
    - a verdict count that doesn't match the item count
    - any item with no verdict (silently skipped)
    - any verdict key that isn't in items (phantom / stale entry)

    Does nothing (returns None) when coverage is exact -- callers
    still need to check the verdicts' own pass/fail themselves.
    """
    item_set = set(items)
    verdict_set = set(verdicts.keys())

    if len(items) != len(item_set):
        dupes = [i for i in item_set if items.count(i) > 1]
        raise SpecError(f"items contains duplicates, coverage is ill-defined: {dupes}")

    missing = item_set - verdict_set
    if missing:
        raise SpecError(
            f"{len(missing)} item(s) enumerated but never verdicted "
            f"(silently skipped): {sorted(missing)}"
        )

    phantom = verdict_set - item_set
    if phantom:
        raise SpecError(
            f"{len(phantom)} verdict(s) exist for item(s) never enumerated "
            f"(phantom/stale entries): {sorted(phantom)}"
        )

    if len(verdicts) != len(items):
        # Should be unreachable if the two set checks above passed, but
        # kept as a hard backstop -- this function's whole purpose is
        # not trusting a single check to be sufficient.
        raise SpecError(
            f"verdict count ({len(verdicts)}) != item count ({len(items)}) "
            "despite matching key sets -- investigate before trusting this run"
        )
