"""VAC emitter: every certification directory is also a Capability Evidence
Bundle (vac-protocol SPEC.md v0.1) — vac.json is computed entirely from the
committed bundle.json plus git history, so the directory verifies offline
under `python -m vac.verify` and replays under `python -m certlab.regrade`
at a pinned commit.

Additive by construction: bundle.json and CONTRACT.md are read and hashed,
never written, and every emitted field derives from bundle content, static
protocol facts, or commit hashes — no wall clock anywhere, so re-emission
is byte-identical (the COMPARISON.md freshness discipline, applied to the
manifest itself).

The earliest bundles predate their own regrader: for those the replay block
checks out the commit that INTRODUCED certlab/regrade.py instead of the
(stamp-bound) issuer_commit — honest because regrade refuses any bundle
whose task-set hashes drifted, so a consistent report at the later commit
still binds the verdicts to the byte-identical pinned family. Both recipes
were executed against real clones before this emitter shipped them.

`python -m certlab.vac [cert-dir ...]` — no arguments (re)emits vac.json
into every committed certifications/*/ directory.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys

ISSUER = "egnaro9/agent-certlab"   # SPEC 2.3: plain owner/name

_CONTROL_POLICY = (
    "constructed calibration agents gate every certification "
    "(tests/test_wedge_calibration.py): null fixes 0, oracle fixes all, "
    "test-deleter is failed by POLICY despite green pytest, forbidden-file "
    "is failed by the allowed-paths layer, unavailable reads "
    "agent-unavailable — a wedge that cannot separate them certifies "
    "nothing")

# the contract's "Conditions and limits" non-claims, as explicit limitations
_LIMITATIONS = (
    "grading reads on-disk artifacts only; the agent's self-report is "
    "never consulted",
    "covers exactly the task family pinned by protocol.hashes and says "
    "nothing beyond it — no cross-family or open-world capability is "
    "claimed",
    "replay re-earns the GRADING, not the agent run: verdicts are "
    "recomputed from issued hashes plus recorded diffs without re-running "
    "any agent")

# the contract's conditions sentence, as the claim's scope
_SCOPE = (
    "exactly the task family named by its hash — defects seeded into that "
    "family's sources (a coordinated defect spans several files), with its "
    "untouched test suite as the complete specification — and nothing "
    "beyond it")


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _replay_commit(repo: pathlib.Path, harness_commit: str) -> str:
    """The commit the replay block checks out: harness_commit when the
    regrader exists there, else the commit that introduced it (see the
    module docstring for why that stays honest)."""
    probe = subprocess.run(
        ["git", "cat-file", "-e", f"{harness_commit}:certlab/regrade.py"],
        cwd=repo, capture_output=True)
    if probe.returncode == 0:
        return harness_commit
    first = subprocess.run(
        ["git", "log", "--reverse", "--format=%h", "--abbrev=7", "--",
         "certlab/regrade.py"],
        cwd=repo, capture_output=True, text=True, check=True)
    return first.stdout.split()[0]


_ARTIFACT = "bundle.json"   # the check's PRIMARY evidence ref; VAC 2.5.1
                            # derives this bundle's scope from its filename


def vac_manifest(cert_dir: pathlib.Path) -> dict:
    """The vac.json content for one certification directory — a pure
    function of bundle.json bytes plus git history; never writes."""
    repo = pathlib.Path(__file__).resolve().parents[1]
    bundle = json.loads((cert_dir / "bundle.json").read_text())
    vs = bundle["verdicts"]
    n, fixed = len(vs), sum(1 for v in vs if v["fixed"])
    modes: dict[str, int] = {}
    for mode in sorted(x["failure_mode"] for x in vs if x["failure_mode"]):
        modes[mode] = modes.get(mode, 0) + 1
    # VAC 2.5.1: at vac_version 0.2 a summary number binds on its FULL path
    # beneath `summary.`, against a pool keyed <scope>.<field>, where scope is
    # DERIVED by the verifier from this check's primary evidence filename.
    # Deriving it here from the same literal keeps the two from drifting: if
    # _ARTIFACT is ever renamed, the summary follows it.
    scope = _ARTIFACT.split(".")[0]
    recomputed = {"verdicts": n, "fixed": fixed,
                  "policy_ok": sum(1 for v in vs if v["policy_ok"]),
                  "tests_ok": sum(1 for v in vs if v["tests_ok"])}
    # A failure_mode is issuer free text, and SPEC 3.1 withholds one whose
    # name collides with a recomputed field so issuer text cannot redefine
    # what `fixed` is held to. Flattened into the scope object, a collision
    # would also silently OVERWRITE the real value here, so refuse instead of
    # emitting a bundle whose headline is not what it appears to be.
    clash = sorted(set(modes) & set(recomputed))
    if clash:
        raise ValueError(
            f"{cert_dir.name}: failure_mode {clash} collides with a "
            "recomputed field name. VAC 3.1 withholds such a mode from the "
            "pool, so this summary key would bind to the recomputed value "
            "rather than the mode count. Rename the mode in the harness.")
    family = bundle.get("family", "intervals")   # pre-family bundles
    commit = bundle["harness_commit"]
    replay_at = _replay_commit(repo, commit)
    limitations = list(_LIMITATIONS)
    if modes.get("agent-unavailable"):
        limitations.append(
            f"INCOMPLETE: {modes['agent-unavailable']} verdict(s) are "
            "agent-unavailable — the agent never executed; infrastructure "
            "failures, not capability findings")
    expected = (f"exit 0; regrade reports 'consistent — {n}/{n} verdicts "
                "recomputed identical'")
    if replay_at != commit:
        expected += (
            f" ({replay_at} is the commit that introduced the regrader — "
            f"it postdates issuer_commit {commit}, and regrade refuses any "
            "bundle whose task-set hashes drifted, so a consistent report "
            "still binds these verdicts to the byte-identical pinned "
            "family)")
    return {
        "vac_version": "0.2",
        "claim": {
            "capability": (f"repair-seeded-defects:{family} — "
                           f"{bundle['agent_id']} fixed {fixed}/{n} seeded "
                           "defects under policy"),
            "scope": _SCOPE,
            "limitations": limitations,
        },
        "subject": {
            "kind": "agent",
            "id": bundle["agent_id"],
            "version": {"model": bundle.get("model"),
                        "harness_commit": commit,
                        "python": bundle["env"]["python"]},
        },
        "protocol": {
            "issuer": ISSUER,
            "issuer_commit": commit,
            "task": family,
            "hashes": {"taskset_hash": bundle["taskset_hash"],
                       "prompt_hash": bundle["prompt_hash"]},
            "grading": bundle["grading"],
            "control_policy": _CONTROL_POLICY,
        },
        # the bundle is CLOSED: every sibling of vac.json is listed + hashed
        "evidence": [
            {"path": p.relative_to(cert_dir).as_posix(),
             "sha256": _sha256(p)}
            for p in sorted(cert_dir.rglob("*"))
            if p.is_file()
            and p.relative_to(cert_dir).as_posix() != "vac.json"
        ],
        "results": {
            # `tasks` was the old name for the recomputed field `verdicts`,
            # and under 0.1 it bound only through the loose tier: any value
            # equal to SOME recomputed quantity anywhere in the bundle. The
            # modes are flattened rather than nested because a 0.2 summary
            # path is exactly <scope>.<field>.
            "summary": {scope: {"verdicts": n, "fixed": fixed, **modes}},
            "checks": [{
                "profile": "certlab-bundle-v1",
                "artifact": _ARTIFACT,
                # CONTRACT.md was pinned as evidence and read by no check, so
                # the artifact a human actually reads carried a headline
                # nothing verified. `render` binds it to the verdicts.
                "render": "CONTRACT.md",
                "expect": dict(recomputed),
            }],
        },
        "replay": {
            "issuer_commit": commit,
            "commands": [
                f"git clone https://github.com/{ISSUER} issuer",
                f"git -C issuer checkout {replay_at}",
                "python -m pip install -e './issuer[test]'",
                "python -m certlab.regrade bundle.json",
            ],
            "expected": expected,
        },
    }


def write_vac(cert_dir: pathlib.Path) -> pathlib.Path:
    out = cert_dir / "vac.json"
    out.write_text(json.dumps(vac_manifest(cert_dir), indent=1) + "\n")
    return out


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    dirs = [pathlib.Path(a) for a in args] or sorted(
        p.parent for p in (pathlib.Path(__file__).resolve().parents[1]
                           / "certifications").glob("*/bundle.json"))
    if not dirs:
        print("no certification directories")
        return 0
    for d in dirs:
        print(f"wrote {write_vac(d)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
