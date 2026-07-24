"""Tests for attested.

Two layers are covered:

  * the pure evaluation logic -- spec in, verdict out, no I/O
  * verify() and the executor seam -- what happens when the probe itself
    misbehaves, which is where a verifier is most likely to lie by accident

The second group matters more than it looks. A verifier's dangerous failure is
not "it crashed" -- it is "it returned True". Every test in TestFailsClosed
describes a way this package could have said yes to nothing, and four of them
were live defects in the code this was extracted from.

Run:
    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import subprocess
import unittest

from attested import (
    Result,
    SpecError,
    VerificationFailed,
    agent_result_matches,
    build_raw_command,
    command_exit_code,
    command_output_contains,
    evaluate_probe_result,
    file_checksum,
    file_exists,
    local,
    validate_spec,
    verify,
)

HASH_A = "a" * 64
HASH_B = "b" * 64


def returns(text: str):
    """An executor that always returns `text`, whatever it is asked to run."""
    return lambda command: text


def raises(exc: Exception):
    """An executor that always blows up."""

    def run(command: str) -> str:
        raise exc

    return run


class TestSpecConstructors(unittest.TestCase):
    """The ergonomic layer must emit specs the strict validator accepts."""

    def test_every_constructor_produces_a_valid_spec(self):
        specs = [
            file_exists("/tmp/x"),
            file_exists("/tmp/x", min_bytes=10),
            file_checksum("/tmp/x", HASH_A),
            command_exit_code("true"),
            command_exit_code("false", expected=1),
            command_output_contains("whoami", "root"),
            agent_result_matches("df -h"),
            agent_result_matches("df -h", match="exact_line_containing", match_key="/"),
        ]
        for spec in specs:
            with self.subTest(spec=spec):
                validate_spec(spec)  # must not raise

    def test_constructors_omit_absent_optionals(self):
        # Absent optionals must not appear as explicit None -- the validator
        # rejects unknown/empty required keys, and a stray None invites bugs.
        self.assertNotIn("min_bytes", file_exists("/tmp/x"))
        self.assertNotIn("match_key", agent_result_matches("df"))

    def test_exit_code_default_is_zero(self):
        self.assertEqual(command_exit_code("true")["expected_exit_code"], 0)


class TestResult(unittest.TestCase):
    def test_truthiness_follows_passed(self):
        self.assertTrue(Result(True, "", {}, "", ""))
        self.assertFalse(Result(False, "", {}, "", ""))

    def test_raise_for_status(self):
        Result(True, "fine", {}, "", "").raise_for_status()  # must not raise
        with self.assertRaises(VerificationFailed):
            Result(False, "nope", {}, "", "").raise_for_status()

    def test_failed_result_carries_the_evidence(self):
        # "it failed" is not actionable on its own. The command and the raw
        # output are what you actually need at 3am.
        check = verify(command_exit_code("false"))
        self.assertFalse(check)
        self.assertIn("false", check.command)
        self.assertIn("PROBE_EXIT_CODE", check.output)


class TestVerifyEndToEnd(unittest.TestCase):
    """Real subprocess execution through the default local() executor."""

    def test_exit_code_pass_and_fail(self):
        self.assertTrue(verify(command_exit_code("true")))
        self.assertFalse(verify(command_exit_code("false")))

    def test_nonzero_expectation(self):
        self.assertTrue(verify(command_exit_code("(exit 3)", expected=3)))
        self.assertFalse(verify(command_exit_code("(exit 3)", expected=0)))

    def test_exit_code_is_not_substring_matched(self):
        # Regression: "PROBE_EXIT_CODE:1" is a substring of
        # "PROBE_EXIT_CODE:10", so a substring check passed on the wrong code.
        check = verify(command_exit_code("(exit 10)", expected=1))
        self.assertFalse(check, "expecting 1 must not pass on an actual 10")
        self.assertIn("10", check.detail)

    def test_file_exists_on_something_real(self):
        self.assertTrue(verify(file_exists("/etc/hostname")))
        self.assertFalse(verify(file_exists("/tmp/attested-definitely-absent-zzz")))

    def test_output_contains(self):
        self.assertTrue(verify(command_output_contains("echo READY", "READY")))
        self.assertFalse(verify(command_output_contains("echo READY", "STEADY")))

    def test_agent_claim_compared_against_ground_truth(self):
        spec = agent_result_matches("echo 42G")
        self.assertTrue(verify(spec, agent_result="42G"))
        check = verify(spec, agent_result="500G")
        self.assertFalse(check)
        self.assertIn("42G", check.detail)
        self.assertIn("500G", check.detail)


class TestFailsClosed(unittest.TestCase):
    """Every ambiguous situation must resolve to 'not verified'.

    A checker that passes when the probe produced nothing is worse than no
    checker: it manufactures confidence.
    """

    def test_empty_probe_output_never_passes(self):
        for spec in (
            file_exists("/tmp/x"),
            command_output_contains("whoami", "root"),
            command_exit_code("true"),
            file_checksum("/tmp/x", HASH_A),
            agent_result_matches("df"),
        ):
            with self.subTest(type=spec["type"]):
                check = verify(spec, executor=returns(""))
                self.assertFalse(check, "empty output must never verify anything")

    def test_whitespace_only_output_never_passes(self):
        check = verify(file_exists("/tmp/x"), executor=returns("   \n\t "))
        self.assertFalse(check)

    def test_executor_that_raises_is_a_failed_check_not_an_exception(self):
        # A caller deciding retry-vs-escalate should hear "not verified",
        # not catch a traceback from somewhere inside the verifier.
        check = verify(command_exit_code("true"), executor=raises(OSError("boom")))
        self.assertFalse(check)
        self.assertIn("could not be executed", check.detail)

    def test_timeout_is_a_failed_check(self):
        check = verify(
            command_exit_code("true"),
            executor=raises(subprocess.TimeoutExpired(cmd="x", timeout=1)),
        )
        self.assertFalse(check)
        self.assertIn("timed out", check.detail)

    def test_garbage_output_does_not_confirm_a_file(self):
        # Output that is neither an ls listing nor a known error is not
        # evidence. Previously anything lacking "No such file" passed.
        check = verify(file_exists("/tmp/x"), executor=returns("ok"))
        self.assertFalse(check)

    def test_agent_silence_is_not_agreement(self):
        # "" == "" used to count as the agent's claim matching ground truth.
        check = verify(agent_result_matches("echo x"), executor=returns("x"), agent_result="")
        self.assertFalse(check)


class TestSpecValidation(unittest.TestCase):
    """Malformed specs are errors, never silent reinterpretation."""

    def test_unknown_key_is_rejected_by_name(self):
        # Writing 'expected' instead of 'expected_exit_code' used to make the
        # gate quietly check for 0. It was correct by luck, which is why it
        # survived in a real test harness for months.
        check = verify({"type": "command_exit_code", "command": "false", "expected": 1})
        self.assertFalse(check)
        self.assertIn("expected", check.detail)
        self.assertIn("expected_exit_code", check.detail)

    def test_missing_required_key_is_named(self):
        check = verify({"type": "command_output_contains", "command": "whoami"})
        self.assertFalse(check)
        self.assertIn("expected", check.detail)

    def test_empty_required_value_rejected(self):
        with self.assertRaises(SpecError):
            validate_spec({"type": "command_output_contains", "command": "x", "expected": ""})

    def test_unknown_type_rejected(self):
        with self.assertRaises(SpecError):
            validate_spec({"type": "vibes_check", "command": "x"})
        self.assertFalse(verify({"type": "vibes_check"}))

    def test_unknown_match_strategy_rejected(self):
        with self.assertRaises(SpecError):
            validate_spec({"type": "agent_result_matches_probe", "command": "df",
                           "match": "fuzzy"})

    def test_line_match_requires_match_key(self):
        with self.assertRaises(SpecError):
            validate_spec({"type": "agent_result_matches_probe", "command": "df",
                           "match": "exact_line_containing"})

    def test_non_integer_exit_code_rejected(self):
        with self.assertRaises(SpecError):
            validate_spec({"type": "command_exit_code", "command": "x",
                           "expected_exit_code": "zero"})

    def test_invalid_spec_is_a_failed_check_not_a_crash(self):
        check = verify({"type": "nonsense"})
        self.assertFalse(check)
        self.assertEqual(check.command, "")


class TestBuildRawCommand(unittest.TestCase):
    def test_commands_are_literal(self):
        self.assertEqual(build_raw_command(command_output_contains("echo hi", "hi")), "echo hi")
        self.assertIn("sha256sum", build_raw_command(file_checksum("/tmp/x", HASH_A)))
        self.assertTrue(build_raw_command(file_exists("/tmp/x")).startswith("ls "))
        self.assertIn("PROBE_EXIT_CODE:$?", build_raw_command(command_exit_code("true")))


class TestChecksumEvaluation(unittest.TestCase):
    def test_match_and_mismatch(self):
        spec = file_checksum("/tmp/x", HASH_A)
        self.assertTrue(evaluate_probe_result(spec, "%s  /tmp/x" % HASH_A)[0])
        self.assertFalse(evaluate_probe_result(spec, "%s  /tmp/x" % HASH_B)[0])

    def test_case_insensitive(self):
        spec = file_checksum("/tmp/x", HASH_A.upper())
        self.assertTrue(evaluate_probe_result(spec, "%s  /tmp/x" % HASH_A)[0])

    def test_missing_file(self):
        spec = file_checksum("/tmp/x", HASH_A)
        passed, detail = evaluate_probe_result(
            spec, "sha256sum: /tmp/x: No such file or directory"
        )
        self.assertFalse(passed)
        self.assertIn("/tmp/x", detail)


class TestExecutors(unittest.TestCase):
    def test_local_combines_stdout_and_stderr(self):
        # The evidence is often on stderr -- "No such file or directory" is
        # the canonical case -- so an executor that drops it blinds the gate.
        run = local()
        self.assertIn("out", run("echo out"))
        self.assertIn("err", run("echo err 1>&2"))

    def test_local_enforces_a_timeout(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            local(timeout=0.5)("sleep 5")

    def test_custom_executor_is_used(self):
        seen = []

        def spy(command: str) -> str:
            seen.append(command)
            return "PROBE_EXIT_CODE:0"

        self.assertTrue(verify(command_exit_code("whatever"), executor=spy))
        self.assertEqual(len(seen), 1)
        self.assertIn("whatever", seen[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
