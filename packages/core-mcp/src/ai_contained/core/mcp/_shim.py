#!/usr/bin/env python3
"""The Harness exec shim — the only executable in the test kernel.

Harness.exec("aws") symlinks <tmpdir>/bin/aws to this committed file, so
tests never mint executable code on writable filesystems (/tmp stays noexec;
the symlink's *target* is what the kernel permission-checks). Everything
dynamic is data:

- identity     : basename(argv[0]) — the symlink's name
- state dir    : $HARNESS_SHIM_STATE (set by Harness in the env providers inherit)
- rules        : <state>/<name>.rules.json — longest-prefix match over argv;
                 each rule's responses are consumed in order, last repeats
- call log     : <state>/<name>.calls.jsonl — argv + env per invocation

Stdlib only; runs under the python3 symlink Harness places next to it.
"""

import json
import os
import stat
import sys


def main() -> int:
    """Record this invocation, match a rule, serve its next response."""
    name = os.path.basename(sys.argv[0])
    argv = sys.argv[1:]

    if stat.S_ISFIFO(os.fstat(0).st_mode):
        sys.stdin.buffer.read()  # drain the pipe so upstream never blocks

    state_dir = os.environ.get("HARNESS_SHIM_STATE")
    if not state_dir:
        sys.stderr.write(f"{name}: HARNESS_SHIM_STATE is not set — was the Harness env passed to this spawn?\n")
        return 126
    rules_path = os.path.join(state_dir, f"{name}.rules.json")
    calls_path = os.path.join(state_dir, f"{name}.calls.jsonl")

    try:
        rules = json.load(open(rules_path))["rules"]
    except FileNotFoundError:
        rules = []

    best = None
    for rule in rules:
        prefix = rule["prefix"]
        if argv[: len(prefix)] == prefix and (best is None or len(prefix) > len(best["prefix"])):
            best = rule

    matched = best["prefix"] if best is not None else None
    served = 0
    try:
        with open(calls_path) as f:
            served = sum(1 for line in f if json.loads(line)["rule"] == matched)
    except FileNotFoundError:
        pass

    with open(calls_path, "a") as f:
        f.write(json.dumps({"argv": argv, "env": dict(os.environ), "rule": matched}) + "\n")

    if best is None:
        sys.stderr.write(f"{name}: no exec rule matches argv {argv!r}\n")
        return 127

    response = best["responses"][min(served, len(best["responses"]) - 1)]
    sys.stdout.write(response["stdout"])
    sys.stderr.write(response["stderr"])
    return int(response["exit_code"])


if __name__ == "__main__":
    sys.exit(main())
