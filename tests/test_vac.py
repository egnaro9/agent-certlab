"""Every certification directory is also a VAC bundle: certify() emits
vac.json beside bundle.json/CONTRACT.md, computed only from committed bytes
plus git history — no wall clock, so a committed manifest must be a fresh
compile (the COMPARISON.md discipline). Where the vac-protocol sibling
checkout is present, its real verifier is the oracle, and the gate is
proven live in BOTH directions: shipped and freshly-emitted bundles PASS,
a tampered copy FAILS naming sha256-mismatch — a verifier that never fires
certifies nothing. Without the sibling, the verifier tests skip cleanly
and the structural bindings below still run.
"""

import hashlib
import importlib.util
import os
import json
import pathlib
import shutil
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from certlab.agents import OracleAgent
from certlab.tasks import INTERVALS
from certlab.vac import vac_manifest, write_vac
from certlab.wedge import certify

CERT_DIRS = sorted(p.parent
                   for p in (REPO / "certifications").glob("*/bundle.json"))
VAC_REPO = REPO.parent / "vac-protocol"
_HAVE_SIBLING = (VAC_REPO / "vac" / "verify.py").is_file()
_HAVE_INSTALLED = importlib.util.find_spec("vac") is not None
_HAVE_VERIFIER = _HAVE_SIBLING or _HAVE_INSTALLED

if os.environ.get("CI") and not _HAVE_VERIFIER:
    # Until 2026-08-17 these tests keyed ONLY on a sibling checkout, which CI
    # never had, so the three verifier-liveness tests (shipped bundles pass, a
    # fresh emission passes, a tampered copy is refused) had never once run in
    # any automated environment. The workflow's separate verify step covered
    # shipped bundles but not emission or tamper-liveness. A suite that reports
    # "all passed" with the verifier missing certifies nothing, which is the
    # exact failure mode this repo is built to detect. Fail at collection.
    raise RuntimeError(
        "no vac verifier available but CI is set: neither a vac-protocol "
        "sibling checkout nor an installed `vac` package. The verifier tests "
        "would skip and the run would read green while certifying nothing. "
        "Install it before pytest (see ci.yml) rather than skipping.")

needs_verifier = pytest.mark.skipif(
    not _HAVE_VERIFIER,
    reason="no vac verifier (sibling checkout or installed package); local "
           "dev only, absence is a hard error under CI")


def _sha256(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _verify(bundle_dir: pathlib.Path) -> subprocess.CompletedProcess:
    """The real verifier, in a subprocess with the sibling repo as cwd so
    `python -m vac.verify` resolves without installing anything."""
    cwd = VAC_REPO if _HAVE_SIBLING else REPO
    return subprocess.run(
        [sys.executable, "-m", "vac.verify", str(bundle_dir)],
        cwd=cwd, capture_output=True, text=True)


def test_committed_manifests_are_fresh_compiles():
    """Byte-reproducibility is the timestamp gate: if any emitted field
    depended on a wall clock, re-emission could not equal the commit."""
    assert CERT_DIRS   # five shipped runs and counting
    for d in CERT_DIRS:
        emitted = json.dumps(vac_manifest(d), indent=1) + "\n"
        assert (d / "vac.json").read_text() == emitted, d.name


def test_manifests_bind_to_their_bundles():
    """sha256s recomputed from disk, stamps and declared counts recomputed
    from the bundle — the manifest asserts nothing it cannot re-earn."""
    for d in CERT_DIRS:
        man = json.loads((d / "vac.json").read_text())
        bundle = json.loads((d / "bundle.json").read_text())
        listed = {e["path"]: e["sha256"] for e in man["evidence"]}
        on_disk = {p.relative_to(d).as_posix(): _sha256(p)
                   for p in sorted(d.rglob("*")) if p.is_file()}
        on_disk.pop("vac.json")
        assert listed == on_disk, d.name          # closed, and hash-true
        assert man["protocol"]["issuer_commit"] == bundle["harness_commit"]
        assert man["replay"]["issuer_commit"] == bundle["harness_commit"]
        assert man["protocol"]["hashes"] == {
            "taskset_hash": bundle["taskset_hash"],
            "prompt_hash": bundle["prompt_hash"]}
        vs = bundle["verdicts"]
        assert man["results"]["checks"][0]["expect"] == {
            "verdicts": len(vs),
            "fixed": sum(1 for v in vs if v["fixed"]),
            "policy_ok": sum(1 for v in vs if v["policy_ok"]),
            "tests_ok": sum(1 for v in vs if v["tests_ok"])}
        assert man["claim"]["limitations"]        # non-claims are mandatory


def test_replay_checkout_commit_ships_the_regrader():
    """The earliest bundles predate certlab/regrade.py; the emitter must
    point their replay at a commit where the regrader actually exists —
    a replay recipe that cannot run is a false accusation waiting."""
    for d in CERT_DIRS:
        man = json.loads((d / "vac.json").read_text())
        checkout = next(c for c in man["replay"]["commands"]
                        if c.startswith("git -C issuer checkout "))
        commit = checkout.rsplit(" ", 1)[-1]
        probe = subprocess.run(
            ["git", "cat-file", "-e", f"{commit}:certlab/regrade.py"],
            cwd=REPO, capture_output=True)
        assert probe.returncode == 0, (d.name, commit)
        # and the deviation from issuer_commit, when taken, explains itself
        if commit != man["protocol"]["issuer_commit"]:
            assert "postdates issuer_commit" in man["replay"]["expected"]


def test_certify_emits_a_manifest_beside_the_contract(tmp_path):
    b = certify(OracleAgent(), INTERVALS, tmp_path / "oracle")
    out = tmp_path / "oracle"
    man = json.loads((out / "vac.json").read_text())
    assert man["vac_version"] == "0.1"
    assert man["claim"]["capability"].startswith(
        "repair-seeded-defects:intervals")
    assert man["protocol"]["issuer_commit"] == b["harness_commit"]
    assert {e["path"] for e in man["evidence"]} == {"bundle.json",
                                                    "CONTRACT.md"}
    for e in man["evidence"]:
        assert e["sha256"] == _sha256(out / e["path"])
    assert man["results"]["checks"][0]["expect"]["fixed"] == len(b["verdicts"])
    # emission is idempotent: same inputs, same bytes
    before = (out / "vac.json").read_bytes()
    write_vac(out)
    assert (out / "vac.json").read_bytes() == before


@needs_verifier
def test_shipped_certifications_pass_the_verifier():
    for d in CERT_DIRS:
        r = _verify(d)
        assert r.returncode == 0, (d.name, r.stdout)
        assert "structural verification: PASS" in r.stdout, d.name


@needs_verifier
def test_emitted_manifest_passes_the_verifier(tmp_path):
    certify(OracleAgent(), INTERVALS, tmp_path / "oracle")
    r = _verify(tmp_path / "oracle")
    assert r.returncode == 0, r.stdout
    assert "structural verification: PASS" in r.stdout


@needs_verifier
def test_verifier_refuses_a_tampered_copy(tmp_path):
    """Liveness: the gate must be SHOWN to fire, not believed to."""
    copy = tmp_path / CERT_DIRS[0].name
    shutil.copytree(CERT_DIRS[0], copy)
    with (copy / "bundle.json").open("a") as fh:
        fh.write("\n")
    r = _verify(copy)
    assert r.returncode == 1, r.stdout
    assert "sha256-mismatch: bundle.json" in r.stdout
