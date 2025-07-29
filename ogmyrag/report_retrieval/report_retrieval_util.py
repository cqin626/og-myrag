from ..util import get_clean_json
from typing import Any

from ..util import get_normalized_string, get_formatted_current_datetime

def get_formatted_company_data(
    document: str,
    document_name: str,
    document_type: str,
    company_name: str,
    published_at: str,
    timezone_str: str = "Asia/Kuala_Lumpur",
) -> dict[str, Any]:
    return {
        "name": get_normalized_string(document_name),
        "type": get_normalized_string(document_type),
        "from_company": get_normalized_string(company_name),
        "created_at": get_formatted_current_datetime(timezone_str),
        "is_parsed": False,
        "content": document,
        "published_at": published_at,
    }