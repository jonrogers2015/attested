"""attested -- check that work actually happened.

AI agents report success. Sometimes they are wrong, and the failure mode is
not an exception -- it is a confident summary of work that did not occur.
attested checks the claim against the machine, with nothing in the checking path
that could itself be confused.

    from attested import verify, command_exit_code

    agent.run("fix the failing auth tests")

    check = verify(command_exit_code("pytest tests/auth"))
    if not check:
        escalate(check.detail)

WHY NOT JUST CALL subprocess YOURSELF

You can, and for one check you probably should. What this package buys you is
the part that is easy to get wrong, because it fails silently and in the
direction of "everything is fine". Every one of these was a live defect in
this code before it was extracted and tested:

    "" in output                      # true for every output ever
    expected = spec.get("expected", "")   # missing key -> matches everything
    "EXIT:1" in "EXIT:10"             # substring match on a number
    if "No such file" not in output:  # empty output -> "file exists!"

A checker that passes when the probe produced nothing is worse than no
checker: it manufactures confidence. So the central rule here is that
**attested fails closed**. Empty output, malformed spec, unknown key,
unparseable result -- all resolve to not-verified, with a reason.

WHERE THE PROBE RUNS IS THE WHOLE GAME

verify() takes an executor: a callable that runs a shell command and returns
its output. The default runs locally via subprocess. You can pass your own to
check a container, a remote host, or a git worktree.

The one rule: **the executor must not run inside the thing being verified.**
If you ask an agent to confirm its own work, you have rebuilt the problem
this package exists to solve. Run the probe in a separate process at minimum,
and on separate hardware if the claim is about hardware.

SPECS ARE DATA

Every check is a plain dict, so it can be stored in a database column, sent
over a queue, or written in config. The constructors below are ergonomics on
top of that format, not a replacement for it -- verify() accepts either.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Optional

from ._gate import (  # noqa: F401  (re-exported)
    SPEC_SCHEMA,
    SUPPORTED_TYPES,
    SpecError,
    build_raw_command,
    evaluate_probe_result,
    validate_spec,
)

__version__ = "0.0.1"

__all__ = [
    "verify",
    "Result",
    "VerificationFailed",
    "SpecError",
    "local",
    "ssh",
    "file_exists",
    "file_checksum",
    "command_exit_code",
    "command_output_contains",
    "agent_result_matches",
    "SUPPORTED_TYPES",
    "SPEC_SCHEMA",
    "validate_spec",
    "build_raw_command",
    "evaluate_probe_result",
]


class VerificationFailed(AssertionError):
    """Raised by Result.raise_for_status() when a check did not pass."""

    def __init__(self, message: str, result: "Result" | None = None):
        super().__init__(message)
        self.result = result


@dataclass(frozen=True)
class Result:
    """The verdict, plus everything needed to understand it.

    Truthy when the check passed, so `if not check:` reads naturally. The
    command and raw output are kept because "it failed" is rarely actionable
    on its own -- when a check fails at 3am you want to see exactly what ran
    and exactly what came back.
    """

    passed: bool
    detail: str
    spec: dict
    command: str
    output: str

    def __bool__(self) -> bool:
        return self.passed

    def raise_for_status(self) -> "Result":
        """Raise VerificationFailed unless the check passed. Returns self."""
        if not self.passed:
            raise VerificationFailed(self.detail, result=self)
        return self

    def __str__(self) -> str:
        return "%s: %s" % ("PASS" if self.passed else "FAIL", self.detail)


# --------------------------------------------------------------------- executors

Executor = Callable[[str], str]


def local(timeout: float = 60.0, shell: str = "/bin/sh") -> Executor:
    """Run probes as a local subprocess. The default executor.

    stdout and stderr are combined, because the evidence is often on stderr
    ("No such file or directory" is the canonical example).

    A timeout is enforced and, importantly, a timeout is a FAILURE rather
    than an exception that escapes -- a probe that hangs has not verified
    anything, and the caller should hear "not verified", not a traceback.
    """

    def run(command: str) -> str:
        proc = subprocess.run(
            [shell, "-c", command],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return (proc.stdout or "") + (proc.stderr or "")

    return run


def ssh(host: str, user: Optional[str] = None, timeout: float = 60.0) -> Executor:
    """Run probes on a remote host over SSH.

    Uses BatchMode so a missing key fails immediately instead of hanging on a
    password prompt -- an interactive prompt inside a verification path is a
    hang, and a hang is indistinguishable from a slow failure.

    Worth stating plainly: running the probe on a different machine than the
    agent is the strongest form of independence this package offers. Use it
    when the claim matters.
    """
    target = "%s@%s" % (user, host) if user else host

    def run(command: str) -> str:
        proc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", target, command],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return (proc.stdout or "") + (proc.stderr or "")

    return run


# ------------------------------------------------------------------ spec builders


def file_exists(path: str, min_bytes: Optional[int] = None) -> dict:
    """The file is present -- and optionally at least min_bytes in size.

    min_bytes is worth setting whenever an agent was supposed to write
    content. "The file exists" is satisfied by an empty file, which is a
    common shape for a failed write.
    """
    spec: dict[str, Any] = {"type": "file_exists", "path": path}
    if min_bytes is not None:
        spec["min_bytes"] = min_bytes
    return spec


def file_checksum(path: str, sha256: str) -> dict:
    """The file's contents hash to exactly this value.

    The strongest file check available: nothing produces the expected hash
    except the caller's own pre-computed value, so a plausible-looking wrong
    file cannot satisfy it.
    """
    return {"type": "file_checksum", "path": path, "sha256": sha256}


def command_exit_code(command: str, expected: int = 0) -> dict:
    """The command exits with this status. The test-suite check.

    `command_exit_code("pytest tests/auth")` is the whole reason this package
    is interesting for coding agents: "I fixed the tests" is a claim, and this
    is the machine's answer.
    """
    return {"type": "command_exit_code", "command": command, "expected_exit_code": expected}


def command_output_contains(command: str, expected: str) -> dict:
    """The command's output contains this string.

    The weakest check offered, and worth being honest about why: a fabricated
    output can contain the expected token by coincidence. A faked `df` table
    still contains a "/". Prefer command_exit_code or file_checksum when the
    claim matters; use agent_result_matches when you specifically want to
    catch a plausible-looking lie.
    """
    return {"type": "command_output_contains", "command": command, "expected": expected}


def agent_result_matches(
    command: str, match: str = "exact_string", match_key: Optional[str] = None
) -> dict:
    """The agent's reported result matches ground truth exactly.

    The only check that compares the CLAIM against reality rather than
    checking reality alone. Pass the agent's own reported output as
    agent_result to verify(). Use match="exact_line_containing" with a
    match_key to compare a single line out of noisy output.
    """
    spec: dict[str, Any] = {"type": "agent_result_matches_probe", "command": command}
    if match != "exact_string":
        spec["match"] = match
    if match_key is not None:
        spec["match_key"] = match_key
    return spec


# ------------------------------------------------------------------------ verify


def verify(
    spec: dict,
    executor: Optional[Executor] = None,
    agent_result: str = "",
) -> Result:
    """Run the probe for `spec` and judge its output. Returns a Result.

    spec may come from a constructor above or be a plain dict loaded from
    storage -- it is validated either way, and an invalid spec is a failed
    check, not a crash.

    agent_result is the agent's own claimed output. Only agent_result_matches
    uses it; ignore it otherwise.

    Never raises for a failed check. Call result.raise_for_status() if you
    want an exception. The distinction matters: most callers are deciding
    whether to retry or escalate, and control flow reads better than
    exception handling for that.
    """
    try:
        validate_spec(spec)
        command = build_raw_command(spec)
    except SpecError as exc:
        return Result(False, "invalid spec: %s" % exc, spec, "", "")

    run = executor or local()

    try:
        output = run(command)
    except subprocess.TimeoutExpired:
        return Result(
            False,
            "probe timed out, so nothing was verified. A probe that does not "
            "finish has not confirmed anything.",
            spec,
            command,
            "",
        )
    except Exception as exc:  # executor could not run at all
        return Result(
            False,
            "probe could not be executed (%s: %s), so nothing was verified."
            % (type(exc).__name__, exc),
            spec,
            command,
            "",
        )

    passed, detail = evaluate_probe_result(spec, output, agent_result)
    return Result(passed, detail, spec, command, output)
