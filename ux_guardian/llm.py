"""Official OpenAI SDK adapter. Constructed only by explicit live CLI paths."""

import os

from openai import AsyncOpenAI, OpenAIError
from pydantic import ValidationError

from ux_guardian.config import Config
from ux_guardian.diff.analyzer import Predictions


class OpenAiLlmClient:
    def __init__(self, config: Config, client: AsyncOpenAI | None = None) -> None:
        if config.llm_provider != "openai":
            raise ValueError("Unsupported llm_provider; use openai")
        key = os.environ.get("LLM_API_KEY")
        if client is None and not key:
            raise ValueError("Set LLM_API_KEY in the environment or ignored .env")
        self.client = client or AsyncOpenAI(api_key=key, max_retries=0, timeout=60)
        self.model = config.llm_model

    async def list_models(self) -> list[str]:
        try:
            page = await self.client.models.list()
            return sorted(model.id for model in page.data)
        except OpenAIError as error:
            raise ValueError(
                "OpenAI model discovery failed; credentials and body omitted"
            ) from error

    async def complete_json(self, *, system: str, prompt: str) -> dict[str, object]:
        try:
            response = await self.client.responses.parse(
                model=self.model,
                instructions=system,
                input=prompt,
                text_format=Predictions,
                max_output_tokens=2000,
                store=False,
            )
        except (OpenAIError, ValidationError) as error:
            raise ValueError("OpenAI inference failed; credentials and body omitted") from error
        if response.output_parsed is None:
            raise ValueError("OpenAI returned no validated output (refused or incomplete)")
        return response.output_parsed.model_dump()

    async def close(self) -> None:
        await self.client.close()
