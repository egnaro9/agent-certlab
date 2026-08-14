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
from certlab import ClaudeCodeAgent, certify
certify(ClaudeCodeAgent(), pathlib.Path('certifications/my-run'))"
```

`certifications/` holds published runs: `bundle.json` (the evidence) and
`CONTRACT.md` (the human-readable capability contract, failure modes named).

The real-agent adapter drives Claude Code headless (`claude -p`) with tools
restricted to read/edit/pytest; any agent that can edit files in a directory
can be adapted in ~20 lines (see `certlab/agents.py`).

MIT.
