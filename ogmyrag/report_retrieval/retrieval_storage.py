import logging
from datetime import datetime
from pymongo import MongoClient
import gridfs
from typing import Any, Mapping, Optional, List

import asyncio
from motor.motor_asyncio import AsyncIOMotorGridFSBucket
from motor.motor_asyncio import AsyncIOMotorClient
from ogmyrag.base import MongoStorageConfig
from bson import ObjectId

from ..report_scraper.models import Announcement, ReportType, PDFDocument
from ..storage.mongodb_storage import AsyncMongoDBStorage


retrieval_logger = logging.getLogger("retrieval")



class RetrievalAsyncStorageManager:
    def __init__(self, client: AsyncIOMotorClient, mongo_config: MongoStorageConfig):
        # Initialize async MongoDB storage
        self.storage = AsyncMongoDBStorage(client)
        self.storage_config = mongo_config
        self.storage.get_database(mongo_config["database_name"])
        
        retrieval_logger.info("Connected to MongoDB database: %s", mongo_config["database_name"])

        # Initialize GridFS bucket
        self.fs_bucket: Optional[AsyncIOMotorGridFSBucket] = None

    def use_collection(self, collection_name: str):
        """
        Switch both metadata & GridFS bucket to this collection.
        Must be called before any save/exists/mark_processed.
        """
        self.storage.use_collection(collection_name)
        # Initialize GridFS bucket for this collection
        self.fs_bucket = AsyncIOMotorGridFSBucket(self.storage.get_database(self.storage_config["database_name"]), bucket_name=collection_name)

    async def get_raw_reports(self, company: str, year: int, report_type: ReportType) -> List[Mapping[str, Any]]:
        """
        Return all raw PDF metadata docs for company/year
        from the “raw” collection (e.g. 'annual_reports').
        """
        #if self.storage.collection is None:
        #    raise ValueError("Call use_collection() first")
        query = {"company": company, "year": str(year)}
        return await self.storage.get_database(self.storage_config["database_name"]).get_collection(report_type.collection).read_documents(query=query)
    
    async def get_processed_summary(self, summary_filename: str) -> Optional[str]:
        """
        Fetch a processed Markdown summary by filename
        from the “processed” collection (e.g. 'ar_processed').
        """
        if self.storage.collection is None:
            raise ValueError("Call use_collection() first")
        
        docs = await self.storage.get_database(self.storage_config["database_name"]).get_collection(report_type.collection).read_documents(query={"filename": summary_filename})

        if not docs:
            retrieval_logger.warning("No summary metadata for %s", summary_filename)
            return None
        
        file_id = docs[0]["file_id"]
        grid_out = await self.fs_bucket.open_download_stream(file_id)
        raw = await grid_out.read()
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
        summary_doc_id = await self.storage.get_database(self.storage_config["database_name"]).get_collection(report_type.collection).create_document(summary_doc)

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
    
    def update_many(self, query: dict, new_values: dict):
        if self.storage.collection is None:
            raise ValueError("Call use_collection() first")
        self.storage.collection.update_many(query, {"$set": new_values}, upsert=True)

    async def save(self, data: Mapping[str, Any]):
        #if self.storage.collection is None:
        #    raise ValueError("Call use_collection() first")
        await self.storage.collection.insert_one(data)


    async def extract_combine_processed_content(
            self,
            company: str,
            year: Optional[int],
            report_type: ReportType
    ) -> str:
        """
        Extract and combine all processed content for a given company and year.
        """
        #if self.storage.collection is None:
        #    raise ValueError("Call use_collection() first")
        
        if report_type.collection == "ipo_reports":
            type = "PROSPECTUS"

            query = {
                "from_company": company,
                "type": type
            }
        elif report_type.collection == "annual_reports":
            type = "ANNUAL_REPORT"

            query = {
                "from_company": company,
                "year": str(year),
                "type": type
            }
        
        retrieval_logger.info("Extracting all the processed content.")

        results = await self.storage.get_database(self.storage_config["database_name"]).get_collection(report_type.collection).read_documents(query=query)
        
        if not results:
            retrieval_logger.warning("No processed content found for %s %s (year: %s)",
                                     company, report_type.name, str(year))
            return ""
        
        # --- minimal: local helpers (no regex) to parse section index ---
        def _parse_leading_int(s: str | None) -> int | None:
            if not s:
                return None
            s = s.lstrip()
            i = 0
            while i < len(s) and s[i].isdigit():
                i += 1
            return int(s[:i]) if i > 0 else None

        def _section_order(doc: dict) -> tuple[int, str]:
            # 1) Try from "section": "12. TITLE"
            n = _parse_leading_int(doc.get("section"))
            if n is not None:
                return (n, doc.get("section") or "")
            # 2) Fallback from "name": "..._SECTION_12"
            name = doc.get("name") or ""
            key = "_SECTION_"
            pos = name.rfind(key)
            if pos != -1:
                n2 = _parse_leading_int(name[pos + len(key):])
                if n2 is not None:
                    return (n2, name)
            # 3) Unknown → push to end, keep stable tie-breaker
            return (10**9, name or (doc.get("_id") and str(doc["_id"])) or "")

        # Sort results by section index (ascending)
        results.sort(key=_section_order)
        
        retrieval_logger.info("Combining all the processed content.")
        # combine all sections into a single Markdown string
        md = [f"# {company} {report_type.name}\n"]
        for section in results:
            md.append(section["content"] + "\n")

        retrieval_logger.info("Processed content ready.")

        return "\n".join(md)
    

    async def check_exists(self, query: dict) -> bool:
        """
        Check if a document exists in the current collection.
        """
        #if self.storage.collection is None:
        #    raise ValueError("Call use_collection() first")
        count = await self.storage.collection.count_documents(query)
        return count > 0
    
    async def retrieve_toc(self, query: dict):
        #if self.storage.collection is None:
        #    raise ValueError("Call use_collection() first")
        results = await self.storage.get_database(self.storage_config["database_name"]).get_collection(report_type.collection).read_documents(query=query)
        return results[0].get("content", "[]")
    
    async def retrieve_section(self, query: dict):
        #if self.storage.collection is None:
        #    raise ValueError("Call use_collection() first")
        results = await self.storage.get_database(self.storage_config["database_name"]).get_collection(report_type.collection).read_documents(query=query)
        return results[0]["content"] 
    
