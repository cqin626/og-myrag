import logging
from datetime import datetime
from pymongo import MongoClient
import gridfs

from ..report_scraper.session import CloudflareSession
from ..report_scraper.models import Announcement, ReportType, PDFDocument

scraper_logger = logging.getLogger("scraper")


class StorageManager:
    """
    Save PDF bytes to GridFS and metadata to MongoDB collections.
    """
    def __init__(self, mongo_uri: str, db_name: str):
        self.client = MongoClient(mongo_uri)
        self.db     = self.client[db_name]
        self.fs     = gridfs.GridFS(self.db)
        scraper_logger.info("Connected to MongoDB database: %s", db_name)

    def exists(self, collection: str, filename: str, year: int) -> bool:
        coll = self.db[collection]
        return coll.find_one({"filename": filename, "year": year}) is not None

    def save(self, announcement: Announcement, report_type: ReportType, year: int):
        coll = self.db[report_type.collection]
        cf   = CloudflareSession()

        for pdf in announcement.pdfs:
            # always store; use filename + year + is_amended to avoid duplicates
            key = {
                "filename": pdf.name,
                "year": year,
                "is_amended": announcement.is_amended
            }

            if coll.find_one(key):
                scraper_logger.warning("Already exists: %s (amended = %s) for %d", pdf.name, announcement.is_amended, year)


            scraper_logger.info("Downloading %s", pdf.name)
            content = cf.get_bytes(pdf.url)
            file_id = self.fs.put(content, filename=pdf.name)

            # insert metadata + amendment flag + processing markers
            coll.insert_one({
                **key,
                "company": announcement.company,
                "file_id": file_id,
                "source_url": pdf.url,
                "timestamp": datetime.utcnow(),
                "processed": False,  # initially not processed
                "summary_path": None,  # to be filled later
            })
            scraper_logger.info("Saved %s (id=%s) (amended=%s) to GridFS + Mongo", pdf.name, file_id, announcement.is_amended)