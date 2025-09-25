import logging
from typing import Any
from contextlib import asynccontextmanager, contextmanager
from bson.objectid import ObjectId
from pymongo.errors import (
    PyMongoError,
)
from pymongo import MongoClient, UpdateOne
from pymongo.database import Database
from pymongo.collection import Collection
from pymongo.client_session import ClientSession
from motor.motor_asyncio import (
    AsyncIOMotorClient,
    AsyncIOMotorCollection,
    AsyncIOMotorDatabase,
    AsyncIOMotorClientSession,
)
from pymongo.results import UpdateResult, BulkWriteResult, DeleteResult
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
        update_data: dict[str, Any],
        session: AsyncIOMotorClientSession | None = None,
    ) -> int:
        """
        Updates a single document in the collection.

        - If `update_data` contains only field-value pairs, it performs a '$set' operation.
        - If `update_data` contains MongoDB update operators (e.g., '$unset', '$inc'),
          it uses the dictionary directly as the update operation.

        Args:
            query: The query to find the document to update.
            update_data: A dictionary containing either the fields to set or a complete
                         MongoDB update document with operators.
            session: An optional client session.

        Returns:
            The number of documents modified.

        Raises:
            DatabaseError: If the update operation fails.
        """
        try:
            # Check if any key in the update dictionary is a MongoDB operator (starts with '$')
            has_operators = any(key.startswith("$") for key in update_data)

            if has_operators:
                # If it already has operators, use it directly.
                # Example: {"$unset": {"field": ""}, "$set": {"status": "done"}}
                update_operation = update_data
            else:
                # For backward compatibility, wrap plain field-value pairs in '$set'.
                # Example: {"status": "done", "progress": 100} -> {"$set": {"status": "done", ...}}
                update_operation = {"$set": update_data}

            result = await self.collection.update_one(
                query, update_operation, session=session
            )
            return result.modified_count
        except PyMongoError as e:
            logger.error(f"Error updating async document: {e}, full error: {e.details}")
            raise DatabaseError("Update document failed") from e

    async def update_documents(
        self,
        query: dict[str, Any],
        update: dict[str, Any],
        session: AsyncIOMotorClientSession | None = None,
    ) -> UpdateResult:
        """
        Updates all documents that match the specified query.

        Args:
            query (dict): The filter to select which documents to update.
            update (dict): The update operation document (e.g., {"$set": {...}}).
            session (optional): The client session for transactions.

        Returns:
            UpdateResult: The result object from MongoDB, containing details like matched_count and modified_count.
        """
        try:
            result = await self.collection.update_many(query, update, session=session)
            logger.info(
                f"Batch update completed for query {query}. "
                f"Matched: {result.matched_count}, "
                f"Modified: {result.modified_count}."
            )
            return result
        except PyMongoError as e:
            logger.error(f"Error during batch update operation: {e}")
            raise DatabaseError("Update documents failed") from e

    async def upsert_documents(
        self,
        operations: list[dict[str, dict]] | dict[str, dict],
        session: AsyncIOMotorClientSession | None = None,
    ) -> BulkWriteResult:
        """
        Performs multiple upsert operations in a single bulk request.

        Args:
            - operations (list or dict) : A list of dictionaries, where each dict has a "query" and "data" key. Example: [{"query": {"name": "A"}, "data": {"value": 1}}, {"query": {"name": "B"}, "data": {"value": 2}}]. Or, a single dictionary with "query" and "data" keys. Example: {"query": {"name": "C"}, "data": {"value": 3}}
            - session (optional) : The client session for transactions.

        Returns:
            BulkWriteResult: The result object from the bulk operation.
        """
        if isinstance(operations, dict):
            operations = [operations]

        if not operations:
            return BulkWriteResult({}, True)  # Return empty but successful result

        try:
            bulk_requests = [
                UpdateOne(op["query"], {"$set": op["data"]}, upsert=True)
                for op in operations
            ]
            result = await self.collection.bulk_write(bulk_requests, session=session)
            logger.info(
                f"Bulk upsert completed. "
                f"Upserted: {result.upserted_count}, "
                f"Modified: {result.modified_count}."
            )
            return result
        except (PyMongoError, KeyError) as e:
            logger.error(f"Error during bulk upsert operation: {e}")
            raise DatabaseError("Bulk upsert documents failed") from e

    async def delete_document(
        self, query: dict, session: AsyncIOMotorClientSession | None = None
    ) -> int:
        try:
            result = await self.collection.delete_one(query, session=session)
            return result.deleted_count
        except PyMongoError as e:
            logger.error(f"Error deleting async document: {e}")
            raise DatabaseError("Delete document failed") from e

    async def delete_documents(
        self, query: dict[str, Any], session: AsyncIOMotorClientSession | None = None
    ) -> DeleteResult:
        """
        Deletes all documents that match the specified query.

        Args:
            query (dict): The filter to select which documents to delete. An empty query {} will delete ALL documents in the collection.
            session (optional): The client session for transactions.

        Returns:
            DeleteResult: The result object from MongoDB, containing details like the number of documents deleted in `deleted_count`.
        """
        try:
            result = await self.collection.delete_many(query, session=session)
            logger.info(
                f"Batch delete completed for query {query}. "
                f"Deleted: {result.deleted_count} document(s)."
            )
            return result
        except PyMongoError as e:
            logger.error(f"Error during batch delete operation: {e}")
            raise DatabaseError("Delete documents failed") from e

    async def get_doc_counts(self, query: dict | None = None):
        # If query is None (the default), create a new empty dict
        if query is None:
            query = {}
        return await self.collection.count_documents(query)


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
