from unittest.mock import patch

from src.utils.langsmith_tracing import langsmith_tracing_enabled, traced_openai_client


def test_tracing_is_disabled_without_an_explicit_flag_and_key(monkeypatch) -> None:
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    client = object()
    assert not langsmith_tracing_enabled()
    assert traced_openai_client(client) is client


def test_tracing_wraps_openai_only_when_explicitly_configured(monkeypatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    client, wrapped = object(), object()
    with patch("langsmith.wrappers.wrap_openai", return_value=wrapped) as wrapper:
        assert traced_openai_client(client) is wrapped
    wrapper.assert_called_once_with(client)
