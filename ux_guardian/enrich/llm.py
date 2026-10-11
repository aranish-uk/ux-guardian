"""OpenAI structured-output adapter implementing the existing LlmClient protocol.

https://developers.openai.com/api/docs/guides/structured-outputs
"""

import json
import os

import httpx

from ux_guardian.enrich.fix import FixSuggestion
from ux_guardian.security import redact


class OpenAiFixClient:
    """One request per completion, no automatic retries; only FR9's output schema."""

    def __init__(
        self, *, model: str | None = None, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.model = model or os.environ.get("LLM_MODEL", "gpt-4.1-mini")
        self._transport = transport

    async def complete_json(self, *, system: str, prompt: str) -> dict[str, object]:
        key = os.environ.get("LLM_API_KEY")
        if not key:
            raise RuntimeError("LLM_API_KEY is required for fix suggestions")
        async with httpx.AsyncClient(
            transport=self._transport, timeout=90, follow_redirects=False
        ) as client:
            try:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json={
                        "model": self.model,
                        "store": False,
                        "messages": [
                            {"role": "system", "content": redact(system)},
                            {"role": "user", "content": redact(prompt)},
                        ],
                        "response_format": {
                            "type": "json_schema",
                            "json_schema": {
                                "name": "fix_suggestion",
                                "strict": True,
                                "schema": FixSuggestion.model_json_schema(),
                            },
                        },
                    },
                )
                response.raise_for_status()
                message = response.json()["choices"][0]["message"]
                if not isinstance(message, dict) or message.get("refusal"):
                    raise ValueError("Refused completion")
                parsed = json.loads(message["content"])
                return FixSuggestion.model_validate(parsed).model_dump()
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
                raise RuntimeError("OpenAI fix completion failed") from None
