import logging
from datetime import datetime
from pymongo import MongoClient
import gridfs
from typing import Any, Mapping, Optional

import asyncio
from motor.motor_asyncio import AsyncIOMotorGridFSBucket
from bson import ObjectId

from ..report_scraper.session import CloudflareSession
from ..report_scraper.models import Announcement, ReportType, PDFDocument
from ..storage.mongodb_storage import AsyncMongoDBStorage

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



class AsyncStorageManager:
    """
    Async storage for Announcement PDFs + metadata.
    - Metadata in Mongo via AsyncMongoDBStorage
    - PDF bytes in GridFS via AsyncIOMotorGridFSBucket
    """

    def __init__(self, mongo_uri: str, db_name: str):
        # Initialize async MongoDB storage
        self.storage = AsyncMongoDBStorage(mongo_uri)
        self.storage.use_database(db_name)
        scraper_logger.info("Connected to MongoDB database: %s", db_name)

        # Initialize Cloudflare session
        self.cf = CloudflareSession()

        # Initialize GridFS bucket
        self.fs_bucket: Optional[AsyncIOMotorGridFSBucket] = None
    
    def use_collection(self, collection_name: str):
        """
        Switch both metadata & GridFS bucket to this collection.
        Must be called before any save/exists/mark_processed.
        """
        self.storage.use_collection(collection_name)
        # Initialize GridFS bucket for this collection
        self.fs_bucket = AsyncIOMotorGridFSBucket(self.storage.db, bucket_name=collection_name)

    async def exists(self, report_type: ReportType, pdf: PDFDocument, year: int) -> bool:
        """
        Check if a document with this filename + year exists in the collection.
        """
        if self.storage.collection is None:
            self.use_collection(report_type.collection)

        key = {
            "filename": pdf.name,
            "year": year,
        }
        docs = await self.storage.read_documents(query=key)
        return len(docs) > 0
    
    async def save(self, announcement: Announcement, report_type: ReportType, year: int):
        """
        Download each PDF, upload to GridFS, then insert metadata doc.
        """
        if self.fs_bucket is None:
            self.use_collection(report_type.collection)

        for pdf in announcement.pdfs:
            key = {
                "filename": pdf.name,
                "year": year,
                "is_amended": announcement.is_amended
            }

            if await self.exists(report_type, pdf, year):
                scraper_logger.warning("Already exists: %s (amended = %s)", pdf.name, announcement.is_amended)
                continue
                
            scraper_logger.info("Downloading %s", pdf.name)
            # download PDF bytes in threadpool
            content: bytes = await asyncio.to_thread(self.cf.get_bytes, pdf.url)

            # upload to GridFS
            file_id: ObjectId = await self.fs_bucket.upload_from_stream(pdf.name, content)
            scraper_logger.info("Uploaded PDF bytes for %s → GridFS ID %s", pdf.name, file_id)

            # build full document
            doc: Mapping[str, Any] = {
                **key,
                "company": announcement.company,
                "file_id": file_id,
                "source_url": pdf.url,
                "timestamp": datetime.utcnow(),
                "processed": False,  # initially not processed
                "summary_path": None,  # to be filled later
                "announced_date": announcement.announced_date
            }

            inserted_id = await self.storage.create_document(doc)
            if inserted_id:
                scraper_logger.info("Inserted metadata for %s → %s", pdf.name, inserted_id)
            else:
                scraper_logger.error("Failed to insert metadata for %s", pdf.name)

    async def mark_processed(self, report_type: ReportType, query: dict, summary_path: str):
        """
        Set processed=True and summary_path for docs matching `query`.
        """
        if self.storage.collection is None:
            self.use_collection(report_type.collection)

        await self.storage.update_document(
            query, 
            {
                "processed": True,
                "summary_path": summary_path
            }
        )