"""
backends/model_provider.py

The single swap point for model provider. Change MODEL_PROVIDER (env var)
and/or the entries in MODEL_MAP below — nothing else in the codebase needs
to change. This is the "one file, one function" seam requested in the
requirements gathering: every agent construction in this project calls
get_model() rather than instantiating a chat model directly.

NOTE: verify current provider support and package names against
docs.langchain.com before relying on this in production. init_chat_model's
provider-string conventions and the specific langchain-<provider> packages
required have moved before and will move again.

NVIDIA NIM / API Catalog notes
-------------------------------
langchain's init_chat_model() does not have a documented, guaranteed
"nvidia:" provider string the way it does for openai/anthropic/deepseek,
so the nvidia branch below instantiates langchain_nvidia_ai_endpoints's
ChatNVIDIA directly (this is exactly what the reference notebook does).
Everything else about get_model()'s contract (env var required, kwargs
passed through) stays identical for callers.

Requires: pip install langchain-nvidia-ai-endpoints
Env vars:
    NVIDIA_API_KEY        -- required, your NVIDIA API Catalog key (starts "nvapi-")
    NVIDIA_MODEL          -- optional, overrides the default model id below
    MODEL_TIMEOUT_SECONDS -- optional, overrides the 5-minute default timeout
                             applied to every provider below

Timeout
-------
Every provider gets a 300s (5 min) request timeout by default. 60s (the
langchain-nvidia-ai-endpoints default, and often the underlying SDK default
for other providers too) is too short for reasoning models or long
tool-calling agent turns -- it's a client-side default, not a real ceiling
imposed by any of these APIs, so raising it here is safe. Override globally
with MODEL_TIMEOUT_SECONDS, or per-call with get_model(timeout=...).
"""

import os

import requests
from langchain.chat_models import init_chat_model

DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("MODEL_TIMEOUT_SECONDS", "300"))

# Transient network failures that are worth retrying automatically rather
# than crashing the whole run: a client-side read timeout, a dropped
# connection, or an HTTP error (this also catches provider-side gateway
# timeouts like NVIDIA's 504 -- see model_provider.py history). This
# intentionally also matches non-retryable HTTPErrors like a 401/403; a
# wasted retry or two on those is harmless (they'll fail again identically
# and surface the same error), and it keeps this list simple rather than
# needing to parse status codes out of every provider's exception shape.
_RETRYABLE_EXCEPTIONS = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    requests.exceptions.HTTPError,
)


def _with_retry(llm):
    """
    Wrap a chat model with LangChain's built-in Runnable.with_retry() so a
    single transient network blip doesn't kill an entire agent run.

    WHY THIS EXISTS: two of the three crashes hit while building this
    integration were exactly this class of problem -- a client read
    timeout and, separately, NVIDIA's gateway returning a 504 mid-
    generation. Neither was a logic error; both were "ask again and it'll
    probably work." Retrying at the model layer (rather than, say, only
    in the CLI's checkpoint/resume loop) means a transient blip costs a
    few seconds and a log line instead of an entire aborted run + manual
    `--resume`.

    3 attempts, exponential backoff with jitter -- .with_retry()'s
    defaults are reasonable here and deliberately not hand-tuned further.
    """
    return llm.with_retry(
        retry_if_exception_type=_RETRYABLE_EXCEPTIONS,
        wait_exponential_jitter=True,
        stop_after_attempt=3,
    )

# provider_key -> (init_chat_model model string, required env var for the key)
MODEL_MAP = {
    "deepseek": ("deepseek:deepseek-chat", "DEEPSEEK_API_KEY"),
    "anthropic": ("anthropic:claude-sonnet-5", "ANTHROPIC_API_KEY"),
    "openai": ("openai:gpt-4.1", "OPENAI_API_KEY"),
    # Default pinned to the model exercised in the reference notebook.
    # NOTE: client.get_available_models() showed "z-ai/glm-5.2" is NOT in
    # the catalog's listing (it still worked, with a "type is unknown"
    # warning -- likely a very-recently-added model not yet fully indexed).
    # "z-ai/glm-5.1" is the closest catalog entry confirmed non-deprecated
    # as of that same listing. Override via NVIDIA_MODEL env var if
    # "z-ai/glm-5.2" starts failing outright rather than just warning.
    "nvidia": ("z-ai/glm-5.2", "NVIDIA_API_KEY"),
}


def get_model(provider: str | None = None, **overrides):
    """
    Returns a chat model instance for the configured provider.

    provider: explicit override. If omitted, reads MODEL_PROVIDER env var,
              defaulting to 'deepseek' (cheap PoC default per requirements).
    overrides: passed through to init_chat_model / ChatNVIDIA (e.g. temperature=0).
    """
    provider = provider or os.environ.get("MODEL_PROVIDER", "deepseek")

    if provider not in MODEL_MAP:
        raise ValueError(
            f"Unknown provider '{provider}'. Known providers: "
            f"{list(MODEL_MAP.keys())}. Add new ones to MODEL_MAP."
        )

    model_string, required_env = MODEL_MAP[provider]

    if required_env not in os.environ:
        raise EnvironmentError(
            f"Provider '{provider}' requires {required_env} to be set."
        )

    if provider == "nvidia":
        # Local import so the rest of the app doesn't hard-require this
        # package just because it's installed for one provider.
        from langchain_nvidia_ai_endpoints import ChatNVIDIA

        model_id = os.environ.get("NVIDIA_MODEL", model_string)

        # Sensible defaults mirrored from the reference notebook; any of
        # these can still be overridden by callers via **overrides.
        nvidia_defaults = {
            "temperature": 1,
            "top_p": 1,
            "max_completion_tokens": 64000,
            "seed": 42,
        }
        nvidia_defaults.update(overrides)

        llm = ChatNVIDIA(
            model=model_id,
            api_key=os.environ[required_env],
            **nvidia_defaults,
        )

        # ---------------- 504/empty-body error masking monkeypatch ----------------
        # From the traceback hit during this integration: ChatNVIDIA's
        # internal client._try_raise(response) unconditionally calls
        # response.json() to build its error message. A gateway-level
        # failure (e.g. NVIDIA's 504 with an empty body) has no JSON body
        # to parse, so the REAL error ("504 Server Error: Gateway Timeout")
        # gets masked by a confusing `JSONDecodeError: Expecting value`
        # instead. Patched here to fall back to the real HTTPError when
        # the body isn't JSON.
        #
        # NOTE: patched against `type(llm._client)` (the real runtime
        # class) rather than a hardcoded `langchain_nvidia_ai_endpoints.
        # _common.SomeClassName` -- I only have the traceback showing this
        # method lives in _common.py as `_try_raise`, not that module's
        # actual source, so I'm deliberately not guessing an exact class
        # name that could silently no-op or AttributeError if wrong.
        # Re-verify this still applies if langchain-nvidia-ai-endpoints is
        # upgraded (same spirit as this file's other NOTE above).
        _client_cls = type(llm._client)
        if hasattr(_client_cls, "_try_raise") and not getattr(
            _client_cls, "_patched_for_readable_errors", False
        ):
            _orig_try_raise = _client_cls._try_raise

            def _patched_try_raise(self, response, *args, **kwargs):
                try:
                    response.raise_for_status()
                except requests.exceptions.HTTPError as http_err:
                    try:
                        response.json()
                    except (ValueError, requests.exceptions.JSONDecodeError):
                        raise http_err from None
                return _orig_try_raise(self, response, *args, **kwargs)

            _client_cls._try_raise = _patched_try_raise
            _client_cls._patched_for_readable_errors = True
        # ---------------------------------------------------------------------------

        # ChatNVIDIA's public constructor has no `timeout=` kwarg -- anything
        # passed in gets silently absorbed into model_kwargs (and sent as a
        # bogus request field) instead of configuring the HTTP client. The
        # underlying client defaults to a 60s read timeout, which a
        # reasoning model asked for max_completion_tokens=64000 can easily
        # exceed mid-generation (this is what caused the ReadTimeout crash
        # during a deepagents subagent call). Set it directly on the
        # (mutable) private client attributes instead.
        timeout_seconds = overrides.get("timeout", DEFAULT_TIMEOUT_SECONDS)
        llm._client.timeout = timeout_seconds
        llm._async_client.timeout = timeout_seconds

        return _with_retry(llm)

    # For every other provider, init_chat_model's `timeout` kwarg is passed
    # straight through to the underlying SDK client (OpenAI/Anthropic/
    # DeepSeek all honor it directly, unlike ChatNVIDIA above). Apply the
    # same 5-minute default here so no provider is left on a 60s default.
    overrides.setdefault("timeout", DEFAULT_TIMEOUT_SECONDS)
    return _with_retry(init_chat_model(model_string, **overrides))
