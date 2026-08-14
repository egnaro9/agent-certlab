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

from certlab.regrade import apply_unified_diff, main, regrade_bundle
from certlab.tasks import CLEAN_INTERVALS, DEFECTS

SHIPPED = sorted((REPO / "certifications").glob("*/bundle.json"))


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


def test_shipped_bundles_regrade_consistent():
    assert len(SHIPPED) == 2  # claude-code + claude-code-cloud, 2026-08-14
    for p in SHIPPED:
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
