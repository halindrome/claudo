"""
Integration tests for streaming response pass-through and helper functions.

Import strategy for wrapper.py:
  wrapper.py imports litellm at module level and calls run_server() at the end,
  so a plain `import wrapper` would try to install/import litellm and start the
  proxy server.  Instead we use sys.modules injection to mock out litellm,
  uvicorn.config, and the handler import path, then load wrapper via
  importlib.util.  This lets the module-level code run (setting flags, applying
  patches) using the mocked objects so _strip_empty_text_blocks and
  _patched_prepare are defined and available for testing.
"""
import importlib.util
import json
import sys
import types
import unittest.mock
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
WRAPPER_PY = Path(__file__).parent.parent.parent / "src" / "python" / "wrapper.py"


# ---------------------------------------------------------------------------
# Helper: load wrapper module with mocked dependencies
# ---------------------------------------------------------------------------

def _load_wrapper_module():
    """
    Load src/python/wrapper.py with litellm, uvicorn, and the LiteLLM handler
    all mocked out so no real proxy is started and no network calls are made.

    Returns the loaded module object.
    """
    # Build a fake litellm module that accepts attribute assignment silently
    fake_litellm = types.ModuleType("litellm")
    fake_litellm.use_chat_completions_url_for_anthropic_messages = True

    # Build a fake uvicorn.config with LOOP_SETUPS so the patch branch runs
    fake_uvicorn_config = types.ModuleType("uvicorn.config")
    fake_uvicorn_config.LOOP_SETUPS = {"uvloop": "uvicorn.loops.uvloop:uvloop_setup"}
    fake_uvicorn = types.ModuleType("uvicorn")
    fake_uvicorn.config = fake_uvicorn_config

    # Build a fake handler class with _prepare_completion_kwargs
    fake_handler_cls = type(
        "LiteLLMMessagesToCompletionTransformationHandler",
        (),
        {"_prepare_completion_kwargs": staticmethod(lambda **kwargs: kwargs)},
    )
    fake_handler_mod = types.ModuleType(
        "litellm.llms.anthropic.experimental_pass_through.adapters.handler"
    )
    fake_handler_mod.LiteLLMMessagesToCompletionTransformationHandler = fake_handler_cls

    # Build parent package stubs so the nested import resolves
    fake_llms = types.ModuleType("litellm.llms")
    fake_anthropic = types.ModuleType("litellm.llms.anthropic")
    fake_exp = types.ModuleType("litellm.llms.anthropic.experimental_pass_through")
    fake_adapters = types.ModuleType(
        "litellm.llms.anthropic.experimental_pass_through.adapters"
    )

    # Fake proxy_cli so run_server() is a no-op
    fake_proxy_cli = types.ModuleType("litellm.proxy.proxy_cli")
    fake_proxy_cli.run_server = lambda *a, **kw: None
    fake_proxy = types.ModuleType("litellm.proxy")
    fake_proxy.proxy_cli = fake_proxy_cli

    injected = {
        "litellm": fake_litellm,
        "uvicorn": fake_uvicorn,
        "uvicorn.config": fake_uvicorn_config,
        "litellm.llms": fake_llms,
        "litellm.llms.anthropic": fake_anthropic,
        "litellm.llms.anthropic.experimental_pass_through": fake_exp,
        "litellm.llms.anthropic.experimental_pass_through.adapters": fake_adapters,
        "litellm.llms.anthropic.experimental_pass_through.adapters.handler": fake_handler_mod,
        "litellm.proxy": fake_proxy,
        "litellm.proxy.proxy_cli": fake_proxy_cli,
    }

    # Temporarily inject our fakes, then load the module
    saved = {k: sys.modules.get(k) for k in injected}
    sys.modules.update(injected)
    try:
        spec = importlib.util.spec_from_file_location("wrapper_under_test", WRAPPER_PY)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        # Restore original sys.modules state
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    return mod


# Load once for the module
_wrapper = _load_wrapper_module()
_strip_empty_text_blocks = _wrapper._strip_empty_text_blocks


# ---------------------------------------------------------------------------
# _strip_empty_text_blocks tests
# ---------------------------------------------------------------------------

def test_strip_empty_text_blocks_preserves_content():
    """Non-empty text blocks pass through unchanged."""
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "hello"}]}
    ]
    result = _strip_empty_text_blocks(messages)
    assert result == messages, f"Expected input unchanged, got {result!r}"


def test_strip_empty_text_blocks_removes_empty():
    """Messages whose only content block has empty/whitespace text are dropped."""
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "  "}]}
    ]
    result = _strip_empty_text_blocks(messages)
    assert result == [], f"Expected empty list (message dropped), got {result!r}"


def test_strip_empty_text_blocks_mixed_content():
    """Empty text block is removed; non-text (tool_use) block is preserved; message kept."""
    messages = [
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": ""},
                {"type": "tool_use", "id": "tu_1", "name": "bash", "input": {}},
            ],
        }
    ]
    result = _strip_empty_text_blocks(messages)
    assert len(result) == 1, f"Expected 1 message, got {len(result)}"
    blocks = result[0]["content"]
    types_in_result = [b["type"] for b in blocks]
    assert "text" not in types_in_result, "Empty text block should have been removed"
    assert "tool_use" in types_in_result, "tool_use block should be preserved"


def test_context_management_stripped():
    """
    _patched_prepare strips context_management from extra_kwargs before
    forwarding to the original prepare function.
    """
    # Capture what the original handler receives
    received = {}

    def fake_orig_prepare(**kwargs):
        received.update(kwargs)
        return kwargs

    # Re-load wrapper with a controlled _orig_prepare so we can inspect the call
    fake_litellm = types.ModuleType("litellm")
    fake_litellm.use_chat_completions_url_for_anthropic_messages = True

    fake_uvicorn_config = types.ModuleType("uvicorn.config")
    fake_uvicorn_config.LOOP_SETUPS = {}
    fake_uvicorn = types.ModuleType("uvicorn")
    fake_uvicorn.config = fake_uvicorn_config

    fake_handler_cls = type(
        "LiteLLMMessagesToCompletionTransformationHandler",
        (),
        {"_prepare_completion_kwargs": staticmethod(fake_orig_prepare)},
    )
    fake_handler_mod = types.ModuleType(
        "litellm.llms.anthropic.experimental_pass_through.adapters.handler"
    )
    fake_handler_mod.LiteLLMMessagesToCompletionTransformationHandler = fake_handler_cls

    fake_llms = types.ModuleType("litellm.llms")
    fake_anthropic = types.ModuleType("litellm.llms.anthropic")
    fake_exp = types.ModuleType("litellm.llms.anthropic.experimental_pass_through")
    fake_adapters = types.ModuleType(
        "litellm.llms.anthropic.experimental_pass_through.adapters"
    )
    fake_proxy_cli = types.ModuleType("litellm.proxy.proxy_cli")
    fake_proxy_cli.run_server = lambda *a, **kw: None
    fake_proxy = types.ModuleType("litellm.proxy")
    fake_proxy.proxy_cli = fake_proxy_cli

    injected = {
        "litellm": fake_litellm,
        "uvicorn": fake_uvicorn,
        "uvicorn.config": fake_uvicorn_config,
        "litellm.llms": fake_llms,
        "litellm.llms.anthropic": fake_anthropic,
        "litellm.llms.anthropic.experimental_pass_through": fake_exp,
        "litellm.llms.anthropic.experimental_pass_through.adapters": fake_adapters,
        "litellm.llms.anthropic.experimental_pass_through.adapters.handler": fake_handler_mod,
        "litellm.proxy": fake_proxy,
        "litellm.proxy.proxy_cli": fake_proxy_cli,
    }

    saved = {k: sys.modules.get(k) for k in injected}
    sys.modules.update(injected)
    try:
        spec = importlib.util.spec_from_file_location("wrapper_ctx_test", WRAPPER_PY)
        mod2 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod2)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    patched_prepare = mod2._patched_prepare

    # Call with context_management in extra_kwargs
    patched_prepare(
        messages=[{"role": "user", "content": "hi"}],
        extra_kwargs={"context_management": {"type": "auto"}, "other_key": "value"},
    )

    assert "context_management" not in received.get("extra_kwargs", {}), (
        "context_management should have been stripped from extra_kwargs"
    )
    assert received.get("extra_kwargs", {}).get("other_key") == "value", (
        "Unrelated extra_kwargs keys must be preserved"
    )


# ---------------------------------------------------------------------------
# Fixture data integrity test
# ---------------------------------------------------------------------------

def test_streaming_fixture_is_valid():
    """streaming_response.json contains a valid list with expected structure."""
    fixture = json.loads((FIXTURES_DIR / "streaming_response.json").read_text())
    assert isinstance(fixture, list), "Fixture must be a JSON array"
    assert len(fixture) >= 2, "Fixture must have at least 2 entries"
    for entry in fixture:
        assert "messages" in entry, "Each fixture entry must have 'messages'"
        assert "extra_kwargs" in entry, "Each fixture entry must have 'extra_kwargs'"
