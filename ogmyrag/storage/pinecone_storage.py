import asyncio
import logging
from pinecone import Pinecone, ServerlessSpec
from tenacity import retry, stop_after_attempt, wait_exponential
from collections import defaultdict
from tqdm import tqdm
from tqdm.asyncio import tqdm_asyncio
from openai import AsyncOpenAI
from typing import Any

pinecone_logger = logging.getLogger("pinecone")


class PineconeStorage:
    def __init__(
        self,
        index_name: str,
        pinecone_api_key: str,
        pinecone_environment: str,
        pinecone_cloud: str,
        pinecone_metric: str,
        pinecone_dimensions: str,
        openai_api_key: str,
    ):
        try:
            self.pinecone = Pinecone(api_key=pinecone_api_key)

            if index_name not in self.pinecone.list_indexes().names():
                self.pinecone.create_index(
                    name=index_name,
                    dimension=int(pinecone_dimensions),
                    metric=pinecone_metric,
                    spec=ServerlessSpec(
                        cloud=pinecone_cloud, region=pinecone_environment
                    ),
                )
            self.index = self.pinecone.Index(index_name)
            self.openai = AsyncOpenAI(api_key=openai_api_key)
            pinecone_logger.info(
                f"Connected to Pinecone index '{index_name}' successfully."
            )

        except Exception as e:
            pinecone_logger.error(f"Could not connect to Pinecone: {str(e)}")
            raise

    async def create_vectors(
        self, items: list[dict[str, Any]], namespace: str = ""
    ) -> None:
        """
        Asynchronously embed multiple texts and upsert them to Pinecone using a single default namespace.
        Each item must have: 'id', 'name', and optionally 'metadata'.
        """
        pinecone_logger.info("Starting vector creation process (no namespace).")

        missing_fields = [
            item for item in items if not all(k in item for k in ("id", "name"))
        ]
        if missing_fields:
            pinecone_logger.error("Validation failed. Required fields are missing.")
            raise ValueError(
                f"Missing required fields in one or more items: {missing_fields}"
            )

        data = [(item["id"], item["name"], item.get("metadata", {})) for item in items]
        pinecone_logger.info(
            f"{len(data)} items passed validation. Beginning embedding..."
        )

        try:
            ids, names, metadata_list = zip(*data)

            # Embed texts asynchronously
            embedding_responses = await tqdm_asyncio.gather(
                *[self._embed_text(name) for name in names], desc="Embedding texts"
            )

            # Prepare vector list
            vectors = [
                {"id": id, "values": embedding, "metadata": metadata}
                for id, embedding, metadata in zip(
                    ids, embedding_responses, metadata_list
                )
            ]

            pinecone_logger.info(f"Upserting {len(vectors)} vectors to Pinecone...")
            self.index.upsert(vectors=vectors, namespace=namespace)

            pinecone_logger.info(
                f"Successfully created {len(items)} vectors in Pinecone (no namespace)."
            )

        except Exception as e:
            pinecone_logger.error(f"Error while creating vectors (no namespace): {e}")
            raise

    async def get_similar_results(
        self,
        query_texts: str | list[str],
        top_k: int = 5,
        include_metadata: bool = True,
        query_filter: dict | None = None,
        score_threshold: float = 0.0,
        namespace: str = "",
    ):
        """
        Perform similarity search without using namespace for the given query_text(s).
        Accepts a single string or list of strings.
        Supports filter and score threshold.
        Returns a list of results corresponding to each query.
        """
        try:
            if isinstance(query_texts, str):
                query_texts = [query_texts]

            query_embeddings = await self._embed_text(query_texts)

            async def query_single(embedding):
                result = await asyncio.to_thread(
                    self.index.query,
                    vector=embedding,
                    namespace=namespace,
                    top_k=top_k,
                    include_metadata=include_metadata,
                    filter=query_filter or {},
                )

                result["matches"] = [
                    m
                    for m in result.get("matches", [])
                    if m.get("score", 0.0) >= score_threshold
                ]
                return result

            all_results = await asyncio.gather(
                *(query_single(embedding) for embedding in query_embeddings)
            )

            return all_results

        except Exception as e:
            pinecone_logger.error(
                f"Error while fetching similar result(s) (no namespace): {e}"
            )
            raise

    async def update_vector(
        self, id: str, namespace: str, new_text: str, new_metadata: dict | None = None
    ) -> None:
        try:
            embedding = await self._embed_text(new_text)
            self.index.upsert(
                vectors=[
                    {
                        "id": id,
                        "namespace": namespace,
                        "values": embedding,
                        "metadata": new_metadata or {},
                    }
                ]
            )
        except Exception as e:
            pinecone_logger.error(f"Error while updating vector: {e}")
            raise

    def delete_vector(self, id: str) -> None:
        try:
            self.index.delete(ids=[id])
        except Exception as e:
            pinecone_logger.error(f"Error while deleting: {e}")
            raise

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
