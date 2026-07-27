"""attested.templates -- safer defaults for authoring specs.

Thin wrappers around the core constructors (file_exists, file_checksum,
command_exit_code, command_output_contains, agent_result_matches). These
do not change what verify() accepts or how the gate evaluates a spec --
they only make it harder to accidentally author a vacuous one.

Every function here raises SpecError at AUTHORING time for a pattern
that would otherwise pass silently at VERIFICATION time. That is the
whole value: catching the mistake before the task ever runs, not after.

This module exists because a weak or small model authoring its own
specs will make the same mistakes attested's core already had to fix
once (see __init__.py's module docstring) -- these wrappers push the
safe shape into the default path instead of relying on the author's
judgment every time.
"""
from __future__ import annotations

import re
from typing import Optional

from . import (
    file_exists,
    file_checksum,
    command_exit_code,
    command_output_contains,
    agent_result_matches,
)
from ._gate import SpecError

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EMPTY_FILE_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def safe_file_exists(path: str, min_bytes: int = 1) -> dict:
    """min_bytes defaults to 1, not None -- a file existing with zero
    bytes is rarely the claim anyone actually wants verified. Pass
    file_exists() directly if a 0-byte check is truly intended."""
    if min_bytes < 1:
        raise SpecError(
            f"min_bytes must be >= 1, got {min_bytes!r}. "
            "Use file_exists() directly if 0 is truly intended."
        )
    return file_exists(path, min_bytes=min_bytes)


def safe_file_checksum(path: str, expected_sha256: str) -> dict:
    """Refuses an empty/malformed hash, and refuses the empty-file hash
    unless the caller uses file_checksum() directly to make that
    explicit. The empty-file hash is what an unwritten file, or a
    write/check path mismatch, produces -- exactly the Phase 1.2
    harness bug (write targeted one path, check targeted another)."""
    if not expected_sha256 or not _SHA256_RE.match(expected_sha256):
        raise SpecError(
            f"expected_sha256 must be a 64-char lowercase hex string, got: {expected_sha256!r}"
        )
    if expected_sha256 == _EMPTY_FILE_SHA256:
        raise SpecError(
            "expected_sha256 is the empty-file hash. If an empty file is "
            "really the claim, use file_checksum() directly."
        )
    return file_checksum(path, sha256=expected_sha256)


def safe_command_output_contains(command: str, expected: str) -> dict:
    """Refuses an empty or whitespace-only expected string. attested's
    core already fails closed on empty PROBE output; an empty EXPECTED
    value is an authoring mistake, not a probe failure, and is worth
    catching when the spec is written rather than when it runs."""
    if not expected or not expected.strip():
        raise SpecError("expected must be a non-empty, non-whitespace string")
    return command_output_contains(command, expected=expected)


def safe_command_exit_code(command: str, expected: int = 0) -> dict:
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise SpecError(f"expected must be an int, got: {type(expected).__name__}")
    return command_exit_code(command, expected=expected)


def safe_agent_result_matches(
    command: str, match: str = "exact_string", match_key: Optional[str] = None
) -> dict:
    if match not in ("exact_string", "exact_line_containing"):
        raise SpecError(f"match must be 'exact_string' or 'exact_line_containing', got: {match!r}")
    if match == "exact_line_containing" and not match_key:
        raise SpecError("match_key is required when match='exact_line_containing'")
    return agent_result_matches(command, match=match, match_key=match_key)


def roundtrip_checksum_spec(write_command: str, check_path: str, expected_sha256: str) -> dict:
    """Purpose-built for the exact Phase 1.2 bug: a write step targets
    one path, a check step targets a different one, and the mismatch is
    invisible until the check fails for no apparent reason. Requires the
    check_path literal to appear in write_command, so a copy/paste path
    drift is caught at authoring time instead of showing up as a
    mystery failure during a run."""
    if check_path not in write_command:
        raise SpecError(
            f"check_path {check_path!r} does not appear in write_command "
            f"{write_command!r} -- this is the write/check path-mismatch "
            "bug from Phase 1.2. Fix the write command or the check_path."
        )
    return safe_file_checksum(check_path, expected_sha256)
