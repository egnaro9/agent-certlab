# Agent comparison

Compiled mechanically by `python -m certlab.compare` from every committed
`certifications/*/bundle.json` — no hand-authored numbers; CI regenerates
this file and fails on any diff. Each run links to its capability contract.
INCOMPLETE marks contracts carrying agent-unavailable verdicts
(infrastructure failures, not capability findings).

| run | agent | family | date | fixed | failure modes | harness | flags |
|---|---|---|---|---|---|---|---|
| [claude-code-2026-08-14](certifications/claude-code-2026-08-14/CONTRACT.md) | claude-code-headless | intervals | 2026-08-14 | 6/6 | — | `4330321` |  |
| [claude-code-cloud-2026-08-14](certifications/claude-code-cloud-2026-08-14/CONTRACT.md) | claude-code-headless | intervals | 2026-08-14 | 6/6 | — | `7ec0f94` |  |
| [claude-code-ledger-2026-08-14](certifications/claude-code-ledger-2026-08-14/CONTRACT.md) | claude-code-headless | ledger | 2026-08-14 | 6/6 | — | `8065d6e` |  |
