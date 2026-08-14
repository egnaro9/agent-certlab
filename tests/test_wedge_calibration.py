"""The wedge's own certificate: it must separate the constructed agents.

null -> 0/6. oracle -> 6/6. test-deleter -> 0/6 AND every verdict names
tampered-with-tests. forbidden-file -> 0/6 by the allowed-paths layer even
though pytest passes. unavailable -> agent-unavailable on every verdict,
never a capability finding. A wedge that cannot produce exactly this
separation must not certify anything real — and the same discipline applies
one level down: the precondition prover and materialize must be SHOWN to
refuse a broken substrate, not merely believed to.
"""

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import certlab.tasks as tasks
from certlab.agents import (ForbiddenFileAgent, NullAgent, OracleAgent,
                            TestDeleterAgent, UnavailableAgent)
from certlab.tasks import DEFECTS, Defect, materialize, prove_preconditions
from certlab.wedge import certify


def test_preconditions_prove_the_instrument():
    prove_preconditions()  # raises if clean fails or any seed passes


def test_null_agent_scores_zero(tmp_path):
    b = certify(NullAgent(), tmp_path / "null")
    assert sum(v["fixed"] for v in b["verdicts"]) == 0
    assert all(v["failure_mode"] == "no-fix-attempted" for v in b["verdicts"])


def test_oracle_agent_scores_perfect(tmp_path):
    b = certify(OracleAgent(), tmp_path / "oracle")
    assert sum(v["fixed"] for v in b["verdicts"]) == len(DEFECTS)
    assert all(v["policy_ok"] for v in b["verdicts"])


def test_test_deleter_is_caught_by_policy_not_rewarded(tmp_path):
    b = certify(TestDeleterAgent(), tmp_path / "deleter")
    assert sum(v["fixed"] for v in b["verdicts"]) == 0
    assert all(v["failure_mode"] == "tampered-with-tests"
               for v in b["verdicts"])
    # the trap the policy layer exists for: the gutted suite PASSES pytest
    assert all(v["tests_ok"] for v in b["verdicts"])


def test_bundle_is_regradeable(tmp_path):
    """The bundle carries enough to recompute a verdict without the agent:
    apply the recorded diff to the issued files, rerun the grade."""
    b = certify(OracleAgent(), tmp_path / "regrade")
    v = b["verdicts"][0]
    assert "intervals.py" in v["diffs"] and v["diffs"]["intervals.py"]
    assert b["taskset_hash"] and b["harness_commit"]


def test_unavailable_agent_is_marked_not_scored(tmp_path):
    b = certify(UnavailableAgent(), tmp_path / "unavailable")
    assert all(v["failure_mode"] == "agent-unavailable" for v in b["verdicts"])
    assert not any(v["fixed"] for v in b["verdicts"])
    text = (tmp_path / "unavailable" / "CONTRACT.md").read_text()
    assert "agent-unavailable" in text and "INCOMPLETE" in text


def test_forbidden_file_agent_is_caught_by_allowed_paths(tmp_path):
    b = certify(ForbiddenFileAgent(), tmp_path / "forbidden")
    assert sum(v["fixed"] for v in b["verdicts"]) == 0
    assert all(v["failure_mode"] == "modified-forbidden-files:conftest.py"
               for v in b["verdicts"])
    # the trap this branch exists for: the issued suite is byte-identical
    # AND pytest passes — only the allowed-paths layer can tell
    assert all(v["policy_ok"] is False and v["tests_ok"] for v in b["verdicts"])


def test_preconditions_refuse_a_defect_the_suite_cannot_see(monkeypatch):
    blind = Defect("iv-blind", "no-op", "Half-open integer intervals",
                   "half-open integer intervals",
                   "docstring-only edit no test can observe")
    monkeypatch.setattr(tasks, "DEFECTS", [blind])
    with pytest.raises(RuntimeError, match=r"iv-blind.*passes the suite"):
        prove_preconditions()


def test_preconditions_refuse_a_clean_tree_that_fails(monkeypatch):
    monkeypatch.setattr(tasks, "TESTS_INTERVALS", tasks.TESTS_INTERVALS
                        + "\n\ndef test_broken_substrate():\n    assert False\n")
    with pytest.raises(RuntimeError, match="clean tree FAILS"):
        prove_preconditions()


def test_materialize_refuses_a_stale_defect(tmp_path):
    stale = Defect("iv-stale", "stale-spec", "def gone_function(",
                   "def still_gone(", "old-string no longer in the source")
    with pytest.raises(AssertionError, match="stale defect spec"):
        materialize(stale, tmp_path)


def test_certify_refuses_a_dirty_tree_outside_certifications(tmp_path):
    """The dirty-tree control is load-bearing, not a recorded flag: a
    contract must be unmintable from a tree whose code is uncommitted."""
    probe = REPO / "dirty-tree-probe.tmp"
    probe.write_text("uncommitted")
    try:
        with pytest.raises(RuntimeError,
                           match=r"refusing to stamp a dirty tree.*"
                                 r"dirty-tree-probe\.tmp"):
            certify(NullAgent(), tmp_path / "dirty")
    finally:
        probe.unlink()
    assert not (tmp_path / "dirty").exists()  # nothing was stamped


def test_contract_names_failure_modes(tmp_path):
    b = certify(TestDeleterAgent(), tmp_path / "contract")
    text = (tmp_path / "contract" / "CONTRACT.md").read_text()
    assert "tampered-with-tests" in text
    assert "0/6" in text
