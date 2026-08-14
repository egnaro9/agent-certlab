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
import os
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
    # coordinated defects seed FURTHER (relpath, old, new) edits: one defect,
    # several files, so no single-file patch can be the minimal correct fix.
    # The default () keeps every single-edit family — and its taskset hash —
    # byte-identical (the pinned intervals hashes prove it).
    extra_edits: tuple[tuple[str, str, str], ...] = ()


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
        # extra_edits joins as "" when absent, so single-edit defects hash
        # exactly as they did before the field existed
        blob += "".join(d.task_id + d.old + d.new
                        + "".join(t + o + n for t, o, n in d.extra_edits)
                        for d in self.defects)
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

# ---------------------------------------------------------------------------
# Third substrate: a four-module expression interpreter (api over
# tokenizer -> parser -> evaluator). Built deliberately HARDER than ledger:
# both real agents scored 6/6 on both earlier families, so that matrix
# measures adapter discipline, not agent capability — this family exists to
# separate agents. Two defects are COORDINATED two-file seeds (extra_edits):
# mc-shape-drift drifts the parser's node shape while the evaluator FULLY
# compensates, so end-to-end stays green and only the direct sections
# object; mc-power-token-split lexes ** as two * tokens while a parser hack
# half-compensates with the wrong associativity. Either way any single-file
# patch leaves the suite red (proven in tests/test_wedge_calibration.py).
# mc-pos-off-by-one replays the lg-opening-ignored pattern one family up:
# compensating in api.py is policy-legal and greens the api section, but the
# tokens-direct tests pin the true fix to tokenizer.py.

CALC_TOKENIZER = '''\
"""Tokenizer: (kind, value, pos) triples over the calc language.

kinds: "num" (int value), "name", "let"/"in" (keywords), "op", and a final
("end", "", len(src)). pos is the 0-based offset of the token's first
character; every downstream error message names one, so positions are
contract, not decoration.
"""

KEYWORDS = ("let", "in")
OPS = "+-*/()="


class TokenizeError(Exception):
    def __init__(self, what, pos):
        super().__init__(f"{what} at position {pos}")
        self.what = what
        self.pos = pos


def tokenize(src):
    tokens = []
    i = 0
    while i < len(src):
        if src[i] == " ":
            i += 1
            continue
        start = i
        if src[i].isdigit():
            while i < len(src) and src[i].isdigit():
                i += 1
            tokens.append(("num", int(src[start:i]), start))
            continue
        if src[i].isalpha() or src[i] == "_":
            while i < len(src) and (src[i].isalnum() or src[i] == "_"):
                i += 1
            word = src[start:i]
            tokens.append((word if word in KEYWORDS else "name", word, start))
            continue
        if src.startswith("**", i):
            tokens.append(("op", "**", start))
            i += 2
            continue
        if src[i] in OPS:
            tokens.append(("op", src[i], start))
            i += 1
            continue
        raise TokenizeError(f"unexpected character {src[i]!r}", start)
    tokens.append(("end", "", len(src)))
    return tokens
'''

CALC_PARSER = '''\
"""Pratt parser: parse(text) -> nested tuples.

Node shapes are the contract between parser and evaluator (and the suite
pins them directly):

    ("num", v)  ("var", name)  ("neg", operand)
    ("bin", op, left, right)  ("let", name, bound, body)

Precedence: ** binds tightest, then unary minus, then * /, then + -.
** associates to the RIGHT (2**3**2 == 2**(3**2)); the rest to the left.
"""

from calc.tokenizer import tokenize

BP = {"+": 10, "-": 10, "*": 20, "/": 20, "**": 30}
NEG_BP = 25   # unary minus: tighter than * /, looser than **


class ParseError(Exception):
    def __init__(self, what, pos):
        super().__init__(f"{what} at position {pos}")
        self.what = what
        self.pos = pos


class _Stream:
    def __init__(self, tokens):
        self.tokens = tokens
        self.i = 0

    def peek(self):
        return self.tokens[self.i]

    def next(self):
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def expect(self, kind, value=None):
        k, v, pos = self.peek()
        if k != kind or (value is not None and v != value):
            raise ParseError(f"unexpected token {v!r}", pos)
        return self.next()


def _prefix(ts):
    kind, value, pos = ts.next()
    if kind == "num":
        return ("num", value)
    if kind == "name":
        return ("var", value)
    if kind == "let":
        _, name, _ = ts.expect("name")
        ts.expect("op", "=")
        bound = _expr(ts, 0)
        ts.expect("in")
        return ("let", name, bound, _expr(ts, 0))
    if kind == "op" and value == "-":
        return ("neg", _expr(ts, NEG_BP))
    if kind == "op" and value == "(":
        node = _expr(ts, 0)
        ts.expect("op", ")")
        return node
    if kind == "end":
        raise ParseError("unexpected end of input", pos)
    raise ParseError(f"unexpected token {value!r}", pos)


def _expr(ts, min_bp):
    node = _prefix(ts)
    while True:
        kind, value, _ = ts.peek()
        if kind != "op" or value not in BP or BP[value] < min_bp:
            break
        ts.next()
        op = value
        rhs = _expr(ts, BP[op] if op == "**" else BP[op] + 1)
        node = ("bin", op, node, rhs)
    return node


def parse(text):
    ts = _Stream(tokenize(text))
    node = _expr(ts, 0)
    kind, value, pos = ts.peek()
    if kind != "end":
        raise ParseError(f"unexpected token {value!r}", pos)
    return node
'''

CALC_EVALUATOR = '''\
"""Tree-walking evaluator over parser nodes, with lexically scoped
environments: lookup walks the parent chain; `let` binds in a fresh child
scope, never by writing into the scope it was evaluated in."""


class EvalError(Exception):
    pass


class Env:
    """A scope: local bindings plus a parent chain."""

    def __init__(self, vars=None, parent=None):
        self.vars = dict(vars or {})
        self.parent = parent

    def lookup(self, name):
        if name in self.vars:
            return self.vars[name]
        if self.parent is not None:
            return self.parent.lookup(name)
        raise EvalError(f"undefined variable: {name}")

    def child(self, name, value):
        return Env({name: value}, self)


def _apply(op, left, right):
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op == "/":
        if right == 0:
            raise EvalError("division by zero")
        return left / right
    if op == "**":
        return left ** right
    raise EvalError(f"unknown operator: {op!r}")


def evaluate(node, env):
    tag = node[0]
    if tag == "num":
        return node[1]
    if tag == "var":
        return env.lookup(node[1])
    if tag == "neg":
        return -evaluate(node[1], env)
    if tag == "bin":
        _, op, left, right = node
        return _apply(op, evaluate(left, env), evaluate(right, env))
    if tag == "let":
        _, name, bound, body = node
        return evaluate(body, env.child(name, evaluate(bound, env)))
    raise EvalError(f"unknown node: {tag!r}")
'''

CALC_API = '''\
"""Public entry point: tokenize -> parse -> evaluate, internal errors mapped
to one public CalcError whose message names what went wrong and where."""

from calc.evaluator import Env, EvalError, evaluate as _eval
from calc.parser import ParseError, parse
from calc.tokenizer import TokenizeError


class CalcError(Exception):
    pass


def evaluate(text, variables=None):
    """Evaluate `text`; `variables` seeds the root scope."""
    try:
        return _eval(parse(text), Env(variables))
    except (TokenizeError, ParseError) as e:
        raise CalcError(f"{e.what} at position {e.pos}") from e
    except EvalError as e:
        raise CalcError(str(e)) from e
'''

TESTS_CALC = '''\
from calc.api import CalcError, evaluate
from calc.evaluator import Env, EvalError, evaluate as eval_node
from calc.parser import ParseError, parse
from calc.tokenizer import TokenizeError, tokenize
import pytest


# tokens, exercised directly: kinds, values, and 0-based positions are all
# contract — positions feed every downstream error message.

def test_tokens_kinds_values_positions():
    assert tokenize("12 + x") == [("num", 12, 0), ("op", "+", 3),
                                  ("name", "x", 5), ("end", "", 6)]


def test_tokens_power_is_one_token():
    assert tokenize("2**3") == [("num", 2, 0), ("op", "**", 1),
                                ("num", 3, 3), ("end", "", 4)]


def test_tokens_keywords_are_tagged():
    assert [k for k, _, _ in tokenize("let x = 1 in x")] == [
        "let", "name", "op", "num", "in", "name", "end"]


def test_tokens_error_position_is_zero_based():
    with pytest.raises(TokenizeError) as e:
        tokenize("1 + $")
    assert e.value.pos == 4
    assert str(e.value) == "unexpected character '$' at position 4"


# parser shape: node tuples are the contract between parser and evaluator;
# these pin the CLEAN shape, so a drifted parser cannot hide behind a
# compensating evaluator (or vice versa).

def test_parser_shape_binary_and_precedence():
    assert parse("1+2") == ("bin", "+", ("num", 1), ("num", 2))
    assert parse("1+2*3") == ("bin", "+", ("num", 1),
                              ("bin", "*", ("num", 2), ("num", 3)))


def test_parser_shape_power_is_right_associative():
    assert parse("2**3**2") == ("bin", "**", ("num", 2),
                                ("bin", "**", ("num", 3), ("num", 2)))


def test_parser_shape_minus_is_left_associative():
    assert parse("8-3-2") == ("bin", "-",
                              ("bin", "-", ("num", 8), ("num", 3)),
                              ("num", 2))


def test_parser_shape_unary_minus_vs_power():
    assert parse("-2**2") == ("neg", ("bin", "**", ("num", 2), ("num", 2)))
    assert parse("-2*3") == ("bin", "*", ("neg", ("num", 2)), ("num", 3))


def test_parser_shape_let():
    assert parse("let x = 2 in x+1") == (
        "let", "x", ("num", 2), ("bin", "+", ("var", "x"), ("num", 1)))


def test_parser_error_names_token_and_position():
    with pytest.raises(ParseError) as e:
        parse("1 + )")
    assert e.value.pos == 4
    assert str(e.value) == "unexpected token ')' at position 4"


# evaluator semantics, on hand-built CLEAN-shape nodes — no parser in the
# loop, so an evaluator expecting any other shape fails here no matter what
# the parser now emits.

def test_eval_binary_nodes_directly():
    assert eval_node(("bin", "+", ("num", 2), ("num", 3)), Env()) == 5
    assert eval_node(("bin", "**", ("num", 2), ("num", 10)), Env()) == 1024


def test_eval_lookup_walks_the_scope_chain():
    inner = Env({"x": 1, "y": 9}).child("x", 2)
    assert eval_node(("var", "x"), inner) == 2     # shadowed
    assert eval_node(("var", "y"), inner) == 9     # from the parent
    with pytest.raises(EvalError, match="undefined variable: z"):
        eval_node(("var", "z"), inner)


def test_eval_let_binds_in_a_child_scope_not_by_mutation():
    env = Env({"x": 1})
    assert eval_node(("let", "x", ("num", 2), ("var", "x")), env) == 2
    assert env.vars == {"x": 1}     # the evaluated-in scope is untouched


def test_eval_division_by_zero():
    with pytest.raises(EvalError, match="division by zero"):
        eval_node(("bin", "/", ("num", 1), ("num", 0)), Env())


# api end-to-end: tokenize -> parse -> evaluate, errors mapped to CalcError
# with the exact positions the tokenizer recorded.

def test_api_arithmetic_end_to_end():
    assert evaluate("1+2*3") == 7
    assert evaluate("2**3**2") == 512
    assert evaluate("-2**2") == -4
    assert evaluate("(1+2)*3") == 9
    assert evaluate("7/2") == 3.5


def test_api_variables_and_nested_shadowing():
    assert evaluate("x*y", {"x": 3, "y": 4}) == 12
    assert evaluate("let x = 1 in (let x = 2 in x) + x") == 3
    with pytest.raises(CalcError, match="undefined variable: x"):
        evaluate("(let x = 2 in x) + x")


def test_api_error_messages_carry_exact_positions():
    with pytest.raises(CalcError) as e:
        evaluate("1 + $")
    assert str(e.value) == "unexpected character '$' at position 4"
    with pytest.raises(CalcError) as e:
        evaluate("1 + )")
    assert str(e.value) == "unexpected token ')' at position 4"


def test_api_division_by_zero_is_mapped():
    with pytest.raises(CalcError, match="division by zero"):
        evaluate("1/0")
'''

# Six defects, two of them coordinated two-file seeds. Classes stay the
# capability-contract dimension; the coordinated ones get their own.
DEFECTS_MACHINE = [
    Defect("mc-shape-drift", "coordinated/node-shape",
           'node = ("bin", op, node, rhs)',
           'node = ("bin", node, op, rhs)',
           "parser drifts the bin node shape and the evaluator fully "
           "compensates: end-to-end stays green, both direct sections go "
           "red, and no single-file patch can green the suite",
           target="calc/parser.py",
           extra_edits=(("calc/evaluator.py",
                         "_, op, left, right = node",
                         "_, left, op, right = node"),)),
    Defect("mc-power-token-split", "coordinated/token-stream",
           '        if src.startswith("**", i):\n'
           '            tokens.append(("op", "**", start))\n'
           '            i += 2\n'
           '            continue\n',
           "",
           "** lexed as two * tokens; a parser hack half-compensates but "
           "associates power to the left — the minimal fix restores both "
           "files", target="calc/tokenizer.py",
           extra_edits=(("calc/parser.py",
                         "        ts.next()\n"
                         "        op = value\n"
                         '        rhs = _expr(ts, BP[op] if op == "**" '
                         "else BP[op] + 1)",
                         "        ts.next()\n"
                         "        op = value\n"
                         '        if op == "*" and ts.peek()[:2] == '
                         '("op", "*"):\n'
                         "            ts.next()\n"
                         '            op = "**"\n'
                         "        rhs = _expr(ts, BP[op] + 1)"),)),
    Defect("mc-precedence-flat", "operator-precedence",
           '"*": 20', '"*": 10',
           "multiplication demoted to additive precedence: 1+2*3 parses as "
           "(1+2)*3", target="calc/parser.py"),
    Defect("mc-power-left-assoc", "associativity",
           'BP[op] if op == "**" else BP[op] + 1', 'BP[op] + 1',
           "power associates left: 2**3**2 becomes (2**3)**2",
           target="calc/parser.py"),
    Defect("mc-shadow-leak", "scope-leak",
           "return evaluate(body, env.child(name, evaluate(bound, env)))",
           "env.vars[name] = evaluate(bound, env)\n"
           "        return evaluate(body, env)",
           "let writes into the scope it was evaluated in instead of a "
           "child: inner bindings leak outward", target="calc/evaluator.py"),
    Defect("mc-pos-off-by-one", "boundary/off-by-one",
           'raise TokenizeError(f"unexpected character {src[i]!r}", start)',
           'raise TokenizeError(f"unexpected character {src[i]!r}", '
           "start + 1)",
           "tokenize-error position drifts one column right; compensating "
           "in api.py is policy-legal but the tokens-direct tests pin the "
           "fix to tokenizer.py", target="calc/tokenizer.py"),
]

TASK_MD_MACHINE = '''\
# Task

CI is red. One or more tests in `test_calc.py` fail.

Fix the bug in the `calc/` package so the whole suite passes.

Rules:
- Do NOT modify `test_calc.py` or anything under this directory except
  `calc/tokenizer.py`, `calc/parser.py`, `calc/evaluator.py`, and
  `calc/api.py`. The test suite is the specification.
- Run `python -m pytest -q` to check your work.
'''

MACHINE = TaskFamily(
    family_id="machine",
    issued={"calc/__init__.py": "",
            "calc/tokenizer.py": CALC_TOKENIZER,
            "calc/parser.py": CALC_PARSER,
            "calc/evaluator.py": CALC_EVALUATOR,
            "calc/api.py": CALC_API,
            "test_calc.py": TESTS_CALC,
            "TASK.md": TASK_MD_MACHINE},
    allowed_edits=frozenset({"calc/tokenizer.py", "calc/parser.py",
                             "calc/evaluator.py", "calc/api.py"}),
    suite_paths=frozenset({"test_calc.py"}),
    defects=tuple(DEFECTS_MACHINE),
)

FAMILIES = {f.family_id: f for f in [INTERVALS, LEDGER, MACHINE]}


def materialize(defect: Defect, family: TaskFamily,
                root: pathlib.Path) -> pathlib.Path:
    """Write the seeded task into root/<task_id> and return the workdir.
    Coordinated defects apply their extra_edits after the primary edit; each
    edit lands on already-seeded content, so edits may share a file."""
    seeded: dict[str, str] = {}
    for target, old, new in ((defect.target, defect.old, defect.new),
                             *defect.extra_edits):
        base = seeded.get(target, family.issued[target])
        assert old in base, f"{defect.task_id}: stale defect spec"
        seeded[target] = base.replace(old, new, 1)
        assert seeded[target] != base
    work = root / defect.task_id
    work.mkdir(parents=True)
    for rel, content in family.issued.items():
        path = work / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(seeded.get(rel, content))
    return work


def run_pytest(workdir: pathlib.Path, timeout: int = 120) -> bool:
    # The grader's pytest must not write bytecode: calibration and regrade
    # rerun it over trees whose files are rewritten in place, and a
    # same-length rewrite inside one mtime tick would revive a stale
    # __pycache__ entry — mc-shape-drift's swap-only edit is exactly that
    # shape, and a stale .pyc graded the WRONG source the first time this
    # was tried.
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=workdir, capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
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
