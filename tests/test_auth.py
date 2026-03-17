"""
Tests for src/python/auth.py — check, update, create, and unknown commands.

auth.py reads sys.argv[1] at module level, so all tests call it via subprocess
to avoid import-time side effects.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest


AUTH_SCRIPT = Path(__file__).parent.parent / "src" / "python" / "auth.py"


def run_auth(cmd, path):
    """Run auth.py with the given command and path, return CompletedProcess."""
    return subprocess.run(
        [sys.executable, str(AUTH_SCRIPT), cmd, str(path)],
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# check command
# ---------------------------------------------------------------------------


def test_check_nonexistent_file(tmp_path):
    """Non-existent file → stdout 'no', exit code 0."""
    result = run_auth("check", tmp_path / "missing.json")
    assert result.returncode == 0
    assert result.stdout.strip() == "no"


def test_check_num_startups_zero(tmp_path):
    """JSON with numStartups=0 → 'no'."""
    p = tmp_path / "claude.json"
    p.write_text(json.dumps({"numStartups": 0}))
    result = run_auth("check", p)
    assert result.stdout.strip() == "no"


def test_check_num_startups_one(tmp_path):
    """JSON with numStartups=1 → 'yes'."""
    p = tmp_path / "claude.json"
    p.write_text(json.dumps({"numStartups": 1}))
    result = run_auth("check", p)
    assert result.stdout.strip() == "yes"


def test_check_num_startups_many(tmp_path):
    """JSON with numStartups=5 → 'yes'."""
    p = tmp_path / "claude.json"
    p.write_text(json.dumps({"numStartups": 5}))
    result = run_auth("check", p)
    assert result.stdout.strip() == "yes"


def test_check_corrupt_json(tmp_path):
    """Corrupt JSON → 'no', exit code 0 (exception caught)."""
    p = tmp_path / "claude.json"
    p.write_text("not json")
    result = run_auth("check", p)
    assert result.returncode == 0
    assert result.stdout.strip() == "no"


def test_check_missing_key(tmp_path):
    """JSON missing numStartups key → 'no' (defaults to 0)."""
    p = tmp_path / "claude.json"
    p.write_text(json.dumps({"hasCompletedOnboarding": True}))
    result = run_auth("check", p)
    assert result.stdout.strip() == "no"


# ---------------------------------------------------------------------------
# update command
# ---------------------------------------------------------------------------


def test_update_increments_from_zero(tmp_path):
    """JSON with numStartups=0 → after update numStartups=1, firstStartTime added."""
    p = tmp_path / "claude.json"
    p.write_text(json.dumps({"numStartups": 0}))
    run_auth("update", p)
    d = json.loads(p.read_text())
    assert d["numStartups"] == 1
    assert "firstStartTime" in d


def test_update_keeps_high_value(tmp_path):
    """JSON with numStartups=5 → after update numStartups stays >= 1 (max keeps it)."""
    p = tmp_path / "claude.json"
    p.write_text(json.dumps({"numStartups": 5}))
    run_auth("update", p)
    d = json.loads(p.read_text())
    # max(5, 1) == 5 — value should not drop below original
    assert d["numStartups"] == 5


def test_update_preserves_first_start_time(tmp_path):
    """JSON with existing firstStartTime → after update firstStartTime unchanged."""
    p = tmp_path / "claude.json"
    original_time = "2024-01-01T00:00:00+00:00"
    p.write_text(json.dumps({"numStartups": 1, "firstStartTime": original_time}))
    run_auth("update", p)
    d = json.loads(p.read_text())
    assert d["firstStartTime"] == original_time


# ---------------------------------------------------------------------------
# create command
# ---------------------------------------------------------------------------


def test_create_nonexistent_path(tmp_path):
    """Non-existent path → file created with numStartups=1, hasCompletedOnboarding=True."""
    p = tmp_path / "new_claude.json"
    assert not p.exists()
    result = run_auth("create", p)
    assert result.returncode == 0
    assert p.exists()
    d = json.loads(p.read_text())
    assert d["numStartups"] == 1
    assert d["hasCompletedOnboarding"] is True


def test_create_valid_json_with_required_keys(tmp_path):
    """Created file is valid JSON with all required keys."""
    p = tmp_path / "new_claude.json"
    run_auth("create", p)
    d = json.loads(p.read_text())
    assert "numStartups" in d
    assert "firstStartTime" in d
    assert "hasCompletedOnboarding" in d


# ---------------------------------------------------------------------------
# unknown command
# ---------------------------------------------------------------------------


def test_unknown_command_exit_code(tmp_path):
    """Unknown command → exit code 1."""
    result = run_auth("bogus", tmp_path / "irrelevant.json")
    assert result.returncode == 1
