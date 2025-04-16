import asyncio
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