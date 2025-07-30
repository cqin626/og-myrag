import re
import logging
from typing import List
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from ..report_scraper.session import BaseScraper
from ..report_scraper.models import Announcement, PDFDocument

scraper_logger = logging.getLogger("scraper")


class PDFExtractor(BaseScraper):
    """
    Given an announcement URL, scrape out all PDFDocument entries.
    """
    def extract(self, announcement_url: str) -> Announcement:
        scraper_logger.debug("Extracting PDFs from %s", announcement_url)

        # Step 1: load main page & find iframe
        html        = self.cf.get_html(announcement_url)
        soup        = BeautifulSoup(html, "html.parser")
        iframe      = soup.find("iframe", id="bm_ann_detail_iframe")
        if not iframe:
            raise ValueError(f"No detail iframe on {announcement_url}")

        # Step 2: load iframe detail page
        detail_url  = iframe["src"]
        detail_html = self.cf.get_html(detail_url)
        dsoup       = BeautifulSoup(detail_html, "html.parser")

        # check if amended
        amended = dsoup.find("p", class_="ven_alert") is not None

        # get company name
        td = dsoup.find("td", class_="company_name")
        company = td.get_text(strip=True).replace(" ", "_") if td else "UNKNOWN_COMPANY"

        # get announced date
        label_td = dsoup.find("td", class_="formContentLabelH", string=re.compile(r"Date\s*Announced", re.IGNORECASE))
        if label_td:
            data_td = label_td.find_next_sibling("td", class_="formContentDataH")
            if data_td:
                announced_date = data_td.get_text(strip=True)

        # collect PDFs
        pdfs: List[PDFDocument] = []
        for a in dsoup.select("p.att_download_pdf a[href]"):
            href = urljoin("https://disclosure.bursamalaysia.com/", a["href"])
            name = a.get_text(strip=True).replace(" ", "_")
            pdfs.append(PDFDocument(url=href, name=name))

        return Announcement(company=company, pdfs=pdfs, is_amended=amended, announced_date=announced_date)