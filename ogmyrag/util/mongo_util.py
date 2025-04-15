from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from typing import Any

def get_formatted_company_data(
   document: str,
   document_name: str,
   document_type: str,
   company_name: str,
   timezone_str: str = "Asia/Kuala_Lumpur"
   )-> dict[str, Any]:
   local_time = datetime.now(ZoneInfo(timezone_str)).strftime('%Y-%m-%d %H:%M:%S')
   return {
      "name": document_name.upper(),
      "type": document_type.upper(),
      "from_company": company_name.upper(),
      "created_at": local_time,
      "isParsed" : False,
      "content": document
   }