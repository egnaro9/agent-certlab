"""Seeded-defect tasks: small real codebases, one known defect each.

The instrument discipline (carried from the reference-fleet and SPIRE64 work):
before any agent sees a task, the harness PROVES the two inputs differ —
the clean tree passes its test suite and the seeded tree fails it. A task
that cannot demonstrate that proves nothing about any agent.

Each task materializes into a fresh working directory containing the seeded
(broken) code, its untouched test suite, and TASK.md. Ground truth (the clean
source) never enters the working directory.
"""

from __future__ import annotations

import hashlib
import pathlib
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# The substrate: one small, real module with a real test suite.

CLEAN_INTERVALS = '''\
"""Half-open integer intervals [lo, hi)."""


def length(lo, hi):
    if hi < lo:
        raise ValueError("hi must be >= lo")
    return hi - lo


def contains(lo, hi, x):
    return lo <= x < hi


def overlaps(a_lo, a_hi, b_lo, b_hi):
    return a_lo < b_hi and b_lo < a_hi


def merge(a_lo, a_hi, b_lo, b_hi):
    """Merge two overlapping or adjacent intervals."""
    if not (overlaps(a_lo, a_hi, b_lo, b_hi) or a_hi == b_lo or b_hi == a_lo):
        raise ValueError("intervals neither overlap nor touch")
    return min(a_lo, b_lo), max(a_hi, b_hi)


def clamp(lo, hi, x):
    if x < lo:
        return lo
    if x >= hi:
        return hi - 1
    return x
'''

TESTS_INTERVALS = '''\
from intervals import clamp, contains, length, merge, overlaps
import pytest


def test_length():
    assert length(2, 5) == 3
    assert length(4, 4) == 0
    with pytest.raises(ValueError):
        length(5, 2)


def test_contains_half_open():
    assert contains(2, 5, 2)
    assert contains(2, 5, 4)
    assert not contains(2, 5, 5)
    assert not contains(2, 5, 1)


def test_overlaps():
    assert overlaps(0, 5, 4, 9)
    assert not overlaps(0, 5, 5, 9)   # touching is not overlapping
    assert overlaps(3, 4, 0, 10)


def test_merge_touching_and_overlapping():
    assert merge(0, 5, 5, 9) == (0, 9)
    assert merge(0, 6, 4, 9) == (0, 9)
    with pytest.raises(ValueError):
        merge(0, 2, 5, 9)


def test_clamp():
    assert clamp(0, 10, -3) == 0
    assert clamp(0, 10, 12) == 9
    assert clamp(0, 10, 4) == 4
    assert clamp(0, 10, 10) == 9   # x == hi: the half-open boundary itself
'''


@dataclass(frozen=True)
class Defect:
    task_id: str
    defect_class: str          # the capability-contract dimension
    old: str                   # exact source substring to replace
    new: str                   # the seeded bug
    description: str           # what a reviewer would call it


# Six defects across distinct classes, all single-edit, all provably
# test-visible (the precondition prover enforces this — a defect the suite
# cannot see would certify nothing, the tellability rule again).
DEFECTS = [
    Defect("iv-off-by-one", "boundary/off-by-one",
           "return lo <= x < hi", "return lo <= x <= hi",
           "half-open interval treated as closed"),
    Defect("iv-inverted-guard", "inverted-condition",
           'if hi < lo:\n        raise ValueError("hi must be >= lo")',
           'if hi <= lo:\n        raise ValueError("hi must be >= lo")',
           "guard rejects the legal empty interval"),
    Defect("iv-overlap-strictness", "comparison-strictness",
           "return a_lo < b_hi and b_lo < a_hi",
           "return a_lo <= b_hi and b_lo <= a_hi",
           "touching intervals report as overlapping"),
    Defect("iv-swapped-args", "argument-order",
           "return min(a_lo, b_lo), max(a_hi, b_hi)",
           "return min(a_lo, b_hi), max(a_hi, b_lo)",
           "merge mixes lo/hi across intervals"),
    Defect("iv-clamp-boundary", "boundary/off-by-one",
           "if x >= hi:\n        return hi - 1", "if x > hi:\n        return hi - 1",
           "clamp lets x == hi escape the half-open range"),
    Defect("iv-dropped-branch", "dropped-condition",
           "if x < lo:\n        return lo\n    if x >= hi:",
           "if x >= hi:",
           "low-side clamp silently removed"),
]


TASK_MD = '''\
# Task

CI is red. One or more tests in `test_intervals.py` fail.

Fix the bug in `intervals.py` so the whole suite passes.

Rules:
- Do NOT modify `test_intervals.py` or anything under this directory except
  `intervals.py`. The test suite is the specification.
- Run `python -m pytest -q` to check your work.
'''


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def taskset_hash() -> str:
    blob = CLEAN_INTERVALS + TESTS_INTERVALS + "".join(
        d.task_id + d.old + d.new for d in DEFECTS)
    return sha(blob)


def materialize(defect: Defect, root: pathlib.Path) -> pathlib.Path:
    """Write the seeded task into root/<task_id> and return the workdir."""
    assert defect.old in CLEAN_INTERVALS, f"{defect.task_id}: stale defect spec"
    seeded = CLEAN_INTERVALS.replace(defect.old, defect.new, 1)
    assert seeded != CLEAN_INTERVALS
    work = root / defect.task_id
    work.mkdir(parents=True)
    (work / "intervals.py").write_text(seeded)
    (work / "test_intervals.py").write_text(TESTS_INTERVALS)
    (work / "TASK.md").write_text(TASK_MD)
    return work


def run_pytest(workdir: pathlib.Path, timeout: int = 120) -> bool:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-x", "--timeout", "30"]
        if False else [sys.executable, "-m", "pytest", "-q"],
        cwd=workdir, capture_output=True, text=True, timeout=timeout)
    return proc.returncode == 0


def prove_preconditions() -> None:
    """Clean passes; every seeded task fails. Refuses to certify otherwise."""
    with tempfile.TemporaryDirectory() as td:
        clean = pathlib.Path(td) / "clean"
        clean.mkdir()
        (clean / "intervals.py").write_text(CLEAN_INTERVALS)
        (clean / "test_intervals.py").write_text(TESTS_INTERVALS)
        if not run_pytest(clean):
            raise RuntimeError("clean tree FAILS its own suite — substrate broken")
        for d in DEFECTS:
            work = materialize(d, pathlib.Path(td) / "seeded")
            if run_pytest(work):
                raise RuntimeError(
                    f"{d.task_id}: seeded defect passes the suite — the suite "
                    "cannot see this defect; it must not be used to certify")
            shutil.rmtree(work)
