"""COMPARISON.md is compiled, never authored: byte-deterministic output
from fixture bundles regardless of discovery order, INCOMPLETE derived from
the verdicts, a missing family field read as the founding intervals family,
and the committed file must equal a fresh compile — the same freshness gate
CI enforces with `git diff --exit-code`.
"""

import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from certlab.compare import compile_comparison

_V_FIXED = {"task_id": "t", "fixed": True, "failure_mode": ""}
_V_UNFIXED = {"task_id": "t", "fixed": False,
              "failure_mode": "fix-did-not-pass-suite"}
_V_UNAVAILABLE = {"task_id": "t", "fixed": False,
                  "failure_mode": "agent-unavailable"}


def _write(root, name, agent_id, verdicts, family=None, commit="abc1234"):
    b = {"schema": 1, "agent_id": agent_id, "agent_kind": "real",
         "harness_commit": commit, "verdicts": verdicts}
    if family is not None:
        b["family"] = family
    d = root / name
    d.mkdir(parents=True)
    (d / "bundle.json").write_text(json.dumps(b))


def _fixture(root):
    # written in an order that is neither alphabetical nor the sorted-row
    # order, so determinism is earned by the compiler, not the filesystem
    _write(root, "zz-aider-ledger-ci-99", "aider-headless",
           [_V_FIXED, _V_UNFIXED], family="ledger", commit="beef001")
    _write(root, "claude-code-2026-01-02", "claude-code-headless",
           [_V_FIXED, _V_FIXED])   # pre-family: no family field
    _write(root, "aa-outage-2026-03-04", "claude-code-headless",
           [_V_UNAVAILABLE, _V_FIXED], family="intervals", commit="dead002")


def test_fixture_bundles_compile_deterministically(tmp_path):
    _fixture(tmp_path)
    out = compile_comparison(tmp_path)
    assert out == compile_comparison(tmp_path)   # stable across compiles
    rows = [ln for ln in out.splitlines() if ln.startswith("| [")]
    assert rows == [
        "| [zz-aider-ledger-ci-99](certifications/zz-aider-ledger-ci-99/"
        "CONTRACT.md) | aider-headless | ledger | — | 1/2 "
        "| fix-did-not-pass-suite | `beef001` |  |",
        "| [aa-outage-2026-03-04](certifications/aa-outage-2026-03-04/"
        "CONTRACT.md) | claude-code-headless | intervals | 2026-03-04 | 1/2 "
        "| agent-unavailable | `dead002` | INCOMPLETE |",
        "| [claude-code-2026-01-02](certifications/claude-code-2026-01-02/"
        "CONTRACT.md) | claude-code-headless | intervals | 2026-01-02 | 2/2 "
        "| — | `abc1234` |  |",
    ]   # sorted by (agent, family, run name) — never directory order


def test_missing_family_field_reads_as_intervals(tmp_path):
    _write(tmp_path, "legacy-2026-01-01", "claude-code-headless", [_V_FIXED])
    assert "| intervals |" in compile_comparison(tmp_path)


def test_shipped_comparison_is_fresh():
    """The committed COMPARISON.md must be exactly what the compiler emits
    from the committed bundles — hand edits and stale rows both fail here
    (and in CI via `git diff --exit-code`)."""
    committed = (REPO / "COMPARISON.md").read_text()
    assert committed == compile_comparison(REPO / "certifications")
    # one row per committed bundle, mechanically — no pinned run count
    bundles = sorted((REPO / "certifications").glob("*/bundle.json"))
    assert len(bundles) >= 2
    for b in bundles:
        assert f"| [{b.parent.name}]" in committed
