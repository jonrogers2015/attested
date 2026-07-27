"""Smoke test for attested.coverage -- run directly, unambiguous stdout."""
import sys
sys.path.insert(0, "/root/attested")

from attested.coverage import verify_coverage
from attested._gate import SpecError

failures = []

def check(name, condition):
    if condition:
        print(f"PASS {name}")
    else:
        print(f"FAIL {name}")
        failures.append(name)

# --- happy path: exact coverage ---
try:
    verify_coverage(["a.md", "b.md", "c.md"], {"a.md": "verified", "b.md": "stale", "c.md": "no_claims"})
    check("exact coverage passes silently", True)
except SpecError:
    check("exact coverage passes silently", False)

# --- missing item (silently skipped) ---
try:
    verify_coverage(["a.md", "b.md", "c.md"], {"a.md": "verified", "b.md": "stale"})
    check("missing item raises SpecError", False)
except SpecError as e:
    check("missing item raises SpecError", "c.md" in str(e))

# --- phantom verdict (never enumerated) ---
try:
    verify_coverage(["a.md", "b.md"], {"a.md": "verified", "b.md": "stale", "ghost.md": "verified"})
    check("phantom verdict raises SpecError", False)
except SpecError as e:
    check("phantom verdict raises SpecError", "ghost.md" in str(e))

# --- duplicate items (ill-defined coverage) ---
try:
    verify_coverage(["a.md", "a.md", "b.md"], {"a.md": "verified", "b.md": "stale"})
    check("duplicate items raises SpecError", False)
except SpecError as e:
    check("duplicate items raises SpecError", "a.md" in str(e))

# --- empty sets: trivially exact coverage ---
try:
    verify_coverage([], {})
    check("empty items/verdicts passes (trivially covered)", True)
except SpecError:
    check("empty items/verdicts passes (trivially covered)", False)

# --- both missing and phantom at once ---
try:
    verify_coverage(["a.md", "b.md"], {"a.md": "verified", "ghost.md": "verified"})
    check("missing+phantom combo raises SpecError", False)
except SpecError as e:
    check("missing+phantom combo raises SpecError", "b.md" in str(e))

print()
if failures:
    print(f"SMOKE_TEST_RESULT: FAIL ({len(failures)} failures: {failures})")
    sys.exit(1)
else:
    print("SMOKE_TEST_RESULT: ALL_PASS")
    sys.exit(0)
