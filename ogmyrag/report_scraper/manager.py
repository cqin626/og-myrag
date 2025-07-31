import asyncio
import logging
from threading import Thread
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

from ..report_scraper.fetcher   import AnnouncementFetcher
from ..report_scraper.extractor import PDFExtractor
from ..report_scraper.storage   import StorageManager, AsyncStorageManager
from ..report_scraper.models    import ReportType, Announcement

scraper_logger = logging.getLogger("scraper")

# Background event loop for async storage
_background_loop = asyncio.new_event_loop()

def _start_background_loop():
    asyncio.set_event_loop(_background_loop)
    _background_loop.run_forever()

_thread = Thread(target=_start_background_loop, daemon=True)
_thread.start()

def run_async(coro):
    future = asyncio.run_coroutine_threadsafe(coro, _background_loop)
    return future.result()


class ScraperManager:
    """
    Orchestrates fetching, extraction, and storage, with multithreading.
    """
    def __init__(
        self,
        storage_manager: AsyncStorageManager,
        #report_types:    List[ReportType],
        max_workers:     int = 5,
        dry_run:         bool = True  # If True, do not save to storage
    ):
        self.fetcher     = AnnouncementFetcher()
        self.extractor   = PDFExtractor()
        self.storage     = storage_manager
        #self.report_types = report_types
        self.max_workers = max_workers
        
        self.dry_run = dry_run  # Set to True for dry run without saving

    def _process_link(self, rtype: ReportType, url: str, year: int):
        try:
            ann = self.extractor.extract(url)
            action = "Amended" if ann.is_amended else "Original"
            
            
            if self.dry_run:
                scraper_logger.info(
                    "[DRY RUN] %s %s → %d PDFs for %s",
                    action,
                    rtype.name,
                    len(ann.pdfs),
                    ann.company
                )
                # Show all the PDF names
                for pdf in ann.pdfs:
                    scraper_logger.info("  - %s", pdf.name)
                return  
            
            # run the async save in its own event loop
            run_async(self.storage.save(ann, rtype, year))
            scraper_logger.info(
                "%s %s for %s (%d PDFs) is in the database",
                action,
                rtype.keyword,
                ann.company,
                len(ann.pdfs)
            )


        except Exception as e:
            scraper_logger.error("Failed %s: %s", url, e)

    def run_one(self, rtype: ReportType, year: Optional[int] = None, company_name: Optional[str] = None):
        year = str(year) if year is not None else "N/A"
        scraper_logger.info("=== %s ===", rtype.keyword)
        all_links = self.fetcher.fetch(rtype, year, company_name)#[::-1] # reverse to process oldest first
            
        links = all_links[:5] # Limit to first 5 for dry run

        if not links:
            scraper_logger.info("No links for %s %s", rtype.keyword, year)
            return

        scraper_logger.info("Processing %d links with %d workers", len(links), self.max_workers)
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [
                executor.submit(self._process_link, rtype, url, year)
                for url in links
            ]
            for fut in as_completed(futures):
                # results & errors are logged inside _process_link
                _ = fut.result()




