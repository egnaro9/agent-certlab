# Capability contract — claude-code-headless

Harness commit `4330321` · task set `61eb01a1a3b34dd3` · prompt `2c582137a10a5640` · python 3.14.6

**6/6 seeded defects fixed** under policy (test suite untouched, edits confined to the allowed file).

| defect class | fixed | failure mode |
|---|---|---|
| argument-order | 1/1 | — |
| boundary/off-by-one | 2/2 | — |
| comparison-strictness | 1/1 | — |
| dropped-condition | 1/1 | — |
| inverted-condition | 1/1 | — |

**Conditions and limits.** Grading reads artifacts only; the agent's self-report is never consulted. This contract covers exactly the task set named by its hash — single-file, single-edit Python defects with a complete test suite as specification — and says nothing beyond it. Verdicts are regradeable from the bundle (diffs + issued hashes) without re-running the agent.

**Deployment note.** All defect classes fixed under policy on this task set.
