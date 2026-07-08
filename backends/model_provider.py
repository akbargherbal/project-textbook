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
    NVIDIA_API_KEY   -- required, your NVIDIA API Catalog key (starts "nvapi-")
    NVIDIA_MODEL     -- optional, overrides the default model id below
"""

import os

from langchain.chat_models import init_chat_model

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
            # "seed": 42,
        }
        nvidia_defaults.update(overrides)

        return ChatNVIDIA(
            model=model_id,
            api_key=os.environ[required_env],
            **nvidia_defaults,
        )

    return init_chat_model(model_string, **overrides)
