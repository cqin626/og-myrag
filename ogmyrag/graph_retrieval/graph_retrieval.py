from __future__ import annotations

import logging
import asyncio
from ..prompts import PROMPT
from ..llm import fetch_responses_openai
from ..util import (
    get_clean_json,
    get_formatted_ontology,
    get_formatted_openai_response,
)

from ..storage import (
    MongoDBStorage,
    AsyncMongoDBStorage,
    PineconeStorage,
    Neo4jStorage,
    AsyncNeo4jStorage,
)

from ..base import (
    BaseAgent,
    BaseMultiAgentSystem,
    MongoStorageConfig,
    PineconeStorageConfig,
    Neo4jStorageConfig,
)

from .graph_retrieval_util import (
    get_formatted_query_formulation_message,
    get_formatted_text2cypher_message,
)

graph_retrieval_logger = logging.getLogger("graph_retrieval")


class QueryFormulationAgent(BaseAgent):
    """
    An agent responsible for converting user requests into queries suitable for input to the Text2CypherAgent.
    """

    async def handle_task(self, **kwargs):
        """
        Parameters:
           user_request (str): The request given by user.
           previous_response_id (str): Previous response id.
           ontology (dict): The existing ontology.
           max_query_attempt (int): Max query attempt.
           max_query_per_attempt (int): Max query per attempt.
           current_query_attempt (int): Current query attempt.
        """
        formatted_ontology = get_formatted_ontology(
            data=kwargs.get("ontology", {}) or {},
        )

        system_prompt = PROMPT["GRAPH_QUERY_FORMULATION_AGENT"].format(
            ontology=formatted_ontology,
            max_query_attempt=kwargs.get("max_query_attempt", 1) or 1,
            max_query_per_attempt=kwargs.get("max_query_per_attempt", 1) or 1,
            current_query_attempt=kwargs.get("current_query_attempt", 0) or 0,
        )

        graph_retrieval_logger.info(f"QueryFormulationAgent is called")

        try:
            response = await fetch_responses_openai(
                model="o4-mini",
                system_prompt=system_prompt,
                user_prompt=kwargs.get("user_request", "") or "",
                text={"format": {"type": "text"}},
                reasoning={"effort": "high"},
                max_output_tokens=100000,
                previous_response_id=kwargs.get("previous_response_id", None) or None,
                tools=[],
            )

            graph_retrieval_logger.info(
                f"QueryFormulationAgent\nResponse details:\n{get_formatted_openai_response(response)}"
            )
            return response

        except Exception as e:
            graph_retrieval_logger.error(
                f"QueryFormulationAgent\nRetrieval failed: {str(e)}"
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
           note (str): Additional note for the Text2CypherAgent.
           ontology (dict): The existing ontology.
        """

        formatted_ontology = get_formatted_ontology(
            data=kwargs.get("ontology", {}) or {},
        )

        system_prompt = PROMPT["TEXT_TO_CYPHER_V2"].format(
            ontology=formatted_ontology,
            potential_entities=kwargs.get("potential_entities", "") or "",
        )
        user_prompt = f"User query: {kwargs.get('query', '')}\nAdditional note: {kwargs.get('note', 'NA')}"

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
            return response

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
                "QueryFormulationAgent": QueryFormulationAgent("QueryFormulationAgent"),
                "Text2CypherAgent": Text2CypherAgent("Text2CypherAgent"),
            }
        )

        try:
            self.onto_storage = MongoDBStorage(ontology_config["connection_uri"])
            self.onto_storage.use_database(ontology_config["database_name"])
            self.onto_storage.use_collection(ontology_config["collection_name"])

            self.entity_vector_storage = PineconeStorage(**entity_vector_config)

            self.graph_storage = AsyncNeo4jStorage(**graphdb_config)

        except Exception as e:
            graph_retrieval_logger.error(f"GraphRetrievalSystem: {e}")
            raise ValueError(f"Failed to intialize GraphRetrievalSystem: {e}")

    # async def query_from_graph(self, user_request: str):
    #     try:
    #         graph_retrieval_logger.info("GraphRetrievalSystem\nPreparing ontology...")
    #         latest_onto = (
    #             self.onto_storage.read_documents({"is_latest": True})[0].get(
    #                 "ontology", {}
    #             )
    #             or {}
    #         )
    #     except Exception as e:
    #         graph_retrieval_logger.error(
    #             f"GraphRetrievalSystem\nError while getting latest ontology:{e}"
    #         )
    #         raise ValueError(f"Failed to latest ontology: {e}")

    #     raw_response_from_user2requestagent = (
    #         await self.get_response_from_user2requestagent(user_request)
    #     )

    #     response_from_user2requestagent = get_clean_json(
    #         raw_response_from_user2requestagent
    #     )

    #     potential_entities = (
    #         await self.entity_vector_storage.get_formatted_similar_results_no_namespace(
    #             query_texts=response_from_user2requestagent["entities_to_validate"],
    #             top_k=20,
    #         )
    #     )

    #     graph_retrieval_logger.info(f"Potential entities:\n {potential_entities}")

    #     query = response_from_user2requestagent["generated_query"]

    #     raw_response_from_text2cypher = await self.agents[
    #         "Text2CypherAgent"
    #     ].handle_task(
    #         ontology=latest_onto, query=query, potential_entities=potential_entities
    #     )

    #     response_from_text2cypher = get_clean_json(raw_response_from_text2cypher)

    #     return response_from_text2cypher["cypher_query"]

    async def query_from_graph(self, user_request: str):
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
            raise ValueError(f"Failed to fetch the latest ontology: {e}")

        # Step 2 : Call QueryFormulationAgent

        is_final_report_produced = False
        current_query_attempt = 0
        previous_response_id = None

        while not is_final_report_produced and current_query_attempt < 3:
            yield "## Calling QueryFormulationAgent..."

            query_formulation_agent_raw_response = (
                await self.get_query_formulation_agent_response(
                    user_request=user_request,
                    ontology=latest_onto,
                    current_query_attempt=current_query_attempt,
                    previous_response_id=previous_response_id,
                )
            )

            previous_response_id = query_formulation_agent_raw_response.id

            query_formulation_agent_response = get_clean_json(
                query_formulation_agent_raw_response.output_text
            )

            if query_formulation_agent_response["response_type"] == "QUERY_FORMULATION":
                yield f"## Response by: QueryFormulationAgent\n {get_formatted_query_formulation_message(query_formulation_agent_response)}"

                text2cypher_tasks = []

                for item in query_formulation_agent_response["response"]:
                    text2cypher_tasks.append(
                        self.get_text_to_cypher_agent_response(
                            query=item.get("query", ""),
                            potential_entities=item.get("entities_to_validate", []),
                            note=item.get("note", ""),
                            ontology=latest_onto,
                        )
                    )

                yield "## Calling Text2CypherAgent..."

                text2cypher_response = {
                    "response_type": "RETRIEVAL_RESULT",
                    "response": [],
                }

                conversion_results = await asyncio.gather(*text2cypher_tasks)

                for result in conversion_results:
                    text2cypher_response["response"].append(result)

                yield f"## Response by: Text2CypherAgent\n {get_formatted_text2cypher_message(text2cypher_response)}"
                
                yield "## Calling QueryFormulationAgent..."
                query_formulation_agent_raw_response = (
                    await self.get_query_formulation_agent_response(
                        user_request=str(text2cypher_response),
                        ontology=latest_onto,
                        current_query_attempt=current_query_attempt,
                        previous_response_id=previous_response_id,
                    )
                )

                previous_response_id = query_formulation_agent_raw_response.id
                
                query_formulation_agent_response = get_clean_json(
                    query_formulation_agent_raw_response.output_text
                )

            if query_formulation_agent_response["response_type"] == "FINAL_REPORT":
                is_final_report_produced = True
                yield f"## Response by: QueryFormulationAgent\n {get_formatted_query_formulation_message(query_formulation_agent_response)}"

            current_query_attempt += 1

    async def get_query_formulation_agent_response(
        self,
        user_request: str,
        ontology: dict,
        current_query_attempt: int,
        previous_response_id: str,
    ):
        response = await self.agents["QueryFormulationAgent"].handle_task(
            ontology=ontology,
            user_request=user_request,
            previous_response_id=previous_response_id,
            max_query_attempt=3,
            max_query_per_attempt=5,
            current_query_attempt=current_query_attempt,
        )

        return response

    async def get_text_to_cypher_agent_response(
        self, query: str, potential_entities: list, note: str, ontology: dict
    ):
        validated_entities = (
            await self.entity_vector_storage.get_formatted_similar_results_no_namespace(
                query_texts=potential_entities,
                top_k=20,
            )
        )

        graph_retrieval_logger.info(
            f"GraphRetrievalSystem\nValidated entities:\n{validated_entities}"
        )

        raw_response = await self.agents["Text2CypherAgent"].handle_task(
            ontology=ontology,
            query=query,
            potential_entities=validated_entities,
            note=note,
        )
        response = get_clean_json(raw_response.output_text)

        cypher_query = response.get("cypher_query", "")
        parameters = response.get("parameters", {})

        if cypher_query and parameters:
            response["obtained_data"] = await self.get_cypher_query_response(
                query=cypher_query, parameters=parameters
            )

        return response

    async def get_cypher_query_response(self, query: str, parameters: dict):
        try:
            graph_retrieval_logger.info(
                "GraphRetrievalSystem\nRetrieving data using Cypher query..."
            )
            return await self.graph_storage.run_query(
                query=query, parameters=parameters
            )
        except Exception as e:
            graph_retrieval_logger.error(
                f"GraphRetrievalSystem\nError while retrieving data using Cypher query:{e}"
            )
            return []
