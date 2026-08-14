"""Real-agent adapters, validated without spending an API call: command
construction is pinned against a monkeypatched subprocess, the failure
paths (nonzero exit, timeout) must read not-invoked, and a fake editing
run must flow through the SAME wedge that graded the calibration set —
the adapter is plumbing; the grading path is already proven.
"""

import pathlib
import subprocess
import sys
import types

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from certlab.agents import AiderAgent, ClaudeCodeAgent
from certlab.tasks import INTERVALS, materialize
from certlab.wedge import certify


@pytest.fixture
def workdir(tmp_path):
    return materialize(INTERVALS.defects[0], INTERVALS, tmp_path / "work")


def _fake_subprocess(monkeypatch, returncode=0, effect=None, raise_timeout=False):
    """Replace certlab.agents' subprocess binding only — tasks/wedge keep
    the real one, so pytest still actually runs during certify."""
    calls = []

    def run(cmd, cwd=None, capture_output=None, text=None, timeout=None):
        calls.append({"cmd": list(cmd), "cwd": cwd, "timeout": timeout})
        if raise_timeout:
            raise subprocess.TimeoutExpired(cmd, timeout)
        if effect:
            effect(pathlib.Path(cwd))
        return types.SimpleNamespace(returncode=returncode,
                                     stdout="fake output", stderr="")

    monkeypatch.setattr("certlab.agents.subprocess", types.SimpleNamespace(
        run=run, TimeoutExpired=subprocess.TimeoutExpired))
    return calls


def test_aider_command_construction(workdir, monkeypatch):
    calls = _fake_subprocess(monkeypatch)
    r = AiderAgent(model="anthropic/claude-x", timeout=42).run(
        workdir, INTERVALS, INTERVALS.defects[0])
    assert r.invoked and "exit 0" in r.note
    (c,) = calls
    cmd = c["cmd"]
    assert cmd[0] == "aider"
    assert "--no-git" in cmd            # workdir is not a repo; snapshot
    assert "--yes-always" in cmd        # must never see a .git dir
    assert cmd[cmd.index("--model") + 1] == "anthropic/claude-x"
    assert cmd[cmd.index("--message") + 1] == INTERVALS.task_md
    # the allowed-edit files are named explicitly, sorted, after the flags
    assert cmd[-len(INTERVALS.allowed_edits):] == sorted(INTERVALS.allowed_edits)
    assert c["cwd"] == workdir and c["timeout"] == 42


def test_aider_default_model_is_anthropic_alias(workdir, monkeypatch):
    calls = _fake_subprocess(monkeypatch)
    AiderAgent().run(workdir, INTERVALS, INTERVALS.defects[0])
    cmd = calls[0]["cmd"]
    assert cmd[cmd.index("--model") + 1] == "sonnet"


def test_aider_nonzero_exit_reads_not_invoked(workdir, monkeypatch):
    _fake_subprocess(monkeypatch, returncode=2)
    r = AiderAgent().run(workdir, INTERVALS, INTERVALS.defects[0])
    assert not r.invoked and "exit 2" in r.note


def test_aider_timeout_reads_not_invoked(workdir, monkeypatch):
    _fake_subprocess(monkeypatch, raise_timeout=True)
    r = AiderAgent(timeout=7).run(workdir, INTERVALS, INTERVALS.defects[0])
    assert not r.invoked and r.note == "timeout 7s"


def test_claude_code_command_construction(workdir, monkeypatch):
    calls = _fake_subprocess(monkeypatch)
    r = ClaudeCodeAgent(model="opus", timeout=99).run(
        workdir, INTERVALS, INTERVALS.defects[0])
    assert r.invoked
    cmd = calls[0]["cmd"]
    assert cmd[:3] == ["claude", "-p", INTERVALS.task_md]
    assert cmd[cmd.index("--model") + 1] == "opus"
    assert calls[0]["cwd"] == workdir and calls[0]["timeout"] == 99


def test_fake_editing_aider_run_is_graded_by_the_wedge(tmp_path, monkeypatch):
    """Calibration-independence: an 'aider' whose subprocess writes the
    clean sources certifies 6/6 through the unchanged artifact grading —
    proof the adapter feeds the wedge, with no API key anywhere."""
    def oracle_fix(cwd):
        for rel in sorted(INTERVALS.allowed_edits):
            (cwd / rel).write_text(INTERVALS.issued[rel])
    _fake_subprocess(monkeypatch, effect=oracle_fix)
    b = certify(AiderAgent(), INTERVALS, tmp_path / "aider")
    assert b["agent_id"] == "aider-headless" and b["agent_kind"] == "real"
    assert b["family"] == "intervals"
    assert sum(v["fixed"] for v in b["verdicts"]) == len(b["verdicts"]) == 6
