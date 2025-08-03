import logging
from datetime import datetime
from pymongo import MongoClient
import gridfs
from typing import Any, Mapping, Optional, List

import asyncio
from motor.motor_asyncio import AsyncIOMotorGridFSBucket
from bson import ObjectId

from ..report_scraper.models import Announcement, ReportType, PDFDocument
from ..storage.mongodb_storage import AsyncMongoDBStorage


retrieval_logger = logging.getLogger("retrieval")



class RetrievalAsyncStorageManager:
    def __init__(self, mongo_uri: str, db_name: str):
        # Initialize async MongoDB storage
        self.storage = AsyncMongoDBStorage(mongo_uri)
        self.storage.use_database(db_name)
        retrieval_logger.info("Connected to MongoDB database: %s", db_name)

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

    async def get_raw_reports(self, company: str, year: int) -> List[Mapping[str, Any]]:
        """
        Return all raw PDF metadata docs for company/year
        from the “raw” collection (e.g. 'annual_reports').
        """
        if self.storage.collection is None:
            raise ValueError("Call use_collection() first")
        query = {"company": company, "year": str(year)}
        return await self.storage.read_documents(query=query)
    
    async def get_processed_summary(self, summary_filename: str) -> Optional[str]:
        """
        Fetch a processed Markdown summary by filename
        from the “processed” collection (e.g. 'ar_processed').
        """
        if self.storage.collection is None:
            raise ValueError("Call use_collection() first")
        
        docs = await self.storage.read_documents(query={"filename": summary_filename})

        if not docs:
            retrieval_logger.warning("No summary metadata for %s", summary_filename)
            return None
        
        file_id = docs[0]["file_id"]
        raw = await self.fs_bucket.open_download_stream(file_id).read()
        return raw.decode("utf-8")
    
    async def save_processed_report(
            self,
            company: str,
            year: int,
            report_type: ReportType,
            summary_filename: str,
            summary_content: str
    ) -> ObjectId:
        """
        Save a processed report summary to the 'processed' collection.
        """
        processed_collection = f"{report_type.name}_processed"
        self.use_collection(processed_collection)

        # upload summary content to GridFS
        data = summary_content.encode("utf-8")
        summary_file_id: ObjectId = await self.fs_bucket.upload_from_stream(summary_filename, data)

        # insert metadata
        summary_doc = {
            "company": company,
            "year": str(year),
            "filename": summary_filename,
            "summary_path": summary_filename,
            "file_id": summary_file_id,
            "timestamp": datetime.utcnow(),
        }
        summary_doc_id = await self.storage.create_document(summary_doc)

        # update the original raw report metadata to 'processed'
        self.use_collection(report_type.collection)

        await self.storage.collection.update_many(
            {"company": company, "year": str(year)},
            {
                "$set": {
                    "processed": True,
                    "summary_path": summary_filename,
                }
            }
        )
        retrieval_logger.info("Saved processed report for %s %s (year: %s) → %s",
            report_type.keyword, company, str(year), summary_filename
        )
        return summary_doc_id
    
    # async def download_processed_report()

    