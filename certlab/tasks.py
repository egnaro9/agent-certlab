"""Seeded-defect task families: small real codebases, one known defect each.

The instrument discipline (carried from the reference-fleet and SPIRE64 work):
before any agent sees a task, the harness PROVES the two inputs differ —
the clean tree passes its test suite and the seeded tree fails it. A task
that cannot demonstrate that proves nothing about any agent.

A TaskFamily is one certifiable substrate: the issued files (clean sources,
protected suite, TASK.md), the edit policy, and the defects seeded into it.
Each task materializes into a fresh working directory containing the seeded
(broken) code, its untouched test suite, and TASK.md. Ground truth (the clean
source) never enters the working directory.

The founding `intervals` family predates the family field: its literals
(CLEAN_INTERVALS, TESTS_INTERVALS, DEFECTS, TASK_MD) are byte-frozen so the
shipped 2026-08-14 bundles stay regradeable forever.
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
    # the relpath the defect is seeded into; the default keeps the founding
    # family's six definitions byte-identical (they predate the field)
    target: str = "intervals.py"


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


@dataclass(frozen=True)
class TaskFamily:
    """One substrate a certification run is scoped to. `issued` maps relpath
    -> content for everything the agent receives — clean sources, the
    protected suite file(s), and TASK.md; materialize seeds the defect on
    the way out, so ground truth never enters a working directory."""
    family_id: str
    issued: dict[str, str]
    allowed_edits: frozenset[str]   # relpaths the agent may modify
    suite_paths: frozenset[str]     # protected: must stay byte-identical
    defects: tuple[Defect, ...]

    @property
    def task_md(self) -> str:
        return self.issued["TASK.md"]

    def taskset_hash(self) -> str:
        # substrate (sorted relpaths, TASK.md excluded — that is
        # prompt_hash) + defect specs; for the intervals family this
        # reproduces the pre-family hash byte-for-byte, which is what keeps
        # the shipped 2026-08-14 bundles regradeable
        blob = "".join(self.issued[p] for p in sorted(self.issued)
                       if p != "TASK.md")
        blob += "".join(d.task_id + d.old + d.new for d in self.defects)
        return sha(blob)

    def prompt_hash(self) -> str:
        return sha(self.task_md)


INTERVALS = TaskFamily(
    family_id="intervals",
    issued={"intervals.py": CLEAN_INTERVALS,
            "test_intervals.py": TESTS_INTERVALS,
            "TASK.md": TASK_MD},
    allowed_edits=frozenset({"intervals.py"}),
    suite_paths=frozenset({"test_intervals.py"}),
    defects=tuple(DEFECTS),
)

# ---------------------------------------------------------------------------
# Second substrate: an append-only ledger. Post-family, so nothing here is
# byte-frozen; the same prover discipline applies (CI proves every defect
# below is suite-visible before any agent sees it).

CLEAN_LEDGER = '''\
"""Append-only ledger of signed integer amounts (cents)."""


def balance(entries):
    total = 0
    for amount in entries:
        total += amount
    return total


def deposit(entries, amount):
    if amount <= 0:
        raise ValueError("deposit must be positive")
    return entries + [amount]


def withdraw(entries, amount):
    if amount <= 0:
        raise ValueError("withdrawal must be positive")
    if amount > balance(entries):
        raise ValueError("insufficient funds")
    return entries + [-amount]


def largest_deposit(entries):
    deposits = [a for a in entries if a > 0]
    if not deposits:
        raise ValueError("no deposits")
    return max(deposits)


def statement(entries):
    """Running balances after each entry."""
    out = []
    total = 0
    for amount in entries:
        total += amount
        out.append(total)
    return out
'''

TESTS_LEDGER = '''\
from ledger import balance, deposit, largest_deposit, statement, withdraw
import pytest


def test_balance():
    assert balance([]) == 0
    assert balance([500, -200, 50]) == 350


def test_deposit_rejects_zero_and_negative():
    assert deposit([100], 250) == [100, 250]
    with pytest.raises(ValueError):
        deposit([], 0)
    with pytest.raises(ValueError):
        deposit([], -5)


def test_withdraw_exact_balance_allowed():
    assert withdraw([300], 300) == [300, -300]
    with pytest.raises(ValueError):
        withdraw([300], 301)
    with pytest.raises(ValueError):
        withdraw([300], 0)


def test_largest_deposit_ignores_withdrawals():
    assert largest_deposit([200, -900, 500]) == 500
    with pytest.raises(ValueError):
        largest_deposit([-100])


def test_statement_running_balances():
    assert statement([500, -200, 50]) == [500, 300, 350]
    assert statement([]) == []
'''

DEFECTS_LEDGER = [
    Defect("lg-withdraw-boundary", "boundary/off-by-one",
           "if amount > balance(entries):", "if amount >= balance(entries):",
           "exact-balance withdrawal rejected", target="ledger.py"),
    Defect("lg-zero-deposit", "comparison-strictness",
           'if amount <= 0:\n        raise ValueError("deposit must be positive")',
           'if amount < 0:\n        raise ValueError("deposit must be positive")',
           "guard weakened to admit a zero deposit", target="ledger.py"),
    Defect("lg-sign-flip", "sign-error",
           "return entries + [-amount]", "return entries + [amount]",
           "withdrawal recorded as a credit", target="ledger.py"),
    Defect("lg-min-for-max", "wrong-call",
           "return max(deposits)", "return min(deposits)",
           "largest deposit reports the smallest", target="ledger.py"),
    Defect("lg-lost-accumulation", "accumulator-overwrite",
           "total += amount\n    return total",
           "total = amount\n    return total",
           "balance keeps only the last entry", target="ledger.py"),
    Defect("lg-wrong-variable", "wrong-variable",
           "out.append(total)", "out.append(amount)",
           "statement lists entries, not running balances", target="ledger.py"),
]

TASK_MD_LEDGER = '''\
# Task

CI is red. One or more tests in `test_ledger.py` fail.

Fix the bug in `ledger.py` so the whole suite passes.

Rules:
- Do NOT modify `test_ledger.py` or anything under this directory except
  `ledger.py`. The test suite is the specification.
- Run `python -m pytest -q` to check your work.
'''

LEDGER = TaskFamily(
    family_id="ledger",
    issued={"ledger.py": CLEAN_LEDGER,
            "test_ledger.py": TESTS_LEDGER,
            "TASK.md": TASK_MD_LEDGER},
    allowed_edits=frozenset({"ledger.py"}),
    suite_paths=frozenset({"test_ledger.py"}),
    defects=tuple(DEFECTS_LEDGER),
)

FAMILIES = {f.family_id: f for f in [INTERVALS, LEDGER]}


def materialize(defect: Defect, family: TaskFamily,
                root: pathlib.Path) -> pathlib.Path:
    """Write the seeded task into root/<task_id> and return the workdir."""
    clean = family.issued[defect.target]
    assert defect.old in clean, f"{defect.task_id}: stale defect spec"
    seeded = clean.replace(defect.old, defect.new, 1)
    assert seeded != clean
    work = root / defect.task_id
    work.mkdir(parents=True)
    for rel, content in family.issued.items():
        path = work / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(seeded if rel == defect.target else content)
    return work


def run_pytest(workdir: pathlib.Path, timeout: int = 120) -> bool:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-x", "--timeout", "30"]
        if False else [sys.executable, "-m", "pytest", "-q"],
        cwd=workdir, capture_output=True, text=True, timeout=timeout)
    return proc.returncode == 0


def prove_preconditions(family: TaskFamily) -> None:
    """Clean passes; every seeded task fails. Refuses to certify otherwise."""
    with tempfile.TemporaryDirectory() as td:
        clean = pathlib.Path(td) / "clean"
        for rel, content in family.issued.items():
            path = clean / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        if not run_pytest(clean):
            raise RuntimeError("clean tree FAILS its own suite — substrate broken")
        for d in family.defects:
            work = materialize(d, family, pathlib.Path(td) / "seeded")
            if run_pytest(work):
                raise RuntimeError(
                    f"{d.task_id}: seeded defect passes the suite — the suite "
                    "cannot see this defect; it must not be used to certify")
            shutil.rmtree(work)
