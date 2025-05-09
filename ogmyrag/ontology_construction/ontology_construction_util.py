from typing import Any
from ..util import get_formatted_current_datetime

def get_new_version(current_version: str, update_type: str) -> str:
    major, minor, patch = map(int, current_version.split('.'))
    
    if update_type == "PATCH":
        patch += 1
    elif update_type == "MINOR":
        minor += 1
        patch = 0
    elif update_type == "MAJOR":
        major += 1
        minor = 0
        patch = 0
    else:
        raise ValueError(f"Unknown update_type: {update_type}")

    return f"{major}.{minor}.{patch}"


def get_formatted_cq_record(
   cq: dict, 
   model: str, 
   purpose: str, 
   version: str,
   timezone: str = "Asia/Kuala_Lumpur"
   ) -> dict[str, Any]:
      return {
        "competency_questions": cq,
        "created_at": get_formatted_current_datetime(timezone),
		"created_with_model": model,
		"created_with_purpose": purpose,
        "is_latest": True,
		"version": version
      }