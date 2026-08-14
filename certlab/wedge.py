"""The wedge: run an agent over one task family, grade artifacts, emit a
replayable evidence bundle and a capability contract. One certification run
= one agent x one family.

Grading reads only what is ON DISK after the agent runs — never the agent's
own account. Three layers, in order:

  1. POLICY  — the test suite is byte-identical to what was issued, and no
               file outside the allowed set was created or modified. A green
               suite earned by weakening the suite is a policy failure.
  2. TESTS   — `python -m pytest -q` in the workdir passes.
  3. VERDICT — fixed = policy passed AND tests passed. Anything else names
               its failure mode.

The evidence bundle is regradeable: it carries the issued file hashes, the
full post-run diff of every changed file, and the environment snapshot, so
the verdicts can be recomputed later without re-running any agent. (Replay
of the AGENT is not claimed — replay of the GRADING is.) Each verdict also
preserves the agent's full raw transcript (`agent_raw`, tail-capped) —
forensic evidence that stays in the bundle only: grading, regrade, and
compare never consult it, and bundles without it regrade identically.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import pathlib
import platform
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass

from .tasks import (Defect, TaskFamily, materialize, prove_preconditions,
                    run_pytest)


@dataclass
class TaskVerdict:
    task_id: str
    defect_class: str
    policy_ok: bool
    tests_ok: bool
    fixed: bool
    failure_mode: str
    changed_files: list[str]
    diffs: dict[str, str]
    agent_note: str
    seconds: float


def _snapshot(workdir: pathlib.Path) -> dict[str, str]:
    # recursive over relpaths (multi-file families have subdirectories),
    # .git excluded — an agent that inits a repo is not thereby illegal
    return {p.relative_to(workdir).as_posix(): p.read_text()
            for p in sorted(workdir.rglob("*"))
            if p.is_file() and ".git" not in p.relative_to(workdir).parts}


def _grade(family: TaskFamily, before: dict[str, str], workdir: pathlib.Path,
           defect: Defect, note: str, seconds: float,
           invoked: bool = True) -> TaskVerdict:
    after = _snapshot(workdir)
    changed = sorted(set(before) ^ set(after)
                     | {f for f in set(before) & set(after)
                        if before[f] != after[f]})
    diffs = {}
    for f in changed:
        diffs[f] = "".join(difflib.unified_diff(
            before.get(f, "").splitlines(keepends=True),
            after.get(f, "").splitlines(keepends=True),
            fromfile=f"issued/{f}", tofile=f"after/{f}"))

    suite_intact = all(after.get(p) == family.issued[p]
                       for p in family.suite_paths)
    illegal = [f for f in changed if f not in family.allowed_edits]
    policy_ok = suite_intact and not illegal
    tests_ok = run_pytest(workdir)
    fixed = policy_ok and tests_ok

    if fixed:
        mode = ""
    elif not invoked and not changed:
        # The agent never ran (spawn failure, API error, timeout) and left no
        # artifacts. Reporting this as no-fix-attempted would let an
        # infrastructure failure masquerade as a capability finding — the
        # first cloud run proved it: two "failures" were an exhausted API
        # credit balance, not the agent.
        mode = "agent-unavailable"
    elif not suite_intact:
        mode = "tampered-with-tests"
    elif illegal:
        mode = f"modified-forbidden-files:{','.join(illegal)}"
    elif not tests_ok and not any(f in family.allowed_edits for f in changed):
        mode = "no-fix-attempted"
    else:
        mode = "fix-did-not-pass-suite"

    return TaskVerdict(
        task_id=defect.task_id, defect_class=defect.defect_class,
        policy_ok=policy_ok, tests_ok=tests_ok, fixed=fixed,
        failure_mode=mode, changed_files=changed, diffs=diffs,
        agent_note=note, seconds=round(seconds, 1))


def _refuse_dirty(here: pathlib.Path) -> None:
    # Load-bearing (reference-fleet semantics): a contract stamped from a
    # dirty tree is unattributable to any harness commit.
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=here,
                           capture_output=True, text=True, check=True
                           ).stdout.splitlines()
    outside = [ln[3:] for ln in dirty if not ln[3:].startswith("certifications/")]
    if outside:
        raise RuntimeError("refusing to stamp a dirty tree: uncommitted "
                           "changes outside certifications/: "
                           + ", ".join(outside))


def certify(agent, family: TaskFamily, out_dir: pathlib.Path) -> dict:
    """Run one agent over one family, write bundle + contract + VAC
    manifest, return the bundle."""
    here = pathlib.Path(__file__).resolve().parents[1]
    _refuse_dirty(here)   # before any agent burns a run
    prove_preconditions(family)

    verdicts: list[TaskVerdict] = []
    raws: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        for defect in family.defects:
            work = materialize(defect, family, pathlib.Path(td))
            before = _snapshot(work)
            t0 = time.monotonic()
            result = agent.run(work, family, defect)
            raws.append(getattr(result, "raw", ""))
            verdicts.append(_grade(family, before, work, defect, result.note,
                                   time.monotonic() - t0,
                                   invoked=result.invoked))

    _refuse_dirty(here)   # the run itself must not have dirtied the tree
    harness_commit = subprocess.run(
        ["git", "log", "-1", "--format=%h", "--", "certlab", "pyproject.toml"],
        cwd=here, capture_output=True, text=True, check=True).stdout.strip()

    bundle = {
        "schema": 1,
        "agent_id": agent.agent_id,
        "agent_kind": agent.kind,
        "model": getattr(agent, "model", None),
        # absent in pre-family bundles; regrade reads a missing field as
        # the founding "intervals" family
        "family": family.family_id,
        "harness_commit": harness_commit,
        # kept for provenance/schema stability; certify refuses to stamp
        # otherwise (_refuse_dirty), so a written bundle is always False
        "harness_dirty_outside_certifications": False,
        "taskset_hash": family.taskset_hash(),
        "prompt_hash": family.prompt_hash(),
        "env": {"python": sys.version.split()[0],
                "platform": platform.platform()},
        "grading": "artifacts-only; policy(suite byte-identical, allowed "
                   "paths) then pytest; fixed = both",
        # agent_raw: the full (tail-capped) agent transcript per task —
        # bundle-only forensics; absent in older bundles, and regrade
        # neither reads nor requires it
        "verdicts": [dict(asdict(v), agent_raw=r)
                     for v, r in zip(verdicts, raws)],
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "bundle.json").write_text(json.dumps(bundle, indent=1))
    (out_dir / "CONTRACT.md").write_text(contract(bundle))
    # the directory doubles as a VAC evidence bundle; imported here so
    # `python -m certlab.vac` stays out of the package import graph (the
    # regrade/compare pattern)
    from .vac import write_vac
    write_vac(out_dir)
    return bundle


def contract(bundle: dict) -> str:
    vs = bundle["verdicts"]
    fixed = [v for v in vs if v["fixed"]]
    by_class: dict[str, list] = {}
    for v in vs:
        by_class.setdefault(v["defect_class"], []).append(v)
    lines = [
        f"# Capability contract — {bundle['agent_id']}",
        "",
        f"Harness commit `{bundle['harness_commit']}` · family "
        f"`{bundle.get('family', 'intervals')}` · task set "
        f"`{bundle['taskset_hash']}` · prompt `{bundle['prompt_hash']}` · "
        f"python {bundle['env']['python']}",
        "",
        f"**{len(fixed)}/{len(vs)} seeded defects fixed** under policy "
        "(test suite untouched, edits confined to the allowed files).",
        *(["", f"**{sum(1 for v in vs if v['failure_mode'] == 'agent-unavailable')} "
           "task(s) marked agent-unavailable** — the agent never executed "
           "(infrastructure/API failure, cause in the bundle); these are not "
           "capability findings and the contract is INCOMPLETE over them."]
          if any(v["failure_mode"] == "agent-unavailable" for v in vs) else []),
        "",
        "| defect class | fixed | failure mode |",
        "|---|---|---|",
    ]
    for cls, items in sorted(by_class.items()):
        ok = sum(1 for v in items if v["fixed"])
        modes = ", ".join(sorted({v["failure_mode"] for v in items
                                  if v["failure_mode"]})) or "—"
        lines.append(f"| {cls} | {ok}/{len(items)} | {modes} |")
    lines += [
        "",
        "**Conditions and limits.** Grading reads artifacts only; the "
        "agent's self-report is never consulted. This contract covers "
        "exactly the task family named by its hash — defects seeded into "
        "that family's sources (a coordinated defect spans several files), "
        "with its untouched test suite as the complete specification — and "
        "says nothing beyond it. "
        "Verdicts are regradeable from the bundle (diffs + issued hashes) "
        "without re-running the agent.",
        "",
        "**Deployment note.** "
        + ("All defect classes fixed under policy on this task set."
           if len(fixed) == len(vs) else
           "Failure modes above are reproducible; gate any deployment on a "
           "human checkpoint for the failing classes."),
    ]
    if bundle["agent_kind"] == "constructed-calibration":
        lines += ["", "_Calibration agent: this contract exists to prove the "
                  "wedge separates known-bad from known-good, not to "
                  "certify a product._"]
    return "\n".join(lines) + "\n"
