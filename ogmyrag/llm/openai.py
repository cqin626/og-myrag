import os
import logging
from datetime import datetime
from openai import (
    AsyncOpenAI,
    APIConnectionError,
    RateLimitError,
    APITimeoutError,
    OpenAIError,
)
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
from ..util import limit_concurrency
from ..base import BaseLLMClient

openai_logger = logging.getLogger("openai")


class OpenAIAsyncClient(BaseLLMClient):
    def __init__(self, api_key: str | None = None):
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            openai_logger.error("OPENAI_API_KEY is not set.")
            raise Exception("OPENAI_API_KEY is required but missing.")
        self.client = AsyncOpenAI(api_key=api_key)

    @limit_concurrency(max_concurrent_tasks=20)
    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type(
            (RateLimitError, APIConnectionError, APITimeoutError)
        ),
    )
    async def fetch_response(
        self, model: str, user_prompt: str, system_prompt: str | None = None, **kwargs
    ):
        start = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        openai_logger.info(f"Started at {start} for prompt: {user_prompt[:30]}...")

        messages = (
            [{"role": "developer", "content": system_prompt}] if system_prompt else []
        )
        messages.append({"role": "user", "content": user_prompt})

        openai_logger.info(f"Sending query to {model} using ResponsesAPI")

        try:
            response = await self.client.responses.create(
                model=model, input=messages, **kwargs
            )
        except (APIConnectionError, RateLimitError, APITimeoutError, OpenAIError) as e:
            openai_logger.error(f"OpenAI API Error: {e}")
            raise

        openai_logger.debug(f"Received response from ResponsesAPI:\n {str(response)}")
        end = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        openai_logger.info(f"Ended at {end} for prompt: {user_prompt[:30]}...")

        return response
