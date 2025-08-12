from datetime import datetime
from zoneinfo import ZoneInfo


def get_formatted_current_datetime(timezone: str) -> str:
    return datetime.now(ZoneInfo(timezone)).strftime("%Y-%m-%d %H:%M:%S")


def get_current_datetime(timezone: str = "Asia/Kuala_Lumpur") -> datetime:
    return datetime.now(ZoneInfo(timezone))
