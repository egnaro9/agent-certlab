"""The wedge's own certificate: it must separate the constructed agents.

null -> 0/6. oracle -> 6/6. test-deleter -> 0/6 AND every verdict names
tampered-with-tests. A wedge that cannot produce exactly this separation
must not certify anything real.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from certlab.agents import NullAgent, OracleAgent, TestDeleterAgent
from certlab.tasks import DEFECTS, prove_preconditions
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


def test_contract_names_failure_modes(tmp_path):
    b = certify(TestDeleterAgent(), tmp_path / "contract")
    text = (tmp_path / "contract" / "CONTRACT.md").read_text()
    assert "tampered-with-tests" in text
    assert "0/6" in text
