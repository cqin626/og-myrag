import logging
import tiktoken
from typing import List, Dict, Any, Tuple
from openai import OpenAI
from pinecone import Pinecone, ServerlessSpec


retrieval_logger = logging.getLogger("retrieval")


class RetrievalEmbedder:
    """
    Take a list of text-chunks and upsert them into Pinecone
    """
    def __init__(
            self,
            openai_api_key: str,
            pinecone_api_key: str,
            embed_model: str,
            index_name: str,
            dimension: int
    ):
        # OpenAI client for embeddings
        self.openai = OpenAI(api_key=openai_api_key)
        self.encoder = tiktoken.encoding_for_model(embed_model)
        self.embed_model = embed_model

        # Pinecone client
        self.pinecone = Pinecone(api_key=pinecone_api_key)
        existing = self.pinecone.list_indexes().names()
        if index_name not in existing:
            self.pinecone.create_index(
                name=index_name,
                dimension=dimension,
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1")
            )

        self.index = self.pinecone.Index(index_name)

        self.total_tokens = 0

    def embed(self, text: str) -> List[float]:
        """
        Return an embedding vector for the given text.
        """
        n_tokens = len(self.encoder.encode(text))
        self.total_tokens += n_tokens

        response = self.openai.embeddings.create(
            model=self.embed_model,
            input=text
        )
        #retrieval_logger.info("Embedding text of %d tokens", len(self.encoder.encode(text)))
        return response.data[0].embedding
    
    def upsert_chunks(self, chunks: List[str], namespace: str, year: int):
        """
        Chunk list → [(id, vector, meta)] → upsert in batches into Pinecone.
        """
        vectors: List[Tuple[str, List[float], Dict[str, Any]]] = []

        for i, chunk in enumerate(chunks):
            vid = f"{namespace}-{year}-chunk-{i}"
            emb = self.embed(chunk)
            meta = {
                "company": namespace,
                "year": str(year),
                "chunk_index": i,
                "text": chunk
            }
            vectors.append((vid, emb, meta))
        
        # upsert in batches of 100
        BATCH = 100
        for start in range(0, len(vectors), BATCH):
            self.index.upsert(vectors[start : start + BATCH], namespace=namespace)

        retrieval_logger.info("Upserted %d chunks for %s (%d tokens total)", len(chunks), namespace, self.total_tokens)