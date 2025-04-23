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
       openai_api_key: str 
    ):
        try:
            self.pinecone = Pinecone(api_key=pinecone_api_key)

            if index_name not in self.pinecone.list_indexes().names():
                self.pinecone.create_index(
                    name=index_name,
                    dimension=int(pinecone_dimensions),
                    metric=pinecone_metric, 
                    spec=ServerlessSpec(cloud=pinecone_cloud, region=pinecone_environment) 
                )
            self.index = self.pinecone.Index(index_name)
            self.openai = AsyncOpenAI(api_key=openai_api_key)
            pinecone_logger.info(f"Connected to Pinecone index '{index_name}' successfully.")

        except Exception as e:
            pinecone_logger.error(f"Could not connect to Pinecone: {str(e)}")
            raise

    async def create_vectors(self, items: list[dict[str, Any]]) -> None:
        """
        Asynchronously embed multiple texts and upsert them in a single batch to Pinecone.
        Each item must have: 'id', 'name', 'namespace' and optionally 'metadata'.
        """
        pinecone_logger.info("Starting vector creation process.")

        missing_fields = [item for item in items if not all(k in item for k in ("id", "name", "namespace"))]
        if missing_fields:
            pinecone_logger.error("Validation failed. Required fields are missing.")
            raise ValueError(f"Missing required fields in one or more items: {missing_fields}")

        data = [(item["id"], item["name"], item["namespace"], item.get("metadata", {})) for item in items]
        pinecone_logger.info(f"{len(data)} items passed validation. Beginning embedding...")

        try:
            ids, names, namespaces, metadata_list = zip(*data)

            # Embedding with tqdm progress
            embedding_responses = await tqdm_asyncio.gather(*[
                self._embed_text(name) for name in names
            ], desc="Embedding texts")

            pinecone_logger.info("Embedding complete. Organizing vectors by namespace...")

            # Group vectors by namespace
            vectors_by_namespace = defaultdict(list)
            for id, embedding, namespace, metadata in zip(ids, embedding_responses, namespaces, metadata_list):
                vectors_by_namespace[namespace].append({
                    "id": id,
                    "values": embedding,
                    "metadata": metadata
                })

            pinecone_logger.info(f"Prepared vectors for {len(vectors_by_namespace)} namespaces. Upserting to Pinecone...")

            for namespace, vectors in tqdm(vectors_by_namespace.items(), desc="Upserting to Pinecone"):
                self.index.upsert(
                    vectors=vectors,
                    namespace=namespace
                )
                pinecone_logger.info(f"Upserted {len(vectors)} vectors to namespace '{namespace}'.")

            pinecone_logger.info(f"Successfully created {len(items)} vectors in Pinecone.")

        except Exception as e:
            pinecone_logger.error(f"Error while creating vectors: {e}")
            raise
    
    async def get_similar_results(
        self, 
        query_texts: str | list[str], 
        namespace: str,
        top_k: int = 5, 
        include_metadata: bool = True
    ):
        """
        Perform similarity search for the given query_text(s).
        Accepts a single string or list of strings.
        Returns a list of results corresponding to each query.
        """
        try:
            if isinstance(query_texts, str):
                query_texts = [query_texts]
            
            query_embeddings = await self._embed_text(query_texts)
            
            all_results = []
            
            for embedding in query_embeddings:
                result = self.index.query(
                    vector=embedding,
                    namespace=namespace,
                    top_k=top_k,
                    include_metadata=include_metadata
                )
                all_results.append(result)

            return all_results
        except Exception as e:
            pinecone_logger.error(f"Error while fetching similar result(s): {e}")
            raise
    
    async def get_formatted_similar_results(
        self, 
        query_texts: str | list[str], 
        namespace: str, 
        top_k: int = 5
    ) -> str:
        """
        Wrapper function that fetches and returns similar results as a formatted string.
        """
        results = await self.get_similar_results(query_texts, namespace, top_k)

        if isinstance(query_texts, str):
            query_texts = [query_texts]

        output_lines = []

        for query, result_set in zip(query_texts, results):
            output_lines.append(f"Target: {query}")
            output_lines.append("Found:")
            for i, match in enumerate(result_set.get("matches", []), start=1):
                entity_name = match["metadata"].get("entity_name", "Unknown")
                score = match.get("score", 0.0)
                output_lines.append(f"{i}. {entity_name} ({score:.9f} similarity score)")
            output_lines.append("") 

        return "\n".join(output_lines)
    
    async def get_similar_results_with_namespace(self, batch_queries: list[dict], top_k: int = 5) -> str:
        """
        Wrapper function to fetch and return similar results for multiple query_texts across namespaces.
        
        Args:
            batch_queries (list): A list of dictionaries with 'namespace' and 'query_texts'.
            top_k (int): Number of top matches to retrieve per query.

        Returns:
            str: A combined formatted string of results.
        """
        output_lines = []

        for item in batch_queries:
            namespace = str(item.get("namespace")).upper()
            query_texts = item.get("query_texts")

            if not namespace or not query_texts:
                continue 

            formatted_result = await self.get_formatted_similar_results(query_texts, namespace, top_k)
            output_lines.append(formatted_result)

        return "\n".join(output_lines)

    
    async def update_vector(
        self, 
        id: str, 
        namespace: str,
        new_text: str, 
        new_metadata: dict | None = None
    ) -> None:
        try:
            embedding = await self._embed_text(new_text) 
            self.index.upsert(vectors=[{
                "id": id,
                "namespace": namespace,
                "values": embedding,
                "metadata": new_metadata or {}
            }])
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
        stop=stop_after_attempt(3), 
        wait=wait_exponential(multiplier=1, min=4, max=10)
    )
    async def _embed_text(self, text: str | list[str]) -> list[float] | list[list[float]]:
        try:
            response = await self.openai.embeddings.create(
                model="text-embedding-3-small",
                input=text
            )
            return [item.embedding for item in response.data] if isinstance(text, list) else response.data[0].embedding
        except Exception as e:
            pinecone_logger.error(f"Error while embedding '{text}': {e}")
            raise
            
 