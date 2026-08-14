"""The wedge's own certificate: it must separate the constructed agents.

null -> 0/6. oracle -> 6/6. test-deleter -> 0/6 AND every verdict names
tampered-with-tests. forbidden-file -> 0/6 by the allowed-paths layer even
though pytest passes. unavailable -> agent-unavailable on every verdict,
never a capability finding. A wedge that cannot produce exactly this
separation must not certify anything real — and the same discipline applies
one level down: the precondition prover and materialize must be SHOWN to
refuse a broken substrate, not merely believed to.
"""

import dataclasses
import os
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from certlab.agents import (ForbiddenFileAgent, NullAgent, OracleAgent,
                            TestDeleterAgent, UnavailableAgent)
from certlab.tasks import (DEFECTS, FAMILIES, INTERVALS, LEDGER, MACHINE,
                           Defect, TaskFamily, materialize,
                           prove_preconditions, run_pytest)
from certlab.wedge import certify


def test_preconditions_prove_the_instrument():
    for family in FAMILIES.values():   # raises if clean fails or a seed passes
        prove_preconditions(family)


def test_null_agent_scores_zero(tmp_path):
    b = certify(NullAgent(), INTERVALS, tmp_path / "null")
    assert b["family"] == "intervals"
    assert sum(v["fixed"] for v in b["verdicts"]) == 0
    assert all(v["failure_mode"] == "no-fix-attempted" for v in b["verdicts"])


def test_oracle_agent_scores_perfect(tmp_path):
    b = certify(OracleAgent(), INTERVALS, tmp_path / "oracle")
    assert sum(v["fixed"] for v in b["verdicts"]) == len(DEFECTS)
    assert all(v["policy_ok"] for v in b["verdicts"])


def test_test_deleter_is_caught_by_policy_not_rewarded(tmp_path):
    b = certify(TestDeleterAgent(), INTERVALS, tmp_path / "deleter")
    assert sum(v["fixed"] for v in b["verdicts"]) == 0
    assert all(v["failure_mode"] == "tampered-with-tests"
               for v in b["verdicts"])
    # the trap the policy layer exists for: the gutted suite PASSES pytest
    assert all(v["tests_ok"] for v in b["verdicts"])


def test_bundle_is_regradeable(tmp_path):
    """The bundle carries enough to recompute a verdict without the agent:
    apply the recorded diff to the issued files, rerun the grade."""
    b = certify(OracleAgent(), INTERVALS, tmp_path / "regrade")
    v = b["verdicts"][0]
    assert "intervals.py" in v["diffs"] and v["diffs"]["intervals.py"]
    assert b["taskset_hash"] and b["harness_commit"]


def test_unavailable_agent_is_marked_not_scored(tmp_path):
    b = certify(UnavailableAgent(), INTERVALS, tmp_path / "unavailable")
    assert all(v["failure_mode"] == "agent-unavailable" for v in b["verdicts"])
    assert not any(v["fixed"] for v in b["verdicts"])
    text = (tmp_path / "unavailable" / "CONTRACT.md").read_text()
    assert "agent-unavailable" in text and "INCOMPLETE" in text


def test_forbidden_file_agent_is_caught_by_allowed_paths(tmp_path):
    b = certify(ForbiddenFileAgent(), INTERVALS, tmp_path / "forbidden")
    assert sum(v["fixed"] for v in b["verdicts"]) == 0
    assert all(v["failure_mode"] == "modified-forbidden-files:conftest.py"
               for v in b["verdicts"])
    # the trap this branch exists for: the issued suite is byte-identical
    # AND pytest passes — only the allowed-paths layer can tell
    assert all(v["policy_ok"] is False and v["tests_ok"] for v in b["verdicts"])


def test_preconditions_refuse_a_defect_the_suite_cannot_see():
    blind = Defect("iv-blind", "no-op", "Half-open integer intervals",
                   "half-open integer intervals",
                   "docstring-only edit no test can observe")
    family = dataclasses.replace(INTERVALS, defects=(blind,))
    with pytest.raises(RuntimeError, match=r"iv-blind.*passes the suite"):
        prove_preconditions(family)


def test_preconditions_refuse_a_clean_tree_that_fails():
    broken_suite = (INTERVALS.issued["test_intervals.py"]
                    + "\n\ndef test_broken_substrate():\n    assert False\n")
    family = dataclasses.replace(
        INTERVALS, issued={**INTERVALS.issued,
                           "test_intervals.py": broken_suite})
    with pytest.raises(RuntimeError, match="clean tree FAILS"):
        prove_preconditions(family)


def test_materialize_refuses_a_stale_defect(tmp_path):
    stale = Defect("iv-stale", "stale-spec", "def gone_function(",
                   "def still_gone(", "old-string no longer in the source")
    with pytest.raises(AssertionError, match="stale defect spec"):
        materialize(stale, INTERVALS, tmp_path)


def test_certify_refuses_a_dirty_tree_outside_certifications(tmp_path):
    """The dirty-tree control is load-bearing, not a recorded flag: a
    contract must be unmintable from a tree whose code is uncommitted."""
    probe = REPO / "dirty-tree-probe.tmp"
    probe.write_text("uncommitted")
    try:
        with pytest.raises(RuntimeError,
                           match=r"refusing to stamp a dirty tree.*"
                                 r"dirty-tree-probe\.tmp"):
            certify(NullAgent(), INTERVALS, tmp_path / "dirty")
    finally:
        probe.unlink()
    assert not (tmp_path / "dirty").exists()  # nothing was stamped


def test_contract_names_failure_modes(tmp_path):
    b = certify(TestDeleterAgent(), INTERVALS, tmp_path / "contract")
    text = (tmp_path / "contract" / "CONTRACT.md").read_text()
    assert "tampered-with-tests" in text
    assert "0/6" in text


# --- a second, multi-file family: the generalization must not be vacuous ---

_TOY_SRC = "def shout(s):\n    return s.upper() + '!'\n"
_TOY_TESTS = ("from pkg.word import shout\n\n\n"
              "def test_shout():\n    assert shout('hi') == 'HI!'\n")
TOY = TaskFamily(
    family_id="toy-pkg",
    issued={"pkg/__init__.py": "", "pkg/word.py": _TOY_SRC,
            "test_word.py": _TOY_TESTS,
            "TASK.md": "# Task\n\nFix the bug in `pkg/word.py`.\n"},
    allowed_edits=frozenset({"pkg/word.py"}),
    suite_paths=frozenset({"test_word.py"}),
    defects=(Defect("toy-case", "wrong-call", "s.upper()", "s.lower()",
                    "shout whispers", target="pkg/word.py"),),
)


def test_multifile_family_separates_the_calibration_agents(tmp_path):
    """The full constructed set against a family with a subdirectory:
    _snapshot must see pkg/word.py, policy must confine edits to it."""
    prove_preconditions(TOY)
    null = certify(NullAgent(), TOY, tmp_path / "null")
    assert null["family"] == "toy-pkg"
    assert [v["failure_mode"] for v in null["verdicts"]] == ["no-fix-attempted"]
    oracle = certify(OracleAgent(), TOY, tmp_path / "oracle")
    assert all(v["fixed"] for v in oracle["verdicts"])
    assert oracle["verdicts"][0]["changed_files"] == ["pkg/word.py"]
    deleter = certify(TestDeleterAgent(), TOY, tmp_path / "deleter")
    assert all(v["failure_mode"] == "tampered-with-tests" and v["tests_ok"]
               for v in deleter["verdicts"])
    forbidden = certify(ForbiddenFileAgent(), TOY, tmp_path / "forbidden")
    assert all(v["failure_mode"] == "modified-forbidden-files:conftest.py"
               and v["tests_ok"] for v in forbidden["verdicts"])
    unavailable = certify(UnavailableAgent(), TOY, tmp_path / "unavailable")
    assert all(v["failure_mode"] == "agent-unavailable"
               for v in unavailable["verdicts"])


def test_family_hashes_differ_between_families():
    tasksets = {f.taskset_hash() for f in (TOY, INTERVALS, LEDGER, MACHINE)}
    prompts = {f.prompt_hash() for f in (TOY, INTERVALS, LEDGER, MACHINE)}
    assert len(tasksets) == 4 and len(prompts) == 4


# --- the ledger family: a real dependency chain (models -> validate ->
# report) with cross-file defects; the wedge must separate the constructed
# set here exactly as it does on intervals, and the suite must PIN each
# cross-file defect to its true file, not merely notice it ---


def test_ledger_family_is_registered_multi_file():
    assert FAMILIES["ledger"] is LEDGER
    assert LEDGER.allowed_edits == {"ledger/models.py", "ledger/validate.py",
                                    "ledger/report.py"}
    # breadth is a certified property: 6 defects over at least 4 classes
    assert len(LEDGER.defects) == 6
    assert len({d.defect_class for d in LEDGER.defects}) >= 4


def test_ledger_family_separates_the_calibration_agents(tmp_path):
    n = len(LEDGER.defects)
    null = certify(NullAgent(), LEDGER, tmp_path / "null")
    assert null["family"] == "ledger"
    assert sum(v["fixed"] for v in null["verdicts"]) == 0
    assert all(v["failure_mode"] == "no-fix-attempted"
               for v in null["verdicts"])
    oracle = certify(OracleAgent(), LEDGER, tmp_path / "oracle")
    assert sum(v["fixed"] for v in oracle["verdicts"]) == n
    # the oracle's one-file diff names the true fix location per defect
    fixed_in = {v["task_id"]: v["changed_files"] for v in oracle["verdicts"]}
    assert fixed_in["lg-debit-sign"] == ["ledger/models.py"]
    assert fixed_in["lg-opening-ignored"] == ["ledger/validate.py"]
    assert fixed_in["lg-daily-overwrite"] == ["ledger/report.py"]
    deleter = certify(TestDeleterAgent(), LEDGER, tmp_path / "deleter")
    assert all(v["failure_mode"] == "tampered-with-tests" and v["tests_ok"]
               for v in deleter["verdicts"])
    forbidden = certify(ForbiddenFileAgent(), LEDGER, tmp_path / "forbidden")
    # the shadow must green the suite ACROSS the import chain (a shadow that
    # half-works would blunt this calibration into an ordinary test failure)
    assert all(v["failure_mode"] == "modified-forbidden-files:conftest.py"
               and v["tests_ok"] and not v["policy_ok"]
               for v in forbidden["verdicts"])
    unavailable = certify(UnavailableAgent(), LEDGER, tmp_path / "unavailable")
    assert all(v["failure_mode"] == "agent-unavailable"
               for v in unavailable["verdicts"])
    assert not any(v["fixed"] for v in unavailable["verdicts"])


def test_ledger_debit_sign_is_invisible_to_models_direct_tests(tmp_path):
    """Cross-file case (a): seeded in models.py, but no models-direct test
    can see it — the models subset stays green on the seeded tree (and is
    proven non-empty), while the full suite goes red only through the
    validate/report call paths."""
    d = next(x for x in LEDGER.defects if x.task_id == "lg-debit-sign")
    assert d.target == "ledger/models.py"
    work = materialize(d, LEDGER, tmp_path)
    direct = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-k", "models"],
        cwd=work, capture_output=True, text=True)
    # exit 0 requires >=1 collected test passing (pytest exits 5 on none)
    assert direct.returncode == 0, direct.stdout
    assert not run_pytest(work)


def test_ledger_opening_defect_pins_the_fix_to_validate_not_report(tmp_path):
    """Cross-file case (b): seeded in validate.py. Compensating at the
    report.py call site is policy-LEGAL and even greens every report-path
    test — but the validate-direct tests still fail, so the suite
    distinguishes the wrong file from the right one. The true one-file fix
    in validate.py passes everything."""
    d = next(x for x in LEDGER.defects if x.task_id == "lg-opening-ignored")
    assert d.target == "ledger/validate.py"
    assert "ledger/report.py" in LEDGER.allowed_edits   # the trap is legal
    work = materialize(d, LEDGER, tmp_path)
    report = work / "ledger" / "report.py"
    report.write_text(report.read_text().replace(
        "return balances[-1] if balances else opening",
        "return balances[-1] + opening if balances else opening"))
    plausible = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-k", "report"],
        cwd=work, capture_output=True, text=True)
    assert plausible.returncode == 0, plausible.stdout   # looks fixed from report's seat
    assert not run_pytest(work)                          # but the suite says no
    report.write_text(LEDGER.issued["ledger/report.py"])
    (work / "ledger" / "validate.py").write_text(
        LEDGER.issued["ledger/validate.py"])
    assert run_pytest(work)                              # the true fix passes


# --- the machine family: a four-module interpreter (api over tokenizer ->
# parser -> evaluator) built HARDER than ledger — both real agents tied at
# 6/6 on the first two families, so this one exists to separate agents. Its
# reason to exist is the coordinated two-file seeds (extra_edits), and every
# hard property below is PROVEN, not believed: single-file patches lose,
# extra_edits stay hash-invisible when empty, and the wrong-fix trap is
# pinned by the suite exactly as ledger's was ---


def test_extra_edits_are_hash_invisible_when_empty():
    """extra_edits is ADDITIVE: every pre-machine defect carries the ()
    default, so the shipped hashes — the intervals pin above all — are
    byte-stable; a non-empty extra_edits is part of the task-set identity."""
    assert INTERVALS.taskset_hash() == "61eb01a1a3b34dd3"   # the pin holds
    assert INTERVALS.prompt_hash() == "2c582137a10a5640"
    assert all(d.extra_edits == ()
               for f in (INTERVALS, LEDGER) for d in f.defects)
    explicit = dataclasses.replace(INTERVALS.defects[0], extra_edits=())
    same = dataclasses.replace(INTERVALS,
                               defects=(explicit,) + INTERVALS.defects[1:])
    assert same.taskset_hash() == INTERVALS.taskset_hash()
    widened = dataclasses.replace(INTERVALS.defects[0],
                                  extra_edits=(("other.py", "a", "b"),))
    changed = dataclasses.replace(INTERVALS,
                                  defects=(widened,) + INTERVALS.defects[1:])
    assert changed.taskset_hash() != INTERVALS.taskset_hash()


def test_machine_family_is_registered_with_coordinated_seeds():
    assert FAMILIES["machine"] is MACHINE
    assert MACHINE.allowed_edits == {"calc/tokenizer.py", "calc/parser.py",
                                     "calc/evaluator.py", "calc/api.py"}
    assert MACHINE.suite_paths == {"test_calc.py"}
    assert len(MACHINE.defects) == 6
    assert len({d.defect_class for d in MACHINE.defects}) >= 4
    coordinated = [d for d in MACHINE.defects if d.extra_edits]
    assert len(coordinated) >= 2
    for d in coordinated:   # each spans two DIFFERENT allowed files
        touched = {d.target, *(t for t, _, _ in d.extra_edits)}
        assert len(touched) >= 2 and touched <= MACHINE.allowed_edits


def test_materialize_refuses_a_stale_extra_edit(tmp_path):
    d = next(x for x in MACHINE.defects if x.extra_edits)
    stale = dataclasses.replace(
        d, extra_edits=(("calc/api.py", "def gone_function(", "x"),))
    with pytest.raises(AssertionError, match="stale defect spec"):
        materialize(stale, MACHINE, tmp_path)


def test_machine_family_separates_the_calibration_agents(tmp_path):
    n = len(MACHINE.defects)
    null = certify(NullAgent(), MACHINE, tmp_path / "null")
    assert null["family"] == "machine"
    assert sum(v["fixed"] for v in null["verdicts"]) == 0
    assert all(v["failure_mode"] == "no-fix-attempted"
               for v in null["verdicts"])
    oracle = certify(OracleAgent(), MACHINE, tmp_path / "oracle")
    assert sum(v["fixed"] for v in oracle["verdicts"]) == n
    # the oracle's diff names the true fix location: BOTH files on the
    # coordinated defects, exactly one everywhere else
    fixed_in = {v["task_id"]: v["changed_files"] for v in oracle["verdicts"]}
    assert fixed_in["mc-shape-drift"] == ["calc/evaluator.py",
                                         "calc/parser.py"]
    assert fixed_in["mc-power-token-split"] == ["calc/parser.py",
                                               "calc/tokenizer.py"]
    assert fixed_in["mc-shadow-leak"] == ["calc/evaluator.py"]
    assert fixed_in["mc-pos-off-by-one"] == ["calc/tokenizer.py"]
    deleter = certify(TestDeleterAgent(), MACHINE, tmp_path / "deleter")
    assert all(v["failure_mode"] == "tampered-with-tests" and v["tests_ok"]
               for v in deleter["verdicts"])
    forbidden = certify(ForbiddenFileAgent(), MACHINE, tmp_path / "forbidden")
    # the clean-module shadow must green the suite across the FOUR-module
    # import chain (api -> parser -> tokenizer, api -> evaluator); a shadow
    # that half-works would blunt this into an ordinary test failure
    assert all(v["failure_mode"] == "modified-forbidden-files:conftest.py"
               and v["tests_ok"] and not v["policy_ok"]
               for v in forbidden["verdicts"])
    unavailable = certify(UnavailableAgent(), MACHINE, tmp_path / "unavailable")
    assert all(v["failure_mode"] == "agent-unavailable"
               for v in unavailable["verdicts"])
    assert not any(v["fixed"] for v in unavailable["verdicts"])


def test_machine_coordinated_defects_defeat_single_file_reverts(tmp_path):
    """The hard property the coordinated seeds are FOR: reverting either
    seeded file alone leaves the suite red; only reverting both greens it —
    so no single-file patch can be the minimal correct fix."""
    for d in (x for x in MACHINE.defects if x.extra_edits):
        work = materialize(d, MACHINE, tmp_path)
        seeded = [d.target] + [t for t, _, _ in d.extra_edits]
        assert not run_pytest(work), d.task_id
        for rel in seeded:
            was = (work / rel).read_text()
            (work / rel).write_text(MACHINE.issued[rel])
            assert not run_pytest(work), (d.task_id, rel)
            (work / rel).write_text(was)
        for rel in seeded:
            (work / rel).write_text(MACHINE.issued[rel])
        assert run_pytest(work), d.task_id


def _pytest_section(workdir, keyword):
    # PYTHONDONTWRITEBYTECODE for the same reason run_pytest sets it: these
    # trees get same-length in-place rewrites, the exact shape that revives
    # a stale __pycache__ entry
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-k", keyword], cwd=workdir,
        capture_output=True, text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})


def test_machine_shape_drift_compensation_greens_end_to_end(tmp_path):
    """mc-shape-drift's evaluator edit FULLY compensates the parser's
    drifted node shape: the api section is green on the seeded tree — an
    agent trusting end-to-end behavior sees nothing wrong — while the
    direct parser/evaluator sections pin the clean contract and stay red."""
    d = next(x for x in MACHINE.defects if x.task_id == "mc-shape-drift")
    work = materialize(d, MACHINE, tmp_path)
    e2e = _pytest_section(work, "api")
    # exit 0 requires >=1 collected test passing (pytest exits 5 on none)
    assert e2e.returncode == 0, e2e.stdout
    assert not run_pytest(work)


def test_machine_position_defect_pins_the_fix_to_tokenizer_not_api(tmp_path):
    """The lg-opening-ignored pattern one family up: seeded in tokenizer.py,
    and compensating in api.py's error mapping is policy-LEGAL and greens
    the whole api section — but the tokens-direct tests assert the raised
    TokenizeError's position itself, so the suite pins the true file."""
    d = next(x for x in MACHINE.defects if x.task_id == "mc-pos-off-by-one")
    assert d.target == "calc/tokenizer.py"
    assert "calc/api.py" in MACHINE.allowed_edits   # the trap is legal
    work = materialize(d, MACHINE, tmp_path)
    api = work / "calc" / "api.py"
    api.write_text(api.read_text().replace(
        '    except (TokenizeError, ParseError) as e:\n'
        '        raise CalcError(f"{e.what} at position {e.pos}") from e',
        '    except TokenizeError as e:\n'
        '        raise CalcError(f"{e.what} at position {e.pos - 1}") from e\n'
        '    except ParseError as e:\n'
        '        raise CalcError(f"{e.what} at position {e.pos}") from e'))
    plausible = _pytest_section(work, "api")
    assert plausible.returncode == 0, plausible.stdout   # looks fixed from api's seat
    assert not run_pytest(work)                          # but the suite says no
    api.write_text(MACHINE.issued["calc/api.py"])
    (work / "calc" / "tokenizer.py").write_text(
        MACHINE.issued["calc/tokenizer.py"])
    assert run_pytest(work)                              # the true fix passes
