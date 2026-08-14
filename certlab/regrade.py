"""Independent regrader: recompute every verdict in an evidence bundle from
its recorded diffs — no agent run, no trust in the recorded verdicts.

taskset_hash/prompt_hash stop being write-only provenance here. If they match
the current code, each task's issued files are rematerialized, the bundle's
unified diffs are applied to reconstruct the after-state, and the full
policy+pytest grade is recomputed and compared field-by-field against the
record; any divergence — a flipped verdict, an altered diff, a diff that no
longer applies — is named and the exit is nonzero. If the hashes do NOT
match, the bundle predates the current task set: report "cannot regrade at
this code version" explicitly and exit zero — an old bundle is not a
mismatch, and guessing is worse than refusing. Bundles are family-scoped;
a bundle with no family field predates families and is the founding
"intervals" family, and an unknown family gets the same honest refusal.

`python -m certlab.regrade [bundle.json ...]` — no arguments regrades every
committed certifications/*/bundle.json.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
import tempfile
from dataclasses import dataclass, field

from .tasks import FAMILIES, materialize
from .wedge import _grade, _snapshot

_HUNK = re.compile(r"@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")
_COMPARED = ("policy_ok", "tests_ok", "fixed", "failure_mode")


def apply_unified_diff(original: str, diff: str) -> str:
    """Apply a difflib-style unified diff (python has no stdlib applier).
    Raises ValueError on any context/deletion line that does not match the
    source — a tampered diff must never apply silently."""
    src = original.splitlines(keepends=True)
    out: list[str] = []
    pos = 0
    lines = diff.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith(("--- ", "+++ ")):
            i += 1
            continue
        m = _HUNK.match(ln)
        if not m:
            raise ValueError(f"unexpected line outside a hunk: {ln!r}")
        # a zero-length source range names the line BEFORE the insertion
        start = int(m.group(1)) - (0 if m.group(2) == "0" else 1)
        if start < pos or start > len(src):
            raise ValueError(f"hunk out of order or past EOF: {ln!r}")
        out.extend(src[pos:start])
        pos = start
        i += 1
        while i < len(lines) and not _HUNK.match(lines[i]):
            tag, body = lines[i][:1], lines[i][1:]
            if tag in (" ", "-"):
                found = src[pos] if pos < len(src) else "<EOF>"
                if pos >= len(src) or src[pos] != body:
                    raise ValueError(f"diff does not match source at line "
                                     f"{pos + 1}: expected {body!r}, "
                                     f"found {found!r}")
                if tag == " ":
                    out.append(body)
                pos += 1
            elif tag == "+":
                out.append(body)
            else:
                raise ValueError(f"unexpected diff line: {lines[i]!r}")
            i += 1
    out.extend(src[pos:])
    return "".join(out)


@dataclass
class Report:
    bundle: str
    status: str            # consistent | stale-code | mismatch
    detail: str
    mismatches: list[str] = field(default_factory=list)


def regrade_bundle(bundle_path: pathlib.Path) -> Report:
    bundle = json.loads(bundle_path.read_text())
    name = bundle_path.parent.name
    family = FAMILIES.get(bundle.get("family", "intervals"))
    if family is None:
        return Report(name, "stale-code",
                      "cannot regrade at this code version: unknown family "
                      f"{bundle.get('family')!r}")
    current = {"taskset_hash": family.taskset_hash(),
               "prompt_hash": family.prompt_hash()}
    stale = [k for k in current if bundle.get(k) != current[k]]
    if stale:
        return Report(name, "stale-code",
                      "cannot regrade at this code version: " + "; ".join(
                          f"{k} {bundle.get(k)} != current {current[k]}"
                          for k in stale))
    defects = {d.task_id: d for d in family.defects}
    recorded = {v["task_id"]: v for v in bundle["verdicts"]}
    mismatches = [f"missing verdict for {t}" for t in defects
                  if t not in recorded]
    mismatches += [f"unknown task {t}" for t in recorded if t not in defects]
    with tempfile.TemporaryDirectory() as td:
        for task_id, v in recorded.items():
            if task_id not in defects:
                continue
            work = materialize(defects[task_id], family, pathlib.Path(td))
            before = _snapshot(work)
            try:
                for fname, diff in v["diffs"].items():
                    target = work / fname
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(
                        apply_unified_diff(before.get(fname, ""), diff))
            except ValueError as e:
                mismatches.append(f"{task_id}: recorded diff does not "
                                  f"apply to the issued state — {e}")
                continue
            # `invoked` is agent-runtime provenance, not reconstructible
            # from artifacts; take it from the record so every
            # artifact-derived field is re-earned
            rv = _grade(family, before, work, defects[task_id],
                        v["agent_note"], 0.0,
                        invoked=v["failure_mode"] != "agent-unavailable")
            for f in _COMPARED:
                if getattr(rv, f) != v[f]:
                    mismatches.append(f"{task_id} {f}: recorded {v[f]!r}, "
                                      f"recomputed {getattr(rv, f)!r}")
    n = len(bundle["verdicts"])
    if mismatches:
        return Report(name, "mismatch",
                      f"{len(mismatches)} mismatch(es) over {n} verdicts",
                      mismatches)
    return Report(name, "consistent", f"{n}/{n} verdicts recomputed identical")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    paths = [pathlib.Path(a) for a in args] or sorted(
        (pathlib.Path(__file__).resolve().parents[1] / "certifications")
        .glob("*/bundle.json"))
    if not paths:
        print("no bundles to regrade")
        return 0
    bad = 0
    for p in paths:
        r = regrade_bundle(p)
        print(f"{r.bundle}: {r.status} — {r.detail}")
        for m in r.mismatches:
            print(f"  MISMATCH {m}")
        bad += r.status == "mismatch"
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
