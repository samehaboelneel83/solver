"""The assistant reports model timeouts as an actionable service failure."""

from dataclasses import replace
from urllib.error import URLError

import pytest

from app.agent import core


@pytest.mark.parametrize(
    "failure",
    [TimeoutError("timed out"), URLError(TimeoutError("timed out"))],
)
def test_llm_timeout_has_service_and_retry_guidance(monkeypatch, failure):
    settings = replace(core.Settings(), base_url="http://model.local/v1", timeout=12)

    def timeout(_request, timeout):
        assert timeout == 12
        raise failure

    monkeypatch.setattr(core.urllib.request, "urlopen", timeout)
    with pytest.raises(core.LlmError, match="model.local.*12 seconds.*healthy"):
        core.llm_chat(settings, [{"role": "user", "content": "test"}], native=False)
