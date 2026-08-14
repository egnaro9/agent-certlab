# Agent comparison

Compiled mechanically by `python -m certlab.compare` from every committed
`certifications/*/bundle.json` — no hand-authored numbers; CI regenerates
this file and fails on any diff. Each run links to its capability contract.
INCOMPLETE marks contracts carrying agent-unavailable verdicts
(infrastructure failures, not capability findings).

| run | agent | family | date | fixed | failure modes | harness | flags |
|---|---|---|---|---|---|---|---|
| [aider-intervals-2026-08-14](certifications/aider-intervals-2026-08-14/CONTRACT.md) | aider-headless | intervals | 2026-08-14 | 6/6 | — | `7213f39` |  |
| [aider-ledger-2026-08-14](certifications/aider-ledger-2026-08-14/CONTRACT.md) | aider-headless | ledger | 2026-08-14 | 6/6 | — | `7213f39` |  |
| [aider-machine-2026-08-14](certifications/aider-machine-2026-08-14/CONTRACT.md) | aider-headless | machine | 2026-08-14 | 6/6 | — | `7954393` |  |
| [claude-code-2026-08-14](certifications/claude-code-2026-08-14/CONTRACT.md) | claude-code-headless | intervals | 2026-08-14 | 6/6 | — | `4330321` |  |
| [claude-code-cloud-2026-08-14](certifications/claude-code-cloud-2026-08-14/CONTRACT.md) | claude-code-headless | intervals | 2026-08-14 | 6/6 | — | `7ec0f94` |  |
| [claude-code-ledger-2026-08-14](certifications/claude-code-ledger-2026-08-14/CONTRACT.md) | claude-code-headless | ledger | 2026-08-14 | 6/6 | — | `8065d6e` |  |
| [claude-code-machine-2026-08-14](certifications/claude-code-machine-2026-08-14/CONTRACT.md) | claude-code-headless | machine | 2026-08-14 | 6/6 | — | `7954393` |  |
