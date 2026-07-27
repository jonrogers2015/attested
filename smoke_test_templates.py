"""Smoke test for attested.templates -- run directly, not via pytest,
so results are unambiguous stdout for the verification gate to check."""
import sys
sys.path.insert(0, "/root/attested")

from attested import verify
from attested._gate import SpecError
from attested.templates import (
    safe_file_exists,
    safe_file_checksum,
    safe_command_output_contains,
    safe_command_exit_code,
    safe_agent_result_matches,
    roundtrip_checksum_spec,
)

failures = []

def check(name, condition):
    if condition:
        print(f"PASS {name}")
    else:
        print(f"FAIL {name}")
        failures.append(name)

# --- safe_file_exists ---
try:
    safe_file_exists("/tmp/whatever", min_bytes=0)
    check("file_exists rejects min_bytes=0", False)
except SpecError:
    check("file_exists rejects min_bytes=0", True)

spec = safe_file_exists("/etc/hostname", min_bytes=1)
result = verify(spec)
check("file_exists happy path verifies", bool(result))

# --- safe_file_checksum ---
try:
    safe_file_checksum("/tmp/x", "")
    check("file_checksum rejects empty hash", False)
except SpecError:
    check("file_checksum rejects empty hash", True)

try:
    safe_file_checksum("/tmp/x", "not-a-hash")
    check("file_checksum rejects malformed hash", False)
except SpecError:
    check("file_checksum rejects malformed hash", True)

try:
    safe_file_checksum("/tmp/x", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
    check("file_checksum rejects empty-file hash", False)
except SpecError:
    check("file_checksum rejects empty-file hash", True)

import hashlib
with open("/tmp/templates-smoke-realfile.txt", "w") as f:
    f.write("real content\n")
real_hash = hashlib.sha256(open("/tmp/templates-smoke-realfile.txt", "rb").read()).hexdigest()
spec = safe_file_checksum("/tmp/templates-smoke-realfile.txt", real_hash)
result = verify(spec)
check("file_checksum happy path verifies", bool(result))

# --- safe_command_output_contains ---
try:
    safe_command_output_contains("echo hi", "")
    check("command_output_contains rejects empty expected", False)
except SpecError:
    check("command_output_contains rejects empty expected", True)

try:
    safe_command_output_contains("echo hi", "   ")
    check("command_output_contains rejects whitespace expected", False)
except SpecError:
    check("command_output_contains rejects whitespace expected", True)

spec = safe_command_output_contains("echo helmward-templates-ok", "helmward-templates-ok")
result = verify(spec)
check("command_output_contains happy path verifies", bool(result))

# --- safe_command_exit_code ---
try:
    safe_command_exit_code("true", expected="0")
    check("command_exit_code rejects non-int expected", False)
except SpecError:
    check("command_exit_code rejects non-int expected", True)

try:
    safe_command_exit_code("true", expected=True)
    check("command_exit_code rejects bool expected", False)
except SpecError:
    check("command_exit_code rejects bool expected", True)

spec = safe_command_exit_code("true", expected=0)
result = verify(spec)
check("command_exit_code happy path verifies", bool(result))

# --- safe_agent_result_matches ---
try:
    safe_agent_result_matches("echo hi", match="bogus_mode")
    check("agent_result_matches rejects unknown match mode", False)
except SpecError:
    check("agent_result_matches rejects unknown match mode", True)

try:
    safe_agent_result_matches("echo hi", match="exact_line_containing", match_key=None)
    check("agent_result_matches requires match_key for exact_line_containing", False)
except SpecError:
    check("agent_result_matches requires match_key for exact_line_containing", True)

spec = safe_agent_result_matches("echo helmward-agent-check")
result = verify(spec, agent_result="helmward-agent-check")
check("agent_result_matches happy path verifies", bool(result))

# --- roundtrip_checksum_spec ---
try:
    roundtrip_checksum_spec(
        write_command="echo x > /tmp/a.txt",
        check_path="/tmp/b.txt",
        expected_sha256=real_hash,
    )
    check("roundtrip_checksum_spec rejects path mismatch", False)
except SpecError:
    check("roundtrip_checksum_spec rejects path mismatch", True)

spec = roundtrip_checksum_spec(
    write_command="cat /tmp/templates-smoke-realfile.txt > /tmp/templates-smoke-realfile.txt",
    check_path="/tmp/templates-smoke-realfile.txt",
    expected_sha256=real_hash,
)
result = verify(spec)
check("roundtrip_checksum_spec happy path verifies", bool(result))

print()
if failures:
    print(f"SMOKE_TEST_RESULT: FAIL ({len(failures)} failures: {failures})")
    sys.exit(1)
else:
    print("SMOKE_TEST_RESULT: ALL_PASS")
    sys.exit(0)
