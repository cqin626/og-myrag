from typing import List
import tiktoken
import logging
from openai import OpenAI
from pinecone import Pinecone

retrieval_logger = logging.getLogger("retrieval")


class RetrievalExtractor:
    """
    Given a natural‐language query, fetch the top‐k most relevant
    chunks from Pinecone.
    """

    def __init__(
        self,
        openai_api_key: str,
        pinecone_api_key: str,
        embed_model: str,
        index_name: str
    ):
        self.openai = OpenAI(api_key=openai_api_key)
        self.encoder = tiktoken.encoding_for_model(embed_model)
        self.embed_model = embed_model

        self.pinecone = Pinecone(api_key=pinecone_api_key)
        self.index = self.pinecone.Index(index_name)


    def embed_query(self, query: str) -> List[float]:
        """Embed the user's query."""
        resp = self.openai.embeddings.create(model=self.embed_model, input=query)
        retrieval_logger.info("Embedding query: %r", query)
        return resp.data[0].embedding
    
    def retrieve_chunks(
            self,
            query: str,
            namespace: str,
            top_k: int = 10,
    ) -> List[str]:
        """
        Given a query, return the top-k most relevant chunks from Pinecone.
        """
        vector = self.embed_query(query)
        result = self.index.query(
            vector=vector,
            namespace=namespace,
            top_k=top_k,
            include_metadata=True
        )
        retrieval_logger.info("Retrieved chunks: %r", [match.metadata["text"] for match in result.matches])
        return [match.metadata["text"] for match in result.matches]
    

