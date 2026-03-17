"""claudo litellm wrapper — patches for DO Gradient AI compatibility."""
import sys
import litellm

# Route /v1/messages through chat/completions instead of the OpenAI Responses API.
# DO Gradient AI exposes an OpenAI-compatible endpoint (openai/ model prefix) but does
# NOT implement the Responses API. Without this flag, LiteLLM detects openai/ prefix
# and tries to call litellm.aresponses(), which DO returns 404 on.
litellm.use_chat_completions_url_for_anthropic_messages = True
assert getattr(litellm, 'use_chat_completions_url_for_anthropic_messages', None) is True, \
    "[claudo] FATAL: litellm.use_chat_completions_url_for_anthropic_messages flag missing — " \
    "LiteLLM API changed. Update wrapper.py."

# Patch uvicorn to use asyncio instead of uvloop (uvloop broken on Python 3.14+)
try:
    import uvicorn.config
    if not hasattr(uvicorn.config, 'LOOP_SETUPS'):
        print("[claudo] WARNING: uvicorn.config.LOOP_SETUPS not found — "
              "uvloop patch skipped. Proxy may fail on Python 3.14+ if uvloop is installed.",
              file=sys.stderr)
    else:
        uvicorn.config.LOOP_SETUPS["uvloop"] = "uvicorn.loops.asyncio:asyncio_setup"
except ImportError:
    pass  # uvicorn not installed yet — LiteLLM will install it; patch applied at proxy start
except Exception as e:
    print(f"[claudo] WARNING: uvloop patch failed: {e}", file=sys.stderr)

# Patch the Anthropic pass-through adapter to exclude params that DO/Anthropic
# rejects when forwarded via OpenAI format (e.g. context_management in interactive mode).
# The method lives on LiteLLMMessagesToCompletionTransformationHandler, NOT AnthropicAdapter.
try:
    from litellm.llms.anthropic.experimental_pass_through.adapters.handler import (
        LiteLLMMessagesToCompletionTransformationHandler as _Handler,
    )

    if not hasattr(_Handler, '_prepare_completion_kwargs'):
        print(
            "[claudo] WARNING: LiteLLMMessagesToCompletionTransformationHandler"
            "._prepare_completion_kwargs not found — adapter patch skipped. "
            "context_management and empty text blocks will NOT be stripped. "
            "Update wrapper.py to match current LiteLLM internals.",
            file=sys.stderr,
        )
    else:
        _orig_prepare = _Handler._prepare_completion_kwargs

        def _strip_empty_text_blocks(messages):
            if not isinstance(messages, list):
                return messages
            cleaned = []
            for msg in messages:
                if not isinstance(msg, dict):
                    cleaned.append(msg)
                    continue
                content = msg.get("content")
                if isinstance(content, list):
                    new_content = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text")
                            if text is None or (isinstance(text, str) and text.strip() == ""):
                                continue
                        new_content.append(block)
                    if len(new_content) == 0:
                        # Drop messages that are effectively empty after filtering
                        continue
                    msg = dict(msg)
                    msg["content"] = new_content
                elif isinstance(content, str) and content.strip() == "":
                    # Drop empty string-only messages
                    continue
                cleaned.append(msg)
            return cleaned

        # All params are keyword-only (after *), so **kwargs captures them correctly
        def _patched_prepare(**kwargs):
            extra_kwargs = kwargs.get("extra_kwargs") or {}
            for drop_key in ("context_management",):
                extra_kwargs.pop(drop_key, None)
            kwargs["extra_kwargs"] = extra_kwargs
            # Remove empty text blocks which Anthropic rejects
            if "messages" in kwargs:
                kwargs["messages"] = _strip_empty_text_blocks(kwargs.get("messages"))
            system = kwargs.get("system")
            if isinstance(system, list):
                new_system = []
                for block in system:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text")
                        if text is None or (isinstance(text, str) and text.strip() == ""):
                            continue
                    new_system.append(block)
                kwargs["system"] = new_system if new_system else None
            elif isinstance(system, str) and system.strip() == "":
                kwargs["system"] = None
            return _orig_prepare(**kwargs)

        _Handler._prepare_completion_kwargs = staticmethod(_patched_prepare)
except ImportError as e:
    print(
        f"[claudo] WARNING: failed to import LiteLLM adapter handler: {e}\n"
        "  The experimental_pass_through adapter path has moved or been removed.\n"
        "  context_management params will NOT be stripped — Claude Code may get API errors.\n"
        "  Update the import path in src/python/wrapper.py.",
        file=sys.stderr,
    )
except Exception as e:
    print(f"[claudo] WARNING: failed to patch adapter: {e}", file=sys.stderr)

from litellm.proxy.proxy_cli import run_server
run_server()
