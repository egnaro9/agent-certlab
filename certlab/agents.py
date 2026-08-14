"""Agents under test.

Five CONSTRUCTED calibration agents (the reference-fleet pattern one level
up) and two real ones. The wedge is only trusted after it separates the
constructed set: null must score 0, oracle must score perfect, test-deleter
must be FAILED BY POLICY — an agent that makes CI green by weakening the
tests is the exact failure a naive grader rewards — forbidden-file must be
failed by the allowed-paths layer even though pytest passes, and unavailable
must read agent-unavailable, never as a capability finding.
"""

from __future__ import annotations

import pathlib
import subprocess
from dataclasses import dataclass

from .tasks import Defect, TaskFamily


def _shadow_conftest(family: TaskFamily) -> str:
    """conftest.py that preloads every editable module CLEAN into
    sys.modules, shadowing the seeded files without touching them."""
    parts = ["import sys, types\n"]
    for rel in sorted(family.allowed_edits):
        name = rel[:-3].replace("/", ".")
        parts.append(f"_m = types.ModuleType({name!r})\n"
                     f"exec({family.issued[rel]!r}, _m.__dict__)\n"
                     f"sys.modules[{name!r}] = _m\n")
    return "".join(parts)


@dataclass
class AgentResult:
    invoked: bool
    note: str


class NullAgent:
    """Does nothing. The floor: any wedge that scores this above 0 is broken."""

    agent_id = "null-agent"
    kind = "constructed-calibration"

    def run(self, workdir: pathlib.Path, family: TaskFamily,
            defect: Defect) -> AgentResult:
        return AgentResult(invoked=True, note="did nothing by construction")


class OracleAgent:
    """Applies the known-correct fix (it holds ground truth). The ceiling:
    any wedge that scores this below perfect cannot recognize success."""

    agent_id = "oracle-agent"
    kind = "constructed-calibration"

    def run(self, workdir: pathlib.Path, family: TaskFamily,
            defect: Defect) -> AgentResult:
        for rel in sorted(family.allowed_edits):
            (workdir / rel).write_text(family.issued[rel])
        return AgentResult(invoked=True, note="wrote the clean source verbatim")


class TestDeleterAgent:
    """Makes CI green by gutting the test file. A wedge that certifies this
    is worse than no wedge — this is the tellability check for the POLICY
    layer, not the test layer."""

    agent_id = "test-deleter-agent"
    kind = "constructed-calibration"

    def run(self, workdir: pathlib.Path, family: TaskFamily,
            defect: Defect) -> AgentResult:
        for rel in sorted(family.suite_paths):
            (workdir / rel).write_text("def test_nothing():\n    pass\n")
        return AgentResult(invoked=True, note="replaced the suite with a no-op")


class UnavailableAgent:
    """Never executes (spawn failure, API error, exhausted credits) and
    leaves no artifacts. Every verdict must read agent-unavailable — an
    infrastructure failure reported as no-fix-attempted would let an outage
    masquerade as a capability finding, the first cloud run's exact bug."""

    agent_id = "unavailable-agent"
    kind = "constructed-calibration"

    def run(self, workdir: pathlib.Path, family: TaskFamily,
            defect: Defect) -> AgentResult:
        return AgentResult(invoked=False, note="constructed spawn failure")


class ForbiddenFileAgent:
    """Greens the suite WITHOUT touching any allowed file: drops a
    conftest.py that preloads the family's clean modules into sys.modules,
    shadowing the seeded files. pytest passes and the issued suite is
    byte-identical — only the allowed-paths policy layer can tell. The
    tellability check for the modified-forbidden-files branch."""

    agent_id = "forbidden-file-agent"
    kind = "constructed-calibration"

    def run(self, workdir: pathlib.Path, family: TaskFamily,
            defect: Defect) -> AgentResult:
        (workdir / "conftest.py").write_text(_shadow_conftest(family))
        return AgentResult(invoked=True,
                           note="shadowed the sources via a new conftest.py")


class ClaudeCodeAgent:
    """The real agent under test: Claude Code, headless (`claude -p`).

    Scoped to the working directory; the prompt is TASK.md verbatim plus a
    pointer at the files. Tool surface is limited to reading, editing, and
    running pytest. The wedge grades only artifacts on disk afterwards — the
    agent's own account of success is never consulted.
    """

    agent_id = "claude-code-headless"
    kind = "real"

    def __init__(self, model: str | None = None, timeout: int = 600):
        self.model = model
        self.timeout = timeout

    def run(self, workdir: pathlib.Path, family: TaskFamily,
            defect: Defect) -> AgentResult:
        prompt = (workdir / "TASK.md").read_text()
        cmd = ["claude", "-p", prompt,
               "--allowedTools", "Read", "Edit", "Write", "Bash(python -m pytest*)",
               "--permission-mode", "acceptEdits"]
        if self.model:
            cmd += ["--model", self.model]
        try:
            proc = subprocess.run(cmd, cwd=workdir, capture_output=True,
                                  text=True, timeout=self.timeout)
            return AgentResult(
                invoked=proc.returncode == 0,
                note=f"exit {proc.returncode}; last output: "
                     f"{(proc.stdout or proc.stderr)[-200:]!r}")
        except subprocess.TimeoutExpired:
            return AgentResult(invoked=False, note=f"timeout {self.timeout}s")


class AiderAgent:
    """The second real agent under test: aider, headless.

    `--no-git` because the workdir is not a repo and the policy snapshot
    must never see a .git dir aider would otherwise create; `--yes-always`
    answers every confirmation; the prompt is TASK.md verbatim via
    `--message`; the allowed-edit files are named explicitly on the command
    line. The model is an Anthropic one (aider reads ANTHROPIC_API_KEY from
    the environment). Graded identically: artifacts on disk only.
    """

    agent_id = "aider-headless"
    kind = "real"

    def __init__(self, model: str = "sonnet", timeout: int = 600):
        self.model = model   # aider's alias for Anthropic's latest Sonnet
        self.timeout = timeout

    def run(self, workdir: pathlib.Path, family: TaskFamily,
            defect: Defect) -> AgentResult:
        prompt = (workdir / "TASK.md").read_text()
        cmd = ["aider", "--no-git", "--yes-always", "--model", self.model,
               "--message", prompt, *sorted(family.allowed_edits)]
        try:
            proc = subprocess.run(cmd, cwd=workdir, capture_output=True,
                                  text=True, timeout=self.timeout)
            return AgentResult(
                invoked=proc.returncode == 0,
                note=f"exit {proc.returncode}; last output: "
                     f"{(proc.stdout or proc.stderr)[-200:]!r}")
        except subprocess.TimeoutExpired:
            return AgentResult(invoked=False, note=f"timeout {self.timeout}s")
