import asyncio
import json
import re
from functools import wraps

def limit_concurrency(max_concurrent_tasks: int):
    semaphore = asyncio.Semaphore(max_concurrent_tasks)

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            async with semaphore:
                return await func(*args, **kwargs)
        return wrapper
    return decorator

def get_clean_json(text: str) -> dict:
    # Step 1: Trim whitespace
    text = text.strip()

    # Step 2: Remove markdown code block if present (```json ... ```)
    if text.startswith("```json") or text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    # Step 3: Try to extract valid JSON between first '{' and last '}'
    try:
        start = text.index('{')
        end = text.rindex('}') + 1
        json_str = text[start:end]
        return json.loads(json_str)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"[Error] JSON parsing failed: {e}")
        return {}