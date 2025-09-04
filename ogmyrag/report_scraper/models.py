from enum import Enum
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class PDFDocument:
    url: str
    name: str


@dataclass
class Announcement:
    company: str
    pdfs: List[PDFDocument]
    is_amended: bool = False
    announced_date: Optional[str] = None


class ReportType(Enum):
    ANNUAL    = ("Annual Report & CG Report", "AR,ARCO", "annual_reports", None)
    QUARTERLY = ("Quarterly Report", "QR", "quarterly_reports", None)
    IPO       = ("Initial Public Offering", "IO", "ipo_reports", "IO3")

    def __init__(self, keyword: str, category: str, collection: str, subtype: Optional[str]):
        self.keyword = keyword
        self.category = category
        self.collection = collection
        self.subtype = subtype