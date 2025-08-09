import logging
from collections.abc import Mapping
from typing import Any

from bson.objectid import ObjectId
from bson.raw_bson import RawBSONDocument
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import (
    ConnectionFailure,
    OperationFailure,
    ServerSelectionTimeoutError,
)
from pymongo.results import DeleteResult, InsertOneResult, UpdateResult
from motor.motor_asyncio import (
    AsyncIOMotorClient,
    AsyncIOMotorCollection,
    AsyncIOMotorDatabase,
)

logger = logging.getLogger("mongodb")

class MongoDBStorage:
    client: MongoClient
    db: Database | None
    collection: Collection | None

    def __init__(self, connection_uri: str, timeout_ms: int = 5000):
        try:
            self.client = MongoClient(
                connection_uri,
                serverSelectionTimeoutMS=timeout_ms,
            )
            # Verify connection by pinging server
            self.client.admin.command("ping")
            self.db = None
            self.collection = None
            logger.info("MongoDB client initialized successfully")
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.error(f"Could not connect to MongoDB: {str(e)}")
            raise

    def use_database(self, db_name: str) -> None:
        try:
            self.db = self.client[db_name]
            logger.info(f"Switched to database: {db_name}")
        except Exception as e:
            logger.error(f"Failed to switch to database {db_name}: {str(e)}")
            raise

    def use_collection(self, collection_name: str) -> None:
        if self.db is None:
            error_msg = "Please select a database first using use_database()"
            logger.error(error_msg)
            raise ValueError(error_msg)
        try:
            self.collection = self.db[collection_name]
            logger.info(f"Using collection: {collection_name}")
        except Exception as e:
            logger.error(f"Failed to use collection {collection_name}: {str(e)}")
            raise

    def create_document(
        self, data: Mapping[str, Any] | RawBSONDocument
    ) -> ObjectId | None:
        """Insert a document into the collection.

        Args:
            data: Document data to insert

        Returns:
            The inserted document ID or None if operation failed

        Raises:
            ValueError: If no collection has been selected
        """
        if self.collection is None:
            error_msg = "No collection selected"
            logger.error(error_msg)
            raise ValueError(error_msg)

        try:
            result: InsertOneResult = self.collection.insert_one(data)
            logger.info(f"Document created with ID: {result.inserted_id}")
            return result.inserted_id
        except OperationFailure as e:
            logger.error(f"Failed to create document: {str(e)}")
            return None

    def read_documents(
        self, query: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Read documents matching the query.

        Args:
            query: Query filter (default: empty to return all documents)

        Returns:
            List of matching documents

        Raises:
            ValueError: If no collection has been selected
        """
        if query is None:
            query = {}

        if self.collection is None:
            error_msg = "No collection selected"
            logger.error(error_msg)
            raise ValueError(error_msg)
        try:
            results = list(self.collection.find(query))
            logger.info(f"Retrieved {len(results)} documents")
            return results
        except Exception as e:
            logger.error(f"Error reading documents: {str(e)}")
            return []

    def update_document(self, query: dict[str, Any], new_values: dict[str, Any]) -> int:
        """Update a document in the collection.

        Args:
            query: Query to identify document(s) to update
            new_values: Values to update in the document

        Returns:
            Number of documents modified

        Raises:
            ValueError: If no collection has been selected
        """
        if self.collection is None:
            error_msg = "No collection selected"
            logger.error(error_msg)
            raise ValueError(error_msg)

        try:
            result: UpdateResult = self.collection.update_one(
                query, {"$set": new_values}
            )
            logger.info(f"Updated {result.modified_count} document(s)")
            return result.modified_count
        except Exception as e:
            logger.error(f"Error updating document: {str(e)}")
            return 0

    def delete_document(self, query: dict[str, Any]) -> int:
        """Delete a document from the collection.

        Args:
            query: Query to identify document(s) to delete

        Returns:
            Number of documents deleted

        Raises:
            ValueError: If no collection has been selected
        """
        if self.collection is None:
            error_msg = "No collection selected"
            logger.error(error_msg)
            raise ValueError(error_msg)
        try:
            result: DeleteResult = self.collection.delete_one(query)
            logger.info(f"Deleted {result.deleted_count} document(s)")
            return result.deleted_count
        except Exception as e:
            logger.error(f"Error deleting document: {str(e)}")
            return 0

    def close_connection(self) -> None:
        try:
            if hasattr(self, "client") and self.client is not None:
                self.client.close()
                logger.info("Connection closed")
        except Exception as e:
            logger.error(f"Error closing connection: {str(e)}")


class AsyncMongoDBStorage:
    client: AsyncIOMotorClient
    db: AsyncIOMotorDatabase | None
    collection: AsyncIOMotorCollection | None

    def __init__(self, connection_uri: str, timeout_ms: int = 5000):
        try:
            self.client = AsyncIOMotorClient(
                connection_uri,
                serverSelectionTimeoutMS=timeout_ms,
                uuidRepresentation="standard",
            )
            self.db = None
            self.collection = None
            logger.info("Async MongoDB client initialized")
        except Exception as e:
            logger.error(f"AsyncMongoDB connection failed: {str(e)}")
            raise

    def use_database(self, db_name: str) -> None:
        self.db = self.client[db_name]
        logger.info(f"Switched to database: {db_name}")

    def use_collection(self, collection_name: str) -> None:
        if self.db is None:
            raise ValueError("Call use_database() before use_collection()")
        self.collection = self.db[collection_name]
        logger.info(f"Using collection: {collection_name}")

    async def create_document(self, data: Mapping[str, Any]) -> ObjectId | None:
        if self.collection is None:
            raise ValueError("No collection selected")
        try:
            result = await self.collection.insert_one(data)
            logger.info(f"Inserted async document with ID: {result.inserted_id}")
            return result.inserted_id
        except Exception as e:
            logger.error(f"Failed to insert async document: {str(e)}")
            return None

    async def read_documents(
        self,
        query: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        if query is None:
            query = {}
        if self.collection is None:
            raise ValueError("No collection selected")
        try:
            cursor = self.collection.find(query)
            if limit is not None:
                cursor = cursor.limit(limit)
            docs = await cursor.to_list(length=limit or None)
            logger.info(f"Retrieved {len(docs)} documents")
            return docs
        except Exception as e:
            logger.error(f"Error reading async documents: {str(e)}")
            return []

    async def update_document(
        self, query: dict[str, Any], new_values: dict[str, Any]
    ) -> int:
        if self.collection is None:
            raise ValueError("No collection selected")
        try:
            result = await self.collection.update_one(query, {"$set": new_values})
            logger.info(f"Updated {result.modified_count} document(s)")
            return result.modified_count
        except Exception as e:
            logger.error(f"Error updating async document: {str(e)}")
            return 0

    async def delete_document(self, query: dict[str, Any]) -> int:
        if self.collection is None:
            raise ValueError("No collection selected")
        try:
            result = await self.collection.delete_one(query)
            logger.info(f"Deleted {result.deleted_count} document(s)")
            return result.deleted_count
        except Exception as e:
            logger.error(f"Error deleting async document: {str(e)}")
            return 0

    async def close_connection(self) -> None:
        try:
            self.client.close()
            logger.info("Async connection closed")
        except Exception as e:
            logger.error(f"Error closing async connection: {str(e)}")

