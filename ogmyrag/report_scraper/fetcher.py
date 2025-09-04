import time
import logging
from typing import List, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from ..report_scraper.session import BaseScraper
from ..report_scraper.models import ReportType

scraper_logger = logging.getLogger("scraper")


class AnnouncementFetcher(BaseScraper):
    """
    Fetches paginated announcement URLs for a given ReportType and year.
    """
    def fetch(self, report_type: ReportType, year: Optional[int] = None, company_name: Optional[str] = None, sector_name: Optional[str] = None, per_page: int = 20) -> List[str]:
        links = []
        if report_type == ReportType.IPO:
            # IPO reports fetching
            params = {
                "ann_type": "company",
                "cat":      report_type.category,
                "sub_type": report_type.subtype,
                "per_page": per_page,
                "page":     1,
            }
            if sector_name:  # only add when provided
                params["sec"] = sector_name
                params["mkt"] = "MAIN-MKT"

        else:
            # Annual and Quarterly reports fetching
            if year is None:
                raise ValueError(f"Year is required for {report_type.name}")
            params = {
                "ann_type": "company",
                "keyword":  f"{report_type.keyword} - {year}",
                "cat":      report_type.category,
                "per_page": per_page,
                "page":     1,
            }
            if sector_name:  # only add when provided
                params["sec"] = sector_name
                params["mkt"] = "MAIN-MKT"
            

        # if user specified a company_name, find its code
        if company_name:
            company_code = self._find_company_code(company_name)
           
            if not company_code:
                raise ValueError(f"Company '{company_name}' not found")
            params["company"] = company_code
            scraper_logger.info("Using company code: %s (%s)", company_code, company_name)

        scraper_logger.info("Fetching %s links (Year: %s, Company: %s)...",
                    report_type.keyword,
                    str(year) if year is not None else "N/A",
                    company_name or "ALL")

        while True:
            resp = self.cf.get_json(self.API_URL, params=params)
            data = resp.get("data", [])
            if not data:
                break

            for row in data:
                raw_html = row[3]  # announcement link HTML snippet
                soup     = BeautifulSoup(raw_html, "html.parser")
                a        = soup.find("a", href=True)
                if not a:
                    continue
                href = a["href"]
                if href.startswith("/"):
                    href = urljoin("https://www.bursamalaysia.com", href)
                links.append(href)

            if len(data) == per_page: # change to (<) to scrape all (testing purpose: set to 20 (==))
                break

            params["page"] += 1
            time.sleep(0.2)

        scraper_logger.info("Found %d announcement links", len(links))
        return links
    
    def _find_company_code(self, company_name: str) -> str:
        html = self.cf.get_html("https://www.bursamalaysia.com/market_information/announcements/company_announcement", extra_headers=None)
        soup = BeautifulSoup(html, "html.parser")

        # Find the company code in the dropdown
        select = soup.find("select", id="inCompany")
        if not select:
            scraper_logger.error("Could not find company <select> on page")
            return None
        
        target = company_name.strip().lower()
        options = select.find_all("option")

        # collect all matching options
        matches: List[str] = []

        for option in options:
            text = option.get_text(strip=True).lower()
            value = option.get("value", "").strip()
            if not value:
                continue

            if text == target or target in text:
                matches.append(value)
        
        if not matches:
            return None
        
        # 1) exactly 4 digits
        for code in matches:
            if len(code) == 4 and code.isdigit():
                return code
        # 2) any numeric
        for code in matches:
            if code.isdigit():
                return code
        # 3) any length-4
        for code in matches:
            if len(code) == 4:
                return code
        # 4) fallback
        return matches[0]