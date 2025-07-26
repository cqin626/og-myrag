from __future__ import annotations

import logging
import asyncio

from collections import defaultdict

from ..prompts import PROMPT
from ..llm import fetch_responses_openai
from ..util import (
    get_clean_json,
    get_formatted_ontology,
    get_formatted_openai_response,
    get_formatted_entities_and_relationships,
    get_formatted_current_datetime,
)

from ..storage import MongoDBStorage, AsyncMongoDBStorage, PineconeStorage, Neo4jStorage

from ..base import (
    BaseAgent,
    BaseMultiAgentSystem,
    MongoStorageConfig,
    PineconeStorageConfig,
    Neo4jStorageConfig,
)

graph_retrieval_logger = logging.getLogger("graph_retrieval")


class UserRequest2QueryAgent(BaseAgent):
    """
    An agent responsible for converting user requests into queries suitable for input to the Text2CypherAgent.
    """

    async def handle_task(self, **kwargs) -> str:
        """
        Parameters:
           user_request (str): The request given by user.
           ontology (dict): The existing ontology.
        """
        formatted_ontology = get_formatted_ontology(
            data=kwargs.get("ontology", {}) or {},
        )

        system_prompt = PROMPT["USER_REQUEST_TO_RETRIEVAL_QUERY"].format(
            ontology=formatted_ontology,
        )

        graph_retrieval_logger.info(f"UserRequest2QueryAgent is called")

        try:
            response = await fetch_responses_openai(
                model="o4-mini",
                system_prompt=system_prompt,
                user_prompt=kwargs.get("user_request", "") or "",
                text={"format": {"type": "text"}},
                reasoning={"effort": "medium"},
                max_output_tokens=100000,
                tools=[],
            )

            graph_retrieval_logger.info(
                f"UserRequest2QueryAgent\nUser request to retrieval query response details:\n{get_formatted_openai_response(response)}"
            )
            return response.output_text

        except Exception as e:
            graph_retrieval_logger.error(
                f"UserRequest2QueryAgent\nConversion from user request to query failed: {str(e)}"
            )
            return ""


class Text2CypherAgent(BaseAgent):
    """
    An agent responsible for converting query written in natural language into Cypher query.
    """

    async def handle_task(self, **kwargs) -> str:
        """
        Parameters:
           query (str): The query written in natural language.
           potential_entities (str): Potential entities to query on.
           ontology (dict): The existing ontology.
        """
        formatted_ontology = get_formatted_ontology(
            data=kwargs.get("ontology", {}) or {},
        )

        system_prompt = PROMPT["TEXT_TO_CYPHER_V2"].format(
            ontology=formatted_ontology,
        )

        user_prompt = f"User query: {kwargs.get('query', '') or ''}\n Validated entities: {kwargs.get('potential_entities', '') or ''}"

        graph_retrieval_logger.info(f"Text2CypherAgent is called")

        try:
            response = await fetch_responses_openai(
                model="o4-mini",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                text={"format": {"type": "text"}},
                reasoning={"effort": "medium"},
                max_output_tokens=100000,
                tools=[],
            )

            graph_retrieval_logger.info(
                f"Text2CypherAgent\nText2Cypher response details:\n{get_formatted_openai_response(response)}"
            )
            return response.output_text

        except Exception as e:
            graph_retrieval_logger.error(
                f"Text2CypherAgent\nConversion from query to Cypher failed: {str(e)}"
            )
            return ""


class GraphRetrievalSystem(BaseMultiAgentSystem):
    def __init__(
        self,
        ontology_config: MongoStorageConfig,
        entity_vector_config: PineconeStorageConfig,
        graphdb_config: Neo4jStorageConfig,
    ):
        super().__init__(
            {
                "UserRequest2QueryAgent": UserRequest2QueryAgent(
                    "UserRequest2QueryAgent"
                ),
                "Text2CypherAgent": Text2CypherAgent("Text2CypherAgent"),
            }
        )

        try:
            self.onto_storage = MongoDBStorage(ontology_config["connection_uri"])
            self.onto_storage.use_database(ontology_config["database_name"])
            self.onto_storage.use_collection(ontology_config["collection_name"])

            self.entity_vector_storage = PineconeStorage(**entity_vector_config)

            self.graph_storage = Neo4jStorage(**graphdb_config)

        except Exception as e:
            graph_retrieval_logger.error(f"GraphRetrievalSystem: {e}")
            raise ValueError(f"Failed to intialize GraphRetrievalSystem: {e}")

    async def query_from_graph(self, user_request: str):
        try:
            graph_retrieval_logger.info("GraphRetrievalSystem\nPreparing ontology...")
            latest_onto = (
                self.onto_storage.read_documents({"is_latest": True})[0].get(
                    "ontology", {}
                )
                or {}
            )
        except Exception as e:
            graph_retrieval_logger.error(
                f"GraphRetrievalSystem\nError while getting latest ontology:{e}"
            )
            raise ValueError(f"Failed to latest ontology: {e}")

        raw_response_from_user2requestagent = (
            await self.get_response_from_user2requestagent(user_request)
        )

        response_from_user2requestagent = get_clean_json(
            raw_response_from_user2requestagent
        )

        potential_entities = (
            await self.entity_vector_storage.get_formatted_similar_results_no_namespace(
                query_texts=response_from_user2requestagent["entities_to_validate"],
                top_k=20,
            )
        )

        graph_retrieval_logger.info(f"Potential entities:\n {potential_entities}")

        query = response_from_user2requestagent["generated_query"]

        raw_response_from_text2cypher = await self.agents[
            "Text2CypherAgent"
        ].handle_task(
            ontology=latest_onto, query=query, potential_entities=potential_entities
        )

        response_from_text2cypher = get_clean_json(raw_response_from_text2cypher)

        return response_from_text2cypher["cypher_query"]

    async def get_response_from_user2requestagent(self, user_request: str):
        # Step 1 : Get the latest ontology
        try:
            graph_retrieval_logger.info("GraphRetrievalSystem\nPreparing ontology...")
            latest_onto = (
                self.onto_storage.read_documents({"is_latest": True})[0].get(
                    "ontology", {}
                )
                or {}
            )
        except Exception as e:
            graph_retrieval_logger.error(
                f"GraphRetrievalSystem\nError while getting latest ontology:{e}"
            )
            raise ValueError(f"Failed to latest ontology: {e}")

        # Step 2 : Call UserRequest2QueryAgent
        return await self.agents["UserRequest2QueryAgent"].handle_task(
            ontology=latest_onto,
            user_request=user_request,
        )
