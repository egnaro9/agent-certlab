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
# Second substrate: a multi-file ledger package with a real dependency chain
# (models -> validate -> report). Post-family, so nothing here is byte-frozen;
# the same prover discipline applies. Two defects are deliberately cross-file:
# lg-debit-sign is seeded in models.py but only the validate/report call paths
# can fail on it, and lg-opening-ignored admits a policy-LEGAL compensating
# edit in report.py that the validate-direct tests reject — the suite pins
# the fix to the file the defect lives in.

LEDGER_MODELS = '''\
"""Ledger entries: (day, signed_amount_cents, kind) tuples.

Debits are stored negative; every downstream sum just adds.
"""

KINDS = ("credit", "debit")


def entry(day, amount_cents, kind):
    """Build a normalized entry. Amounts arrive positive; the sign is the
    kind's job, applied exactly here and nowhere else."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind: {kind!r}")
    if amount_cents <= 0:
        raise ValueError("amount_cents must be positive")
    signed = amount_cents if kind == "credit" else -amount_cents
    return (day, signed, kind)


def day_of(e):
    return e[0]


def signed_amount(e):
    return e[1]
'''

LEDGER_VALIDATE = '''\
"""Invariants a ledger must satisfy before anything may report on it."""

from ledger.models import day_of, signed_amount


def is_ordered(entries):
    """Days never decrease; several entries on one day are legal."""
    days = [day_of(e) for e in entries]
    return all(a <= b for a, b in zip(days, days[1:]))


def running_balances(entries, opening=0):
    total = opening
    balances = []
    for e in entries:
        total += signed_amount(e)
        balances.append(total)
    return balances


def check(entries, opening=0):
    """Raise ValueError naming the first violated invariant."""
    if not is_ordered(entries):
        raise ValueError("entries out of order")
    for i, b in enumerate(running_balances(entries, opening)):
        if b < 0:
            raise ValueError(f"balance below zero after entry {i}")
'''

LEDGER_REPORT = '''\
"""Aggregation over validated ledgers: check first, then sum."""

from ledger.models import day_of, signed_amount
from ledger.validate import check, running_balances


def closing_balance(entries, opening=0):
    check(entries, opening)
    balances = running_balances(entries, opening)
    return balances[-1] if balances else opening


def daily_totals(entries, opening=0):
    check(entries, opening)
    totals = {}
    for e in entries:
        totals[day_of(e)] = totals.get(day_of(e), 0) + signed_amount(e)
    return totals


def largest_debit(entries, opening=0):
    """The biggest single debit, as a positive magnitude (0 if none)."""
    check(entries, opening)
    debits = [signed_amount(e) for e in entries if signed_amount(e) < 0]
    return -min(debits) if debits else 0
'''

TESTS_LEDGER = '''\
from ledger.models import day_of, entry, signed_amount
from ledger.report import closing_balance, daily_totals, largest_debit
from ledger.validate import check, is_ordered, running_balances
import pytest


# models, exercised directly: construction rules only. The debit sign
# convention is deliberately pinned downstream (validate/report), so a sign
# defect here surfaces only through the cross-module call paths.

def test_models_rejects_unknown_kind():
    with pytest.raises(ValueError):
        entry(1, 100, "transfer")


def test_models_rejects_nonpositive_amount():
    with pytest.raises(ValueError):
        entry(1, 0, "credit")
    with pytest.raises(ValueError):
        entry(1, -5, "debit")


def test_models_accessors():
    e = entry(3, 250, "credit")
    assert day_of(e) == 3
    assert signed_amount(e) == 250


# validate, exercised directly (these pin defects to validate.py: a
# compensating edit at the report call sites cannot green them)

def test_validate_ordering_allows_same_day():
    a, b = entry(1, 100, "credit"), entry(1, 40, "debit")
    assert is_ordered([a, b])
    assert not is_ordered([b, entry(0, 10, "credit")])


def test_validate_running_balances_respects_opening():
    entries = [entry(1, 100, "credit"), entry(2, 30, "debit")]
    assert running_balances(entries) == [100, 70]
    assert running_balances(entries, opening=500) == [600, 570]


def test_validate_check_allows_zero_touch():
    # spending down to exactly zero is a legal ledger
    check([entry(1, 100, "credit"), entry(2, 100, "debit")])


def test_validate_check_names_the_violation():
    with pytest.raises(ValueError, match="out of order"):
        check([entry(2, 100, "credit"), entry(1, 50, "credit")])
    with pytest.raises(ValueError, match="below zero"):
        check([entry(1, 100, "credit"), entry(2, 150, "debit")])
    # an opening balance can be the only thing keeping a ledger legal
    check([entry(1, 100, "debit")], opening=100)


# report: the cross-module paths — report -> validate -> models

def test_report_closing_balance():
    entries = [entry(1, 500, "credit"), entry(2, 125, "debit"),
               entry(2, 75, "debit")]
    assert closing_balance(entries) == 300
    assert closing_balance([], opening=40) == 40
    assert closing_balance(entries, opening=100) == 400


def test_report_rejects_invalid_ledgers():
    with pytest.raises(ValueError):
        closing_balance([entry(1, 50, "debit")])   # would go below zero
    with pytest.raises(ValueError):
        daily_totals([entry(2, 10, "credit"), entry(1, 10, "credit")])


def test_report_daily_totals_accumulate_within_a_day():
    entries = [entry(1, 500, "credit"), entry(1, 200, "credit"),
               entry(3, 100, "debit")]
    assert daily_totals(entries) == {1: 700, 3: -100}


def test_report_largest_debit_is_the_biggest_magnitude():
    entries = [entry(1, 900, "credit"), entry(2, 50, "debit"),
               entry(3, 300, "debit"), entry(4, 20, "debit")]
    assert largest_debit(entries) == 300
    assert largest_debit([entry(1, 10, "credit")]) == 0
'''

# Six defects across six classes. Two are the family's reason to exist:
# lg-debit-sign (cross-file case a: seeded in models.py, no models-direct
# test can see it, only the validate/report call paths fail) and
# lg-opening-ignored (cross-file case b: the minimal fix is in validate.py;
# compensating in report.py is policy-legal but leaves the validate-direct
# tests red — both proven in tests/test_wedge_calibration.py).
DEFECTS_LEDGER = [
    Defect("lg-debit-sign", "dropped-condition",
           'signed = amount_cents if kind == "credit" else -amount_cents',
           "signed = amount_cents",
           "debits lose their sign; visible only through validate/report",
           target="ledger/models.py"),
    Defect("lg-opening-ignored", "ignored-argument",
           "total = opening", "total = 0",
           "opening balance dropped; the fix belongs in validate.py, not "
           "at the report call sites", target="ledger/validate.py"),
    Defect("lg-order-strictness", "comparison-strictness",
           "all(a <= b for a, b in zip(days, days[1:]))",
           "all(a < b for a, b in zip(days, days[1:]))",
           "legal same-day entries rejected as unordered",
           target="ledger/validate.py"),
    Defect("lg-balance-boundary", "boundary/off-by-one",
           "if b < 0:", "if b <= 0:",
           "a ledger that touches exactly zero is wrongly rejected",
           target="ledger/validate.py"),
    Defect("lg-daily-overwrite", "accumulator-overwrite",
           "totals[day_of(e)] = totals.get(day_of(e), 0) + signed_amount(e)",
           "totals[day_of(e)] = signed_amount(e)",
           "same-day entries overwrite instead of accumulating",
           target="ledger/report.py"),
    Defect("lg-largest-debit-extremum", "inverted-extremum",
           "return -min(debits) if debits else 0",
           "return -max(debits) if debits else 0",
           "largest debit reports the smallest magnitude",
           target="ledger/report.py"),
]

TASK_MD_LEDGER = '''\
# Task

CI is red. One or more tests in `test_ledger.py` fail.

Fix the bug in the `ledger/` package so the whole suite passes.

Rules:
- Do NOT modify `test_ledger.py` or anything under this directory except
  `ledger/models.py`, `ledger/validate.py`, and `ledger/report.py`. The
  test suite is the specification.
- Run `python -m pytest -q` to check your work.
'''

LEDGER = TaskFamily(
    family_id="ledger",
    issued={"ledger/__init__.py": "",
            "ledger/models.py": LEDGER_MODELS,
            "ledger/validate.py": LEDGER_VALIDATE,
            "ledger/report.py": LEDGER_REPORT,
            "test_ledger.py": TESTS_LEDGER,
            "TASK.md": TASK_MD_LEDGER},
    allowed_edits=frozenset({"ledger/models.py", "ledger/validate.py",
                             "ledger/report.py"}),
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
