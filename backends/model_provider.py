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
"""
import os

from langchain.chat_models import init_chat_model

# provider_key -> (init_chat_model model string, required env var for the key)
MODEL_MAP = {
    "deepseek": ("deepseek:deepseek-chat", "DEEPSEEK_API_KEY"),
    "anthropic": ("anthropic:claude-sonnet-5", "ANTHROPIC_API_KEY"),
    "openai": ("openai:gpt-4.1", "OPENAI_API_KEY"),
}


def get_model(provider: str | None = None, **overrides):
    """
    Returns a chat model instance for the configured provider.

    provider: explicit override. If omitted, reads MODEL_PROVIDER env var,
              defaulting to 'deepseek' (cheap PoC default per requirements).
    overrides: passed through to init_chat_model (e.g. temperature=0).
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

    return init_chat_model(model_string, **overrides)
