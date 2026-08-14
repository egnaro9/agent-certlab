# Capability contract — aider-headless

Harness commit `7213f39` · family `ledger` · task set `385077b2a93b5ff7` · prompt `dbcbc37d4e776a1a` · python 3.12.13

**6/6 seeded defects fixed** under policy (test suite untouched, edits confined to the allowed files).

| defect class | fixed | failure mode |
|---|---|---|
| accumulator-overwrite | 1/1 | — |
| boundary/off-by-one | 1/1 | — |
| comparison-strictness | 1/1 | — |
| dropped-condition | 1/1 | — |
| ignored-argument | 1/1 | — |
| inverted-extremum | 1/1 | — |

**Conditions and limits.** Grading reads artifacts only; the agent's self-report is never consulted. This contract covers exactly the task family named by its hash — single-edit defects seeded into that family's sources, with its untouched test suite as the complete specification — and says nothing beyond it. Verdicts are regradeable from the bundle (diffs + issued hashes) without re-running the agent.

**Deployment note.** All defect classes fixed under policy on this task set.
