"""
Unit tests for do_to_cc_names() in src/python/config_gen.py.

config_gen.py reads sys.argv[1..3] and opens a JSON file at module import time,
so we must patch sys.argv and supply a real temp file before importing the module.
importlib.util is used so we can reload fresh each time if needed, but since we
only need do_to_cc_names() and the patch happens once at module level we do it
via a conftest-style fixture at the top of this file.
"""
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest.mock

import pytest


# ---------------------------------------------------------------------------
# Bootstrap: load only the do_to_cc_names function from config_gen.py
# by patching sys.argv before import to prevent IndexError/FileNotFoundError.
# ---------------------------------------------------------------------------

def _load_do_to_cc_names():
    """Import config_gen with a fake argv so module-level code won't crash."""
    # Create a temporary models JSON file with one Claude model entry.
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    )
    json.dump(
        {"data": [{"id": "anthropic-claude-4-5-sonnet"}]},
        tmp,
    )
    tmp.flush()
    tmp.close()

    fake_argv = ["config_gen.py", tmp.name, "http://localhost:4000", "sk-test"]
    with unittest.mock.patch.object(sys, "argv", fake_argv):
        spec = importlib.util.spec_from_file_location(
            "config_gen",
            os.path.join(
                os.path.dirname(__file__), "..", "src", "python", "config_gen.py"
            ),
        )
        mod = importlib.util.module_from_spec(spec)
        # Suppress the stdout YAML print during import-time execution.
        with unittest.mock.patch("sys.stdout"):
            spec.loader.exec_module(mod)

    os.unlink(tmp.name)
    return mod.do_to_cc_names


do_to_cc_names = _load_do_to_cc_names()


# ---------------------------------------------------------------------------
# Parametrized test cases
# ---------------------------------------------------------------------------

BASIC_CASES = [
    # (do_id, expected_primary, alias_must_include)
    (
        "anthropic-claude-4.5-sonnet",
        "claude-4-5-sonnet",
        "claude-sonnet-4-5",
    ),
    (
        "anthropic-claude-3-sonnet",
        "claude-3-sonnet",
        "claude-sonnet-3",
    ),
    (
        "anthropic-claude-4-opus",
        "claude-4-opus",
        "claude-opus-4",
    ),
    (
        "anthropic-claude-3-haiku",
        "claude-3-haiku",
        "claude-haiku-3",
    ),
    # No anthropic- prefix — strip is idempotent
    (
        "claude-3-sonnet",
        "claude-3-sonnet",
        "claude-sonnet-3",
    ),
    # Triple-part version: dots replaced, no raw dots in primary
    (
        "anthropic-claude-4.0.0-sonnet",
        "claude-4-0-0-sonnet",
        None,  # just check primary has no dots
    ),
]


@pytest.mark.parametrize("do_id,expected_primary,alias_must_include", BASIC_CASES)
def test_do_to_cc_names_primary(do_id, expected_primary, alias_must_include):
    """Primary name matches the expected normalized form."""
    primary, aliases = do_to_cc_names(do_id)
    assert primary == expected_primary


@pytest.mark.parametrize("do_id,expected_primary,alias_must_include", BASIC_CASES)
def test_do_to_cc_names_alias_present(do_id, expected_primary, alias_must_include):
    """Required alias is present when specified."""
    if alias_must_include is None:
        pytest.skip("No specific alias requirement for this case")
    primary, aliases = do_to_cc_names(do_id)
    assert alias_must_include in aliases, (
        f"Expected '{alias_must_include}' in aliases {aliases}"
    )


@pytest.mark.parametrize("do_id,expected_primary,alias_must_include", BASIC_CASES)
def test_do_to_cc_names_no_dots_in_primary(do_id, expected_primary, alias_must_include):
    """Primary name must not contain dots (dots are replaced with dashes)."""
    primary, _ = do_to_cc_names(do_id)
    assert "." not in primary, f"Primary '{primary}' still contains dots"


# ---------------------------------------------------------------------------
# Output invariants
# ---------------------------------------------------------------------------

INVARIANT_INPUTS = [do_id for do_id, _, _ in BASIC_CASES]


@pytest.mark.parametrize("do_id", INVARIANT_INPUTS)
def test_invariant_primary_not_in_aliases(do_id):
    """primary must NOT appear in aliases."""
    primary, aliases = do_to_cc_names(do_id)
    assert primary not in aliases, (
        f"primary '{primary}' should not be in aliases {aliases}"
    )


@pytest.mark.parametrize("do_id", INVARIANT_INPUTS)
def test_invariant_aliases_sorted(do_id):
    """aliases must be in sorted order."""
    _, aliases = do_to_cc_names(do_id)
    assert aliases == sorted(aliases), f"aliases {aliases} are not sorted"


@pytest.mark.parametrize("do_id", INVARIANT_INPUTS)
def test_invariant_no_duplicate_aliases(do_id):
    """aliases must have no duplicates."""
    _, aliases = do_to_cc_names(do_id)
    assert len(aliases) == len(set(aliases)), (
        f"aliases {aliases} contain duplicates"
    )


@pytest.mark.parametrize("do_id", INVARIANT_INPUTS)
def test_invariant_return_types(do_id):
    """primary is a str, aliases is a list."""
    primary, aliases = do_to_cc_names(do_id)
    assert isinstance(primary, str)
    assert isinstance(aliases, list)
