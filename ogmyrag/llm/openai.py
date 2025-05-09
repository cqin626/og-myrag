import os
import logging
from tqdm.asyncio import tqdm

from openai import(
   AsyncOpenAI,
   APIConnectionError,
   RateLimitError,
   APITimeoutError,
   OpenAIError
)

from tenacity import (
   retry,
   stop_after_attempt,
   wait_exponential,
   retry_if_exception_type
)

from ..util import limit_concurrency

openai_logger = logging.getLogger("openai")

global_openai_async_client: AsyncOpenAI | None = None

def get_openai_async_client_instance() -> AsyncOpenAI:
   global global_openai_async_client
   if global_openai_async_client is None:
      try:
         api_key = os.getenv("OPENAI_API_KEY")
         global_openai_async_client = AsyncOpenAI(api_key=api_key)
      except KeyError:
         openai_logger.warning("OPENAI_API_KEY is not properly set!")
         raise Exception("OPENAI_API_KEY is required but not properly set in environment variables.")
   return global_openai_async_client

@limit_concurrency(max_concurrent_tasks=5)
@retry(
   stop=stop_after_attempt(5),
   wait=wait_exponential(multiplier=1, min=4, max=10),
   retry=retry_if_exception_type((RateLimitError, APIConnectionError, APITimeoutError)),
)
async def fetch_completion_openai(
   model: str, 
   user_prompt: str,
   system_prompt: str | None,
   history_messages: list[dict[str,str]] | None,
   max_tokens: int | None,
   temperature: float | None,
   ) -> str:
    client = get_openai_async_client_instance()
    
    messages = [{"role": "system", "content": system_prompt}] if system_prompt else []
    messages += history_messages or []
    messages.append({"role": "user", "content": user_prompt})
    
    openai_logger.debug(f"Sending query to {model} ...")
    openai_logger.debug("Current conversation:\n\n" + "\n".join(
      f"{msg['role']}: {msg['content']}" for msg in messages
    ))
    
    try:
       
      async for _ in tqdm([None], desc=f"Processing query for {model}", total=1): 
         response = await client.chat.completions.create(
            model=model, 
            messages=messages, 
            **{key: value for key, value in {"temperature": temperature, "max_tokens": max_tokens}.items() if value is not None}
         )
    except APIConnectionError as e:
      openai_logger.error(f"OpenAI API Connection Error: {e}")
      raise
    except RateLimitError as e:
      openai_logger.error(f"OpenAI API Rate Limit Error: {e}")
      raise
    except APITimeoutError as e:
      openai_logger.error(f"OpenAI API Timeout Error: {e}")
      raise
    except OpenAIError as e:
      openai_logger.error(f"OpenAI API Call Failed: {e}")
      raise

    return response.choices[0].message.content


@limit_concurrency(max_concurrent_tasks=5)
@retry(
   stop=stop_after_attempt(5),
   wait=wait_exponential(multiplier=1, min=4, max=10),
   retry=retry_if_exception_type((RateLimitError, APIConnectionError, APITimeoutError)),
)
async def fetch_responses_openai(
   model: str, 
   user_prompt: str,
   system_prompt: str | None,
   **kwargs
   ) -> str:
    client = get_openai_async_client_instance()
    
    messages = [{"role": "developer", "content": system_prompt}] if system_prompt else []
    messages.append({"role": "user", "content": user_prompt})
    
    openai_logger.info(f"Sending query to {model} using ResponsesAPI")
    
    try:
      response = await client.responses.create(
         model=model, 
         input=messages, 
         **kwargs
      )
    except APIConnectionError as e:
      openai_logger.error(f"OpenAI API Connection Error: {e}")
      raise
    except RateLimitError as e:
      openai_logger.error(f"OpenAI API Rate Limit Error: {e}")
      raise
    except APITimeoutError as e:
      openai_logger.error(f"OpenAI API Timeout Error: {e}")
      raise
    except OpenAIError as e:
      openai_logger.error(f"OpenAI API Call Failed: {e}")
      raise

    openai_logger.info(f"Received response from ResponsesAPI:\n {response}")
    return response
