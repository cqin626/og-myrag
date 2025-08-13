from __future__ import annotations

import asyncio
import logging
from pinecone import Pinecone, ServerlessSpec
from tenacity import retry, stop_after_attempt, wait_exponential
from collections import defaultdict
from tqdm.asyncio import tqdm_asyncio
from openai import AsyncOpenAI
from typing import Any

pinecone_logger = logging.getLogger("pinecone")


class IndexOperator:
    """
    An operator for a single, specific Pinecone index.
    This class is not meant to be created directly, but through PineconeStorageManager.get_index().
    """

    def __init__(self, index_name: str, manager: PineconeStorage):
        """
        Initializes the operator.
        :param index_name: The name of the Pinecone index to operate on.
        :param manager: The parent PineconeStorageManager instance.
        """
        self.index_name = index_name
        self.manager = manager
        self.index = self.manager._get_index(self.index_name)

    async def upsert_vectors(
        self, items: list[dict] | dict, namespace: str = ""
    ) -> None:
        """
        Embeds and upserts a list of items into the specific index for this operator.
        """
        pinecone_logger.info(f"Starting vector upsert for index '{self.index_name}'.")

        if isinstance(items, dict):
            items = [items]

        missing_fields = [
            item for item in items if "id" not in item or "name" not in item
        ]
        if missing_fields:
            raise ValueError("All items must contain 'id' and 'name' keys.")

        try:
            data = [
                (item["id"], item["name"], item.get("metadata", {})) for item in items
            ]
            ids, names, metadata_list = zip(*data)

            embedding_responses = await asyncio.gather(
                *[self.manager._embed_text(name) for name in names]
            )
            vectors = [
                {"id": id, "values": embedding, "metadata": metadata}
                for id, embedding, metadata in zip(
                    ids, embedding_responses, metadata_list
                )
            ]

            await asyncio.to_thread(
                self.index.upsert, vectors=vectors, namespace=namespace
            )
            pinecone_logger.info(
                f"Successfully upserted {len(vectors)} vectors to index '{self.index_name}'."
            )
        except Exception as e:
            pinecone_logger.error(
                f"Error during upsert to index '{self.index_name}': {e}"
            )
            raise

    async def get_similar_results(
        self,
        query_texts: str | list[str],
        top_k: int = 5,
        include_metadata: bool = True,
        query_filter: dict | None = None,
        score_threshold: float = 0.0,
        namespace: str = ""
    ) -> list[dict]:
        """
        Performs a similarity search in the index for this operator.
        """
        try:
            pinecone_logger.info(f"Fetching similar results for query_texts from '{self.index_name}':\n {query_texts}")
            
            if isinstance(query_texts, str):
                query_texts = [query_texts]
            
            query_embeddings = await self.manager._embed_text(query_texts)

            async def query_single(embedding: list[float]) -> dict:
                result = await asyncio.to_thread(
                    self.index.query,
                    vector=embedding, top_k=top_k, include_metadata=include_metadata,
                    filter=query_filter or {}, namespace=namespace
                )
                result["matches"] = [
                    m for m in result.get("matches", []) if m.get("score", 0.0) >= score_threshold
                ]
                return result

            return await asyncio.gather(*(query_single(emb) for emb in query_embeddings))
        except Exception as e:
            pinecone_logger.error(f"Error during query on index '{self.index_name}': {e}")
            raise

    async def delete_vectors(self, ids: list[str], namespace: str = "") -> None:
        """
        Deletes one or more vectors from the index by their IDs.
        """
        try:
            pinecone_logger.info(f"Deleting vector(s) from '{self.index_name}'...")
            await asyncio.to_thread(self.index.delete, ids=ids, namespace=namespace)
            pinecone_logger.info(
                f"Sent delete request for {len(ids)} vector(s) from index '{self.index_name}'."
            )
        except Exception as e:
            pinecone_logger.error(
                f"Error during delete on index '{self.index_name}': {e}"
            )
            raise

class PineconeStorage:
    """
    A class for interacting with multiple Pinecone indexes using a fluent API.
    """
    def __init__(self, pinecone_api_key: str, openai_api_key: str):
        self.pinecone = Pinecone(api_key=pinecone_api_key)
        self.openai = AsyncOpenAI(api_key=openai_api_key)
        self._index_cache: dict[str, Any] = {}
        pinecone_logger.info("PineconeStorage initialized successfully.")

    def _get_index(self, index_name: str) -> Any:
        if index_name not in self._index_cache:
            self._index_cache[index_name] = self.pinecone.Index(index_name)
        return self._index_cache[index_name]

    def get_index(self, index_name: str) -> IndexOperator:
        return IndexOperator(index_name, self)

    def create_index_if_not_exists(
        self,
        index_name: str,
        dimension: int,
        metric: str = "cosine",
        cloud: str = "aws",
        region: str = "us-east-1"
    ):
        if index_name not in self.pinecone.list_indexes().names():
            pinecone_logger.info(f"Index '{index_name}' not found. Creating...")
            self.pinecone.create_index(
                name=index_name, dimension=dimension, metric=metric,
                spec=ServerlessSpec(cloud=cloud, region=region)
            )
            pinecone_logger.info(f"Index '{index_name}' created.")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def _embed_text(self, text: str | list[str]) -> list[float] | list[list[float]]:
        response = await self.openai.embeddings.create(model="text-embedding-3-small", input=text)
        return [item.embedding for item in response.data] if isinstance(text, list) else response.data[0].embedding

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10)
    )
    async def _embed_text(
        self, text: str | list[str]
    ) -> list[float] | list[list[float]]:
        try:
            response = await self.openai.embeddings.create(
                model="text-embedding-3-small", input=text
            )
            return (
                [item.embedding for item in response.data]
                if isinstance(text, list)
                else response.data[0].embedding
            )
        except Exception as e:
            pinecone_logger.error(f"Error while embedding '{text}': {e}")
            raise