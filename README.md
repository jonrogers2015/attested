# attested

Check that work actually happened.

AI agents report success. Sometimes they are wrong — and the failure mode isn't
an exception, it's a confident summary of work that never occurred. `attested`
checks the claim against the machine, with nothing in the checking path that
could itself be confused.

```python
from attested import verify, command_exit_code

agent.run("fix the failing auth tests")

check = verify(command_exit_code("pytest tests/auth"))
if not check:
    escalate(check.detail)
```

---

## "I could write that myself in three lines"

You could. Here are four ways those three lines quietly say yes to nothing.
Every one of them was live in production code that had been running for months:

```python
"" in output                          # true for every output ever written
expected = spec.get("expected", "")   # missing key → matches everything
"EXIT:1" in "EXIT:10"                 # substring match on a number
if "No such file" not in output:      # empty output → "the file exists!"
```

None of these throw. None appear in a log. They return `True`, the dashboard
goes green, and the work was never done.

That last one is the worst: an empty probe result means the probe *didn't run* —
the worker died, the command wasn't found, the result never came back. The naive
check reads "no error message present" and reports success.

A verifier that passes when nothing was verified is worse than no verifier at
all, because it manufactures confidence. So:

**`attested` fails closed.** Empty output, malformed spec, unknown key, timeout,
unparseable result — every ambiguous case resolves to *not verified*, with a
reason you can act on.

---

## Install

```
pip install attested
```

No dependencies. Standard library only, and it stays that way — a component
whose job is to be trusted shouldn't ask you to audit a dependency tree.

---

## Use

```python
from attested import verify, command_exit_code, file_checksum, file_exists

verify(command_exit_code("pytest tests/auth"))
verify(file_exists("/app/config.yml", min_bytes=100))
verify(file_checksum("/app/config.yml", sha256=expected_hash))
```

Every call returns a `Result`:

```python
check = verify(command_exit_code("pytest"))

bool(check)          # True if it passed — so `if not check:` reads naturally
check.detail         # why, in words
check.command        # what actually ran
check.output         # what actually came back
check.raise_for_status()   # raise VerificationFailed instead, if you prefer
```

`verify()` never raises on a failed check. Most callers are deciding whether to
retry or escalate, and control flow reads better than exception handling for
that. A timeout or an executor that can't run is a **failed check**, not an
escaped exception — a probe that didn't finish hasn't confirmed anything.

---

## Catching a plausible lie

Checking that reality is fine is one thing. Checking that the agent's *claim*
matches reality is the interesting one:

```python
from attested import verify, agent_result_matches

claim = agent.run("how much disk is free on /?")

check = verify(agent_result_matches("df -h / | tail -1"), agent_result=claim)
```

```
FAIL: probe: '42G' | agent claimed: '500G'
```

This exists because substring checks false-pass on fabrications. A completely
invented `df` table still contains a `/`. Comparing the claim against ground
truth doesn't have that hole.

---

## Where the probe runs is the whole game

`verify()` takes an executor — any callable that runs a shell command and
returns its output. The default runs locally:

```python
from attested import verify, ssh, command_exit_code

verify(command_exit_code("systemctl is-active nginx"), executor=ssh("web-01"))

verify(command_exit_code("pytest"), executor=my_container_exec)
```

**The one rule: the executor must not run inside the thing being verified.**
If you ask an agent to confirm its own work, you've rebuilt the problem this
package exists to solve. A separate process is the minimum; separate hardware
is better when the claim is about hardware.

An executor is just `Callable[[str], str]`, so wiring up Docker, a git worktree,
or a remote runner is a few lines.

---

## Checks

| Check | Confirms | Strength |
|---|---|---|
| `command_exit_code(cmd, expected=0)` | the command exited with that status | strong |
| `file_checksum(path, sha256)` | contents hash exactly | strongest |
| `file_exists(path, min_bytes=None)` | file present, optionally non-trivial | moderate |
| `agent_result_matches(cmd)` | the agent's claim equals ground truth | strong |
| `command_output_contains(cmd, expected)` | output contains a string | weak |

`command_output_contains` is documented as weak on purpose. A fabricated output
can contain the expected token by coincidence. Reach for `command_exit_code` or
`file_checksum` when the answer matters.

Specs are plain dicts, so they can live in a database column, travel over a
queue, or sit in a config file. The constructors are ergonomics on top of that
format — `verify()` accepts either.

```python
verify({"type": "command_exit_code", "command": "pytest", "expected_exit_code": 0})
```

Malformed specs are rejected by name, not silently reinterpreted:

```
FAIL: invalid spec: unknown key(s) 'expected' for type 'command_exit_code';
allowed: command, expected_exit_code. A misspelled key is not ignored here --
it would silently change what gets checked.
```

That specific typo shipped in a real test harness and made the gate quietly
check for exit code 0. It was correct by luck, which is exactly why it survived.

---

## Status

`0.0.1`. The API above is what exists and works, with a test suite covering the
evaluation logic including every failure mode described here.

It's early. The spec format and executor signature may still move before `0.1`.
If you use it and something is awkward, that's worth an issue — the shape is
still cheap to change.

Extracted from Helmward, a self-hosted agent orchestrator, where
this logic gates whether agent tasks are allowed to be marked done.

MIT.
