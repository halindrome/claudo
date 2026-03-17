"""
Integration tests for the proxy startup sequence.

These tests validate config generation, wrapper file content, and platform
compatibility — all without a live DO API key or a running LiteLLM process.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
SRC_DIR = Path(__file__).parent.parent.parent / "src" / "python"
CONFIG_GEN = SRC_DIR / "config_gen.py"
WRAPPER_PY = SRC_DIR / "wrapper.py"


def test_generate_litellm_config_from_fixture(tmp_path):
    """Config generation produces valid YAML with expected model entries from fixture."""
    # Copy the fixture models_cache.json to tmp_path
    cache_src = FIXTURES_DIR / "models_cache.json"
    cache_dest = tmp_path / "models_cache.json"
    cache_dest.write_text(cache_src.read_text())

    result = subprocess.run(
        [
            sys.executable,
            str(CONFIG_GEN),
            str(cache_dest),
            "https://api.digitalocean.com/v1/ai/",
            "sk-test",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"config_gen failed:\n{result.stderr}"
    yaml_out = result.stdout

    # The fixture has 'anthropic-claude-4.5-sonnet' which normalizes to 'claude-4-5-sonnet'
    assert "model_name: claude-4-5-sonnet" in yaml_out, (
        "Expected 'model_name: claude-4-5-sonnet' in YAML output"
    )
    # Should use openai/ prefix for DO model
    assert "model: openai/anthropic-claude-4.5-sonnet" in yaml_out, (
        "Expected 'model: openai/anthropic-claude-4.5-sonnet' in YAML output"
    )
    # The fixture also has 'anthropic-claude-3-haiku'
    assert "model_name: claude-3-haiku" in yaml_out, (
        "Expected 'model_name: claude-3-haiku' in YAML output"
    )


def test_generate_litellm_config_empty_models(tmp_path):
    """Config generation exits non-zero with a clear error when model list is empty."""
    cache_dest = tmp_path / "models_cache.json"
    cache_dest.write_text(json.dumps({"data": []}))

    result = subprocess.run(
        [
            sys.executable,
            str(CONFIG_GEN),
            str(cache_dest),
            "https://api.digitalocean.com/v1/ai/",
            "sk-test",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0, "Expected non-zero exit code for empty model list"
    assert "No Claude models found" in result.stderr, (
        f"Expected 'No Claude models found' in stderr, got: {result.stderr!r}"
    )


def test_litellm_wrapper_contains_patches():
    """wrapper.py contains all expected patch markers (validates Plan 03 hardening)."""
    content = WRAPPER_PY.read_text()

    assert "use_chat_completions_url_for_anthropic_messages" in content, (
        "Missing: use_chat_completions_url_for_anthropic_messages flag"
    )
    assert "LOOP_SETUPS" in content, (
        "Missing: LOOP_SETUPS (uvloop compatibility patch)"
    )
    assert "experimental_pass_through" in content, (
        "Missing: experimental_pass_through import path"
    )
    assert "hasattr(_Handler" in content, (
        "Missing: hasattr(_Handler ...) attribute guard (Plan 03 hardening)"
    )
    assert "ImportError" in content, (
        "Missing: ImportError handler (Plan 03 hardening)"
    )


def test_stat_cache_ttl_platform_compatibility(tmp_path):
    """os.path.getmtime works cross-platform to read cache file mtime within 60s."""
    cache_file = tmp_path / "models_cache.json"
    cache_file.write_text(json.dumps({"data": []}))

    # Run in a subprocess to isolate from any import side effects
    code = (
        "import os, time\n"
        f"path = {str(cache_file)!r}\n"
        "mtime = os.path.getmtime(path)\n"
        "age = time.time() - mtime\n"
        "assert age >= 0, f'mtime in the future: age={age}'\n"
        "assert age < 60, f'mtime too old: age={age}'\n"
        "print('ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"stat/mtime check failed:\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    assert "ok" in result.stdout
