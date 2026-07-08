"""
tests/backends/test_model_provider.py

Env-var-driven branching; mock init_chat_model and ChatNVIDIA so no real
SDK/network call happens.

DEFAULT_TIMEOUT_SECONDS is computed once, at import time, from
MODEL_TIMEOUT_SECONDS. To test overrides of that env var we reload the
module after setting the env var, then reload it again afterward (in a
fixture) so later tests aren't left looking at a stale timeout default.
"""

import importlib

import pytest

import backends.model_provider as model_provider

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reload_model_provider_after_each_test():
    """Some tests reload the module to pick up a fresh
    MODEL_TIMEOUT_SECONDS env var at import time; always reload back to
    a clean state afterward so later tests see the real default."""
    yield
    importlib.reload(model_provider)


def test_unknown_provider_raises(monkeypatch):
    with pytest.raises(ValueError, match="Unknown provider"):
        model_provider.get_model(provider="not-a-real-provider")


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(EnvironmentError, match="DEEPSEEK_API_KEY"):
        model_provider.get_model(provider="deepseek")


def test_deepseek_calls_init_chat_model_with_default_timeout(monkeypatch, mocker):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake")
    mock_init = mocker.patch("backends.model_provider.init_chat_model")
    model_provider.get_model(provider="deepseek")
    args, kwargs = mock_init.call_args
    assert args[0] == "deepseek:deepseek-chat"
    assert kwargs["timeout"] == 300.0


def test_anthropic_provider_requires_anthropic_api_key(monkeypatch, mocker):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
        model_provider.get_model(provider="anthropic")


def test_openai_provider_calls_init_chat_model_with_correct_model_string(
    monkeypatch, mocker
):
    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    mock_init = mocker.patch("backends.model_provider.init_chat_model")
    model_provider.get_model(provider="openai")
    args, kwargs = mock_init.call_args
    assert args[0] == "openai:gpt-4.1"


def test_nvidia_provider_sets_client_timeouts(monkeypatch, mocker):
    monkeypatch.setenv("NVIDIA_API_KEY", "fake")
    fake_llm = mocker.MagicMock()
    fake_llm._client = mocker.MagicMock()
    fake_llm._async_client = mocker.MagicMock()
    mocker.patch("langchain_nvidia_ai_endpoints.ChatNVIDIA", return_value=fake_llm)
    model_provider.get_model(provider="nvidia")
    assert fake_llm._client.timeout == 300.0
    assert fake_llm._async_client.timeout == 300.0


def test_nvidia_provider_timeout_override_sets_client_attrs_directly(
    monkeypatch, mocker
):
    """get_model(timeout=45) must set the REAL http client timeout on the
    (mutable) private client attributes directly -- this is what actually
    fixes the ReadTimeout bug described in the module's docstring, since
    ChatNVIDIA's public constructor has no working timeout= kwarg (any
    timeout passed to the constructor is silently absorbed into
    model_kwargs as a bogus request field rather than configuring the
    HTTP client, so it ALSO still flows through to the constructor call
    below -- harmlessly, per that same docstring -- but only the direct
    attribute assignment is what actually takes effect)."""
    monkeypatch.setenv("NVIDIA_API_KEY", "fake")
    fake_llm = mocker.MagicMock()
    fake_llm._client = mocker.MagicMock()
    fake_llm._async_client = mocker.MagicMock()
    mock_chat_nvidia = mocker.patch(
        "langchain_nvidia_ai_endpoints.ChatNVIDIA", return_value=fake_llm
    )
    model_provider.get_model(provider="nvidia", timeout=45)

    # The real fix: both client objects get the override timeout set
    # directly, regardless of what was passed to the constructor.
    assert fake_llm._client.timeout == 45
    assert fake_llm._async_client.timeout == 45

    # Regardless of whether "timeout" happens to appear in the ctor
    # kwargs bag, it must never be relied upon there -- the direct
    # attribute assignment above is the only thing that actually
    # configures the HTTP client.
    mock_chat_nvidia.assert_called_once()


def test_nvidia_provider_uses_default_model_and_env_var_key(monkeypatch, mocker):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-fake")
    monkeypatch.delenv("NVIDIA_MODEL", raising=False)
    fake_llm = mocker.MagicMock()
    fake_llm._client = mocker.MagicMock()
    fake_llm._async_client = mocker.MagicMock()
    mock_chat_nvidia = mocker.patch(
        "langchain_nvidia_ai_endpoints.ChatNVIDIA", return_value=fake_llm
    )
    model_provider.get_model(provider="nvidia")
    _, ctor_kwargs = mock_chat_nvidia.call_args
    assert ctor_kwargs["model"] == "z-ai/glm-5.2"
    assert ctor_kwargs["api_key"] == "nvapi-fake"


def test_nvidia_model_env_var_overrides_default(monkeypatch, mocker):
    monkeypatch.setenv("NVIDIA_API_KEY", "fake")
    monkeypatch.setenv("NVIDIA_MODEL", "some-other-model")
    fake_llm = mocker.MagicMock()
    fake_llm._client = mocker.MagicMock()
    fake_llm._async_client = mocker.MagicMock()
    mock_chat_nvidia = mocker.patch(
        "langchain_nvidia_ai_endpoints.ChatNVIDIA", return_value=fake_llm
    )
    model_provider.get_model(provider="nvidia")
    _, ctor_kwargs = mock_chat_nvidia.call_args
    assert ctor_kwargs["model"] == "some-other-model"


def test_model_timeout_seconds_env_var_overrides_default_for_non_nvidia(
    monkeypatch, mocker
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake")
    monkeypatch.setenv("MODEL_TIMEOUT_SECONDS", "45")
    importlib.reload(model_provider)

    mock_init = mocker.patch("backends.model_provider.init_chat_model")
    model_provider.get_model(provider="deepseek")
    _, kwargs = mock_init.call_args
    assert kwargs["timeout"] == 45.0


def test_provider_falls_back_to_model_provider_env_var(monkeypatch, mocker):
    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    mock_init = mocker.patch("backends.model_provider.init_chat_model")
    model_provider.get_model()
    args, _ = mock_init.call_args
    assert args[0] == "openai:gpt-4.1"


def test_provider_falls_back_to_deepseek_when_nothing_set(monkeypatch, mocker):
    monkeypatch.delenv("MODEL_PROVIDER", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake")
    mock_init = mocker.patch("backends.model_provider.init_chat_model")
    model_provider.get_model()
    args, _ = mock_init.call_args
    assert args[0] == "deepseek:deepseek-chat"
