from ..util import get_clean_json
from typing import Any, List
import re

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


def chunk_markdown(text: str) -> List[str]:
    """
    Split Markdown into logical chunks for embedding.
    • Each bullet line (“- ” or “* ”) becomes its own chunk.
    • Paragraphs separated by blank lines become separate chunks.
    """
    chunks: List[str] = []
    buffer: List[str] = []
    for line in text.splitlines():
        s = line.strip()
        if re.match(r"^[-*]\s+", s):
            if buffer:
                chunks.append(" ".join(buffer))
                buffer = []
            chunks.append(s)
        elif not s:
            if buffer:
                chunks.append(" ".join(buffer))
                buffer = []
        else:
            buffer.append(s)
    if buffer:
        chunks.append(" ".join(buffer))
    return chunks


def clean_markdown_response(text: str) -> str:
    """Strip ```markdown fences if present."""
    if text.startswith("```markdown"):
        text = text[len("```markdown"):].strip()
    if text.endswith("```"):
        text = text[:-3].strip()

    if text.startswith("```json"):
        text = text[len("```json"):].strip()
    if text.endswith("```"):
        text = text[:-3].strip()

    return text