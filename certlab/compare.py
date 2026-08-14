"""Mechanical comparison compiler: certifications/*/bundle.json in,
COMPARISON.md out. One row per certification run — agent, family, date,
fixed/total, failure modes, harness commit, INCOMPLETE flag — every value
read from a committed bundle, none hand-authored. Order is deterministic
(agent, family, run name), so CI regenerates the file and `git diff
--exit-code`s it: a row that cannot be reproduced from a committed bundle
does not ship (the fleet-board freshness pattern).

`python -m certlab.compare` rewrites COMPARISON.md at the repo root.
"""

from __future__ import annotations

import json
import pathlib
import re

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

HEADER = """\
# Agent comparison

Compiled mechanically by `python -m certlab.compare` from every committed
`certifications/*/bundle.json` — no hand-authored numbers; CI regenerates
this file and fails on any diff. Each run links to its capability contract.
INCOMPLETE marks contracts carrying agent-unavailable verdicts
(infrastructure failures, not capability findings).

| run | agent | family | date | fixed | failure modes | harness | flags |
|---|---|---|---|---|---|---|---|
"""


def _row(bundle_path: pathlib.Path) -> tuple[str, str, str, str]:
    b = json.loads(bundle_path.read_text())
    name = bundle_path.parent.name
    family = b.get("family", "intervals")   # pre-family bundles
    vs = b["verdicts"]
    fixed = sum(1 for v in vs if v["fixed"])
    modes = ", ".join(sorted({v["failure_mode"] for v in vs
                              if v["failure_mode"]})) or "—"
    date = m.group(0) if (m := _DATE.search(name)) else "—"
    flags = ("INCOMPLETE" if any(v["failure_mode"] == "agent-unavailable"
                                 for v in vs) else "")
    return (b["agent_id"], family, name,
            f"| [{name}](certifications/{name}/CONTRACT.md) "
            f"| {b['agent_id']} | {family} | {date} | {fixed}/{len(vs)} "
            f"| {modes} | `{b['harness_commit']}` | {flags} |")


def compile_comparison(cert_dir: pathlib.Path) -> str:
    rows = sorted(_row(p) for p in sorted(cert_dir.glob("*/bundle.json")))
    return HEADER + "".join(r[-1] + "\n" for r in rows)


def main() -> int:
    repo = pathlib.Path(__file__).resolve().parents[1]
    out = repo / "COMPARISON.md"
    out.write_text(compile_comparison(repo / "certifications"))
    print(f"wrote {out.name} "
          f"({sum(1 for _ in (repo / 'certifications').glob('*/bundle.json'))}"
          " run(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
