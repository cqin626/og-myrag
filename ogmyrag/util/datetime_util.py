from datetime import datetime
from zoneinfo import ZoneInfo

def get_formatted_current_datetime(timezone: str) -> str:
   return datetime.now(ZoneInfo(timezone)).strftime('%Y-%m-%d %H:%M:%S')