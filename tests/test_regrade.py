"""The regrader closes the write-only-provenance gap: recorded verdicts are
re-earned from the recorded diffs, so bundle tampering stops being
undetectable by construction.

Shipped bundles must regrade consistent. A flipped verdict and an altered
diff must each be named. A bundle from another code version must be refused
explicitly — never guessed at — and that refusal is not a failure.
"""

import difflib
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from certlab.agents import OracleAgent
from certlab.regrade import apply_unified_diff, main, regrade_bundle
from certlab.tasks import CLEAN_INTERVALS, DEFECTS, INTERVALS, LEDGER, MACHINE
from certlab.wedge import certify

SHIPPED = sorted((REPO / "certifications").glob("*/bundle.json"))


def test_intervals_hashes_are_pinned_forever():
    """The shipped 2026-08-14 bundles carry exactly these two hashes and no
    family field. Any drift in CLEAN_INTERVALS, TESTS_INTERVALS, DEFECTS, or
    TASK_MD — or in the hashing that feeds them — makes those bundles
    unregradeable at this code version. Caught here, not in the field."""
    assert INTERVALS.taskset_hash() == "61eb01a1a3b34dd3"
    assert INTERVALS.prompt_hash() == "2c582137a10a5640"


def _udiff(a, b):
    return "".join(difflib.unified_diff(a.splitlines(keepends=True),
                                        b.splitlines(keepends=True),
                                        fromfile="issued/x", tofile="after/x"))


def test_applier_roundtrips_every_defect_both_directions():
    for d in DEFECTS:
        seeded = CLEAN_INTERVALS.replace(d.old, d.new, 1)
        assert apply_unified_diff(
            CLEAN_INTERVALS, _udiff(CLEAN_INTERVALS, seeded)) == seeded
        assert apply_unified_diff(
            seeded, _udiff(seeded, CLEAN_INTERVALS)) == CLEAN_INTERVALS


def test_applier_handles_multi_hunk_creation_and_deletion():
    a = "one\ntwo\nthree\nfour\nfive\nsix\nseven\neight\nnine\nten\n"
    b = "ONE\ntwo\nthree\nfour\nfive\nsix\nseven\neight\nnine\nTEN\n"
    assert apply_unified_diff(a, _udiff(a, b)) == b    # two separate hunks
    assert apply_unified_diff("", _udiff("", a)) == a  # file creation
    assert apply_unified_diff(a, _udiff(a, "")) == ""  # file deletion


def test_applier_refuses_a_diff_that_does_not_match():
    d = _udiff("alpha\nbeta\n", "alpha\nBETA\n")
    with pytest.raises(ValueError, match="does not match"):
        apply_unified_diff("alpha\ngamma\n", d)


PRE_FAMILY = {"claude-code-2026-08-14", "claude-code-cloud-2026-08-14"}


def test_shipped_bundles_regrade_consistent():
    # every committed certification, present and future — a count pin here
    # would turn each new contract into a CI failure
    assert len(SHIPPED) >= 2
    for p in SHIPPED:
        if p.parent.name in PRE_FAMILY:
            # these predate task families: no family field, read as intervals
            assert "family" not in json.loads(p.read_text())
        r = regrade_bundle(p)
        assert r.status == "consistent", (p, r.mismatches)


def _tampered(tmp_path, mutate):
    b = json.loads((REPO / "certifications" / "claude-code-2026-08-14"
                    / "bundle.json").read_text())
    mutate(b)
    p = tmp_path / "bundle.json"
    p.write_text(json.dumps(b))
    return p


def test_flipped_verdict_is_named(tmp_path):
    def flip(b):
        assert b["verdicts"][0]["task_id"] == "iv-off-by-one"
        b["verdicts"][0]["fixed"] = False
    p = _tampered(tmp_path, flip)
    r = regrade_bundle(p)
    assert r.status == "mismatch"
    assert any(m.startswith("iv-off-by-one fixed:") for m in r.mismatches)
    assert main([str(p)]) == 1


def test_altered_diff_is_named(tmp_path):
    def alter(b):  # the "fix" now reconstructs to the seeded bug itself
        v = next(x for x in b["verdicts"] if x["task_id"] == "iv-off-by-one")
        d = v["diffs"]["intervals.py"]
        assert "+    return lo <= x < hi\n" in d
        v["diffs"]["intervals.py"] = d.replace(
            "+    return lo <= x < hi\n", "+    return lo <= x <= hi\n")
    p = _tampered(tmp_path, alter)
    r = regrade_bundle(p)
    assert r.status == "mismatch"
    assert any(m.startswith("iv-off-by-one") for m in r.mismatches)
    assert main([str(p)]) == 1


def test_foreign_code_version_is_refused_not_guessed(tmp_path):
    p = _tampered(tmp_path, lambda b: b.update(taskset_hash="0" * 16))
    r = regrade_bundle(p)
    assert r.status == "stale-code"
    assert "cannot regrade at this code version" in r.detail
    assert not r.mismatches
    assert main([str(p)]) == 0


def test_explicit_intervals_family_regrades_consistent(tmp_path):
    # a new-style bundle naming its family takes the same path as a legacy one
    p = _tampered(tmp_path, lambda b: b.update(family="intervals"))
    assert regrade_bundle(p).status == "consistent"


def test_ledger_bundle_regrades_consistent_and_tampering_is_caught(tmp_path):
    """End-to-end over the multi-file family: a fresh ledger bundle (diffs
    under a subdirectory) regrades consistent, and the regrader is PROVEN
    able to fire on it — a flipped ledger verdict is named, not absorbed."""
    b = certify(OracleAgent(), LEDGER, tmp_path / "ledger-oracle")
    assert b["family"] == "ledger"
    p = tmp_path / "ledger-oracle" / "bundle.json"
    assert regrade_bundle(p).status == "consistent"
    b["verdicts"][0]["fixed"] = False
    p.write_text(json.dumps(b))
    r = regrade_bundle(p)
    assert r.status == "mismatch"
    assert any("fixed" in m for m in r.mismatches)


def test_machine_multi_edit_bundle_regrades_consistent(tmp_path):
    """The regrader over coordinated (extra_edits) defects: materialize must
    rematerialize BOTH seeded files, the oracle's two-file diffs must both
    reapply, and a flipped verdict on a coordinated task is still named."""
    b = certify(OracleAgent(), MACHINE, tmp_path / "machine-oracle")
    assert b["family"] == "machine"
    v = next(x for x in b["verdicts"] if x["task_id"] == "mc-shape-drift")
    assert sorted(v["diffs"]) == ["calc/evaluator.py", "calc/parser.py"]
    p = tmp_path / "machine-oracle" / "bundle.json"
    assert regrade_bundle(p).status == "consistent"
    v["fixed"] = False
    p.write_text(json.dumps(b))
    r = regrade_bundle(p)
    assert r.status == "mismatch"
    assert any(m.startswith("mc-shape-drift") for m in r.mismatches)


def test_agent_raw_is_carried_but_never_required(tmp_path):
    """New bundles preserve the full agent transcript per verdict
    (agent_raw); the regrader neither reads nor requires it. A bundle
    stripped of the field — the shape of every pre-raw bundle, including
    the shipped ones — regrades identically."""
    b = certify(OracleAgent(), INTERVALS, tmp_path / "raw")
    assert all("agent_raw" in v for v in b["verdicts"])
    p = tmp_path / "raw" / "bundle.json"
    assert regrade_bundle(p).status == "consistent"
    for v in b["verdicts"]:
        del v["agent_raw"]
    p.write_text(json.dumps(b))
    assert regrade_bundle(p).status == "consistent"


def test_unknown_family_is_refused_not_guessed(tmp_path):
    p = _tampered(tmp_path, lambda b: b.update(family="not-a-family"))
    r = regrade_bundle(p)
    assert r.status == "stale-code"
    assert "cannot regrade at this code version" in r.detail
    assert not r.mismatches
    assert main([str(p)]) == 0


# ---------------------------------------------------------------------------
# What the regrader never proved it compares.
#
# A mutation audit found that `_COMPARED = ("policy_ok", "tests_ok", "fixed", "failure_mode")`
# could be reduced to `("fixed",)` with all 57 tests and both CI gates green. All four tamper
# tests move the SAME field: three set verdicts[0]["fixed"]=False, and the diff-alteration
# test changes a reconstruction so that `fixed` diverges. Three of the four compared fields
# had zero tamper coverage, on the repo's central integrity claim.

@pytest.mark.parametrize("field,bad", [
    ("policy_ok", False),
    ("tests_ok", False),
    ("fixed", False),
    ("failure_mode", "tampered-with-tests"),
])
def test_every_compared_field_is_actually_compared(tmp_path, field, bad):
    """Tamper each compared field in turn and require the regrader to name THAT field.
    Reducing _COMPARED to any proper subset must fail at least one of these. The shipped
    bundle is 6/6 clean (True/True/True/''), so each `bad` value is the opposite of what is
    recorded."""
    def pick(b):
        v = b["verdicts"][0]
        assert v[field] != bad, f"fixture no longer differs on {field}"
        v[field] = bad
        pick.task = v["task_id"]
    p = _tampered(tmp_path, pick)
    r = regrade_bundle(p)
    assert r.status == "mismatch", f"a tampered {field} regraded consistent"
    assert any(m.startswith(f"{pick.task} {field}:") for m in r.mismatches), r.mismatches
    assert main([str(p)]) == 1


def test_a_bundle_that_omits_a_verdict_is_not_consistent(tmp_path):
    """`if t not in recorded` could be deleted with the suite green. Every existing round trip
    builds a COMPLETE bundle via certify and the tamper helper only edits fields in place, so
    no test ever presented an incomplete bundle. The regrade gate is what CI runs to certify
    internal honesty, and it would have passed a bundle that silently dropped a task it
    failed."""
    dropped = {}

    def drop(b):
        dropped["task_id"] = b["verdicts"].pop(0)["task_id"]
    p = _tampered(tmp_path, drop)
    r = regrade_bundle(p)
    assert r.status == "mismatch", "a bundle missing a verdict regraded consistent"
    assert any("missing verdict" in m and dropped["task_id"] in m for m in r.mismatches), \
        r.mismatches


def test_an_agent_unavailable_verdict_round_trips(tmp_path):
    """`invoked=v["failure_mode"] != "agent-unavailable"` had no coverage: no committed bundle
    carries an agent-unavailable verdict, and test_unavailable_agent_is_marked_not_scored
    checks certify's output without ever regrading.

    The failure direction is a false RED rather than a missed tamper: CI regrades every
    committed bundle, so the first honest outage bundle shipped would fail the gate and read
    as tampering.
    """
    def outage(b):
        v = b["verdicts"][0]
        v.update(failure_mode="agent-unavailable", fixed=False, policy_ok=True,
                 tests_ok=False, changed_files=[], diffs={})
    p = _tampered(tmp_path, outage)
    r = regrade_bundle(p)
    assert r.status == "consistent", (
        "an honest outage verdict must regrade clean; recomputing it with invoked=True "
        f"relabels it a capability finding: {r.mismatches}")
