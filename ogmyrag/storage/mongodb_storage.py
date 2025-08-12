import logging
from typing import Any
from contextlib import asynccontextmanager, contextmanager
from bson.objectid import ObjectId
from pymongo.errors import (
    PyMongoError,
)
from pymongo import MongoClient
from pymongo.database import Database
from pymongo.collection import Collection
from pymongo.client_session import ClientSession
from motor.motor_asyncio import (
    AsyncIOMotorClient,
    AsyncIOMotorCollection,
    AsyncIOMotorDatabase,
    AsyncIOMotorClientSession,
)
from .storage_util import DatabaseError

logger = logging.getLogger("mongodb")


class CollectionHandler:
    """Handles operations for a specific sync collection."""

    def __init__(self, collection: Collection):
        self.collection = collection

    def create_document(
        self, data: dict[str, Any], session: ClientSession | None = None
    ) -> ObjectId:
        try:
            result = self.collection.insert_one(data, session=session)
            return result.inserted_id
        except PyMongoError as e:
            logger.error(f"Create failed: {e}")
            raise DatabaseError("Create document failed") from e

    def read_documents(
        self, query: dict | None = None, session: ClientSession | None = None
    ) -> list[dict[str, Any]]:
        try:
            return list(self.collection.find(query or {}, session=session))
        except PyMongoError as e:
            logger.error(f"Read failed: {e}")
            raise DatabaseError("Read documents failed") from e

    def update_document(
        self,
        query: dict[str, Any],
        new_values: dict[str, Any],
        session: ClientSession | None = None,
    ) -> int:
        try:
            result = self.collection.update_one(
                query, {"$set": new_values}, session=session
            )
            return result.modified_count
        except PyMongoError as e:
            logger.error(f"Error updating document: {str(e)}")
            raise DatabaseError("Update document failed") from e

    def delete_document(
        self, query: dict[str, Any], session: ClientSession | None = None
    ) -> int:
        try:
            result = self.collection.delete_one(query, session=session)
            return result.deleted_count
        except PyMongoError as e:
            logger.error(f"Error deleting document: {str(e)}")
            raise DatabaseError("Delete document failed") from e

    def get_doc_counts(self):
        return self.collection.count_documents({})


class DatabaseHandler:
    """Handles operations for a specific sync database."""

    def __init__(self, db: Database):
        self.db = db

    def get_collection(self, collection_name: str) -> CollectionHandler:
        """Returns a handler for a specific collection within this database."""
        return CollectionHandler(self.db[collection_name])


class MongoDBStorage:
    """Top-level sync storage class providing a fluent API."""

    def __init__(self, client: MongoClient):
        self.client = client
        logger.info("MongoStorage initialized with a shared client.")

    def get_database(self, db_name: str) -> DatabaseHandler:
        """Returns a handler for a specific database."""
        return DatabaseHandler(self.client[db_name])

    @contextmanager 
    def with_transaction(self):
        """A context manager to handle a transaction, initiated from the client."""
        with self.client.start_session() as session:
            with session.start_transaction():
                try:
                    yield session
                except Exception as e:
                    logger.error(f"Transaction aborted due to an error: {e}")
                    raise


class AsyncCollectionHandler:
    """Handles operations for a specific async collection."""

    def __init__(self, collection: AsyncIOMotorCollection):
        self.collection = collection

    async def create_document(
        self, data: dict, session: AsyncIOMotorClientSession | None = None
    ) -> ObjectId:
        try:
            result = await self.collection.insert_one(data, session=session)
            return result.inserted_id
        except PyMongoError as e:
            logger.error(f"Failed to insert async document: {e}")
            raise DatabaseError("Create document failed") from e

    async def create_documents(
        self, data: list[dict], session: AsyncIOMotorClientSession | None = None
    ) -> list[ObjectId]:
        if not data:
            return []
        try:
            result = await self.collection.insert_many(data, session=session)
            logger.info(f"Batch inserted {len(result.inserted_ids)} documents.")
            return result.inserted_ids
        except PyMongoError as e:
            logger.error(f"Failed to batch insert async documents: {e}")
            raise DatabaseError("Batch create documents failed") from e

    async def read_documents(
        self,
        query: dict | None = None,
        limit: int = 1000,
        sort: list[tuple[str, int]] | None = None,
        session: AsyncIOMotorClientSession | None = None,
    ) -> list[dict[str, Any]]:
        try:
            cursor = self.collection.find(query or {}, session=session)
            if sort:
                cursor = cursor.sort(sort)
            return await cursor.to_list(length=limit)
        except PyMongoError as e:
            logger.error(f"Error reading async documents: {e}")
            raise DatabaseError("Read documents failed") from e

    async def update_document(
        self,
        query: dict,
        new_values: dict,
        session: AsyncIOMotorClientSession | None = None,
    ) -> int:
        try:
            result = await self.collection.update_one(
                query, {"$set": new_values}, session=session
            )
            return result.modified_count
        except PyMongoError as e:
            logger.error(f"Error updating async document: {e}")
            raise DatabaseError("Update document failed") from e

    async def delete_document(
        self, query: dict, session: AsyncIOMotorClientSession | None = None
    ) -> int:
        try:
            result = await self.collection.delete_one(query, session=session)
            return result.deleted_count
        except PyMongoError as e:
            logger.error(f"Error deleting async document: {e}")
            raise DatabaseError("Delete document failed") from e

    async def get_doc_counts(self):
        return await self.collection.count_documents({})


class AsyncDatabaseHandler:
    """Handles operations for a specific async database."""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    def get_collection(self, collection_name: str) -> AsyncCollectionHandler:
        """Returns a handler for a specific collection within this database."""
        return AsyncCollectionHandler(self.db[collection_name])


class AsyncMongoDBStorage:
    """Top-level async storage class providing a fluent API."""

    def __init__(self, client: AsyncIOMotorClient):
        self.client = client
        logger.info("AsyncMongoStorage initialized with a shared async client.")

    def get_database(self, db_name: str) -> AsyncDatabaseHandler:
        """Returns a handler for a specific database."""
        return AsyncDatabaseHandler(self.client[db_name])

    @asynccontextmanager
    async def with_transaction(self):
        """An async context manager to handle a transaction, initiated from the client."""
        async with await self.client.start_session() as session:
            async with session.start_transaction():
                try:
                    logger.info("Async transaction started.")
                    yield session
                    logger.info("Async transaction committed successfully.")
                except Exception as e:
                    logger.error(f"Async transaction aborted due to an error: {e}")
                    raise
