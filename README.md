# agent-certlab

**CI-grade reliability certification for coding agents.** Run an agent
against tasks with **seeded, known defects**, grade only the artifacts it
leaves on disk, and emit a **capability contract** backed by a **replayable
evidence bundle** — not a benchmark score, and never the agent's own account
of its success.

Part of a program on verifiable evaluation:
[evalmut](https://github.com/egnaro9/evalmut) (mutation testing for eval
suites) → [reference-fleet](https://github.com/egnaro9/reference-fleet)
(certified defect models + the [audit
board](https://egnaro9.github.io/reference-fleet/)) → this lab.

Every capability contract here is backed by a replayable evidence bundle — one
per run under [`certifications/`](certifications) — and each one is registered
in the program's [evidence registry](https://egnaro9.github.io/vac-protocol/)
([registry.json](https://github.com/egnaro9/vac-protocol/blob/main/registry.json)).
Ten minutes and no API key is enough to try to break one:
[REPLAY_REQUEST.md](https://github.com/egnaro9/vac-protocol/blob/main/REPLAY_REQUEST.md).

**Note what is under test here: an agent, not a model.** The lab certifies
the whole software system that edits code (today: Claude Code, driven
headless); there is no model artifact in this repo by design. The program's
trained defect **model** — a LoRA adapter with a measured, certified defect
rate — lives in
[reference-fleet/native](https://github.com/egnaro9/reference-fleet/tree/main/native).

**Shipped certifications** (real runs, committed with evidence): the
mechanically compiled [**COMPARISON.md**](COMPARISON.md) is the index — one
row per run, every number read from a committed `bundle.json`, regenerated
and diff-checked in CI. The first two contracts:
[claude-code-2026-08-14](certifications/claude-code-2026-08-14/CONTRACT.md)
(run locally) and
[claude-code-cloud-2026-08-14](certifications/claude-code-cloud-2026-08-14/CONTRACT.md)
(**entirely inside GitHub Actions** via the dispatchable
[`real-certification` workflow](.github/workflows/certify.yml), which takes
the agent — Claude Code or aider — and the task family as dispatch inputs:
calibration gate first, then the headless runs on an ephemeral runner,
bundle uploaded as an artifact). Every committed certification is
independently **regraded in CI** (`python -m certlab.regrade`): issued files
are rematerialized, the bundle's diffs reapplied, and every verdict
re-earned from artifacts — recorded verdicts are never trusted, including
ours.

## The three rules that make a certificate mean something

1. **Prove the instrument before the finding.** Before any agent sees a
   task, the harness proves the clean tree passes its suite and the seeded
   tree fails it. The prover refused one of this repo's own defects on its
   first run — the substrate suite had never tested `x == hi` — which is the
   method working on its own materials.
2. **Calibrate on constructed agents before certifying real ones.** The
   wedge must score `null-agent` 0/6, `oracle-agent` 6/6, and fail
   `test-deleter-agent` 0/6 by **policy** — pytest alone would happily pass
   its gutted suite. That separation is CI (`tests/`); a wedge that cannot
   produce it must not certify anything.
3. **Artifacts only, regradeable later.** Grading reads the working tree
   after the run: policy (test suite byte-identical, edits confined to
   allowed paths), then the suite itself. The bundle carries issued hashes,
   full diffs, environment, and a harness commit stamped from the last
   code-touching commit — verdicts can be recomputed without re-running the
   agent.

## Certify an agent

```
pip install -e ".[test]" && python -m pytest tests/ -q   # calibration first
python -c "
import pathlib
from certlab import INTERVALS, ClaudeCodeAgent, certify
certify(ClaudeCodeAgent(), INTERVALS, pathlib.Path('certifications/my-run'))"
```

Three task families ship (`certlab.FAMILIES`). `intervals` is a
single-module substrate. `ledger` is a three-module package (`models` →
`validate` → `report`) whose defects include genuinely cross-file cases —
one seeded in `models.py` that only the `validate`/`report` call paths can
fail on, and one whose policy-legal-but-wrong fix in `report.py` the
validate-direct tests reject, pinning the fix to the file the defect lives
in. `machine` is a four-module expression interpreter (`tokenizer` →
`parser` → `evaluator`, `api` over all three) built deliberately harder:
both real agents scored 6/6 on the first two families, so that matrix
measures adapter discipline — this family exists to separate agents. Two of
its six defects are **coordinated two-file seeds** (a parser node-shape
drift the evaluator fully compensates, so end-to-end stays green while the
direct sections object; a `**` token split a parser hack half-compensates
with the wrong associativity): reverting either file alone leaves the suite
red — proven in the calibration tests — so no single-file patch is the
minimal correct fix. A third replays the pinned-fix-location trap one
family up: compensating in `api.py`'s error mapping is policy-legal and
greens the whole api section, but the tokens-direct tests assert the raised
position itself.

`certifications/` holds published runs: `bundle.json` (the evidence) and
`CONTRACT.md` (the human-readable capability contract, failure modes named).

Two real-agent adapters ship: Claude Code headless (`claude -p`, tools
restricted to read/edit/pytest) and aider headless (`--message --no-git
--yes-always`, allowed files named explicitly); any agent that can edit
files in a directory can be adapted in ~20 lines (see `certlab/agents.py`).

MIT.
