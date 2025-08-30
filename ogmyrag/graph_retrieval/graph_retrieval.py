from __future__ import annotations

import logging
import json
import asyncio
from typing import AsyncGenerator
from motor.motor_asyncio import AsyncIOMotorClient

from ogmyrag.report_retrieval.report_chunker import rag_answer_with_company_detection

from ..prompts import PROMPT
from ..llm import fetch_responses_openai
from ..util import (
    get_clean_json,
    get_formatted_ontology,
    get_formatted_openai_response,
    get_formatted_similar_entities,
)

from ..storage import (
    AsyncMongoDBStorage,
    PineconeStorage,
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
    get_formatted_cypher_retrieval_result,
    get_formatted_input_for_query_agent,
    get_formatted_cypher,
    get_formatted_validated_entities,
    get_formatted_decomposed_request,
)

graph_retrieval_logger = logging.getLogger("graph_retrieval")


class ChatAgent(BaseAgent):
    """
    An agent responsible for interacting with the user.
    """

    async def handle_task(self, **kwargs):
        """
        Parameters:
            chat_input (str),
            similarity_threshold(float),
            previous_chat_id (str)
        """
        graph_retrieval_logger.info(f"ChatAgent is called")

        system_prompt = PROMPT["CHAT"].format(
            similarity_threshold=kwargs.get("similarity_threshold", 0.5) or 0.5,
        )
        graph_retrieval_logger.debug(f"ChatAgent\nSystem prompt used:\n{system_prompt}")

        user_prompt = kwargs.get("chat_input", "") or ""
        graph_retrieval_logger.debug(f"ChatAgent\nUser prompt used:\n{user_prompt}")

        response = await fetch_responses_openai(
            model="o4-mini",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            text={"format": {"type": "text"}},
            reasoning={"effort": "medium"},
            max_output_tokens=100000,
            previous_response_id=kwargs.get("previous_chat_id", None),
            tools=[],
        )

        graph_retrieval_logger.info(
            f"ChatAgent\nChatAgent response details:\n{get_formatted_openai_response(response)}"
        )

        formatted_response = get_clean_json(response.output_text)
        formatted_response["id"] = response.id

        return formatted_response
    

class RAGAgent(BaseAgent):
    """
    An agent that runs Pinecone-based RAG and returns a structured payload.
    """
    def __init__(self, agent_name: str, pinecone_config: dict):
        super().__init__(agent_name)
        # pinecone storage for RAG
        self.pine = PineconeStorage(
            pinecone_api_key=pinecone_config["pinecone_api_key"],
            openai_api_key=pinecone_config["openai_api_key"],
        )
        self.pine.create_index_if_not_exists(
            index_name=pinecone_config["index_name"],
            dimension=pinecone_config["pinecone_dimensions"],
            metric=pinecone_config["pinecone_metric"],
            cloud=pinecone_config["pinecone_cloud"],
            region=pinecone_config["pinecone_environment"],
        )
        self.pinecone_config = pinecone_config

    async def handle_task(self, **kwargs):
        """
        Parameters (kwargs):
            user_query (str) | query (str)         [required]
            top_k (int)                            [default: 10]
            data_namespace (str)                   [default: ""]
            catalog_namespace (str)                [default: "company-catalog"]
            doc_type (str)                         [optional]
            report_type_name (str)                 [optional]
            year (str|int)                         [optional]
            score_threshold (float)                [optional]
            small_model (str)                      [default: "gpt-5-nano"]
            answer_model (str)                     [default: "gpt-5-nano"]
        """
        graph_retrieval_logger.info("RAGAgent is called")

        user_query = kwargs.get("user_query") or kwargs.get("query") or ""
        graph_retrieval_logger.debug(f"RAGAgent\nUser query used:\n{user_query}")

        if not user_query.strip():
            formatted_response = {
                "type": "RAG_RESPONSE",
                "payload": {
                    "answer": "Query is empty.",
                    "hits": [],
                    "company_used": None,
                    "known_companies": [],
                    "filter_used": {},
                    "usage": {},
                }
            }
            return formatted_response
        
        # Gather optional params
        top_k = int(kwargs.get("top_k", 10))
        data_namespace = kwargs.get("data_namespace", "")
        catalog_namespace = kwargs.get("catalog_namespace", "company-catalog")
        doc_type = kwargs.get("doc_type")
        report_type_name = kwargs.get("report_type_name")
        year = kwargs.get("year")
        year = str(year) if year is not None else None
        score_threshold = kwargs.get("score_threshold")
        small_model = kwargs.get("small_model", "gpt-5-nano")
        answer_model = kwargs.get("answer_model", "gpt-5-nano")

        # Run the end-to-end RAG
        try:
            res = await rag_answer_with_company_detection(
                pine=self.pine,
                pinecone_config=self.pinecone_config,
                query=user_query,
                top_k=top_k,
                data_namespace=data_namespace,
                catalog_namespace=catalog_namespace,
                small_model=small_model,
                answer_model=answer_model,
                doc_type=doc_type,
                report_type_name=report_type_name,
                year=year,
                score_threshold=score_threshold,
            )
            graph_retrieval_logger.info("RAGAgent completed RAG call successfully.")
        except Exception as e:
            graph_retrieval_logger.error(f"RAGAgent error during RAG call: {e}")
            res = {
                "answer": "Failed to generate an answer.",
                "hits": [],
                "company_used": None,
                "known_companies": [],
                "filter_used": {},
                "usage": {},
            }
        
        formatted_response = {
            "type": "RAG_RESPONSE",
            "payload": {
                "answer": res.get("answer", ""),
                "hits": res.get("hits", []),
                "company_used": res.get("company_used"),
                "known_companies": res.get("known_companies", []),
                "filter_used": res.get("filter_used", {}),
                "usage": res.get("usage", {}),
            }
        }

        return formatted_response



class RequestDecompositionAgent(BaseAgent):
    """
    An agent responsible for decomposing and rephrasing the user request.
    """

    async def handle_task(self, **kwargs):
        """
        Parameters:
            user_request (str),
            validated_entities (list(str)),
        """
        graph_retrieval_logger.info(f"RequestDecompositionAgent is called")

        system_prompt = PROMPT["REQUEST_DECOMPOSITION"]
        graph_retrieval_logger.debug(
            f"RequestDecompositionAgent\nSystem prompt used:\n{system_prompt}"
        )

        user_prompt = (
            kwargs.get("user_request", "")
            + "\n"
            + get_formatted_validated_entities(kwargs.get("validated_entities", []))
        )
        graph_retrieval_logger.debug(
            f"RequestDecompositionAgent\nUser prompt used:\n{user_prompt}"
        )

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
            f"RequestDecompositionAgent\nRequestDecompositionAgent response details:\n{get_formatted_openai_response(response)}"
        )

        formatted_response = get_clean_json(response.output_text)

        return formatted_response


class QueryAgent(BaseAgent):
    """
    An agent responsible for interacting with Text2CypherAgent to come up with retrieval result.
    """

    async def handle_task(self, **kwargs):
        """
        Parameters:
            user_request (str),
            ontology (dict),
            previous_response_id (str | None)
        """
        graph_retrieval_logger.info(f"QueryAgent is called")

        system_prompt = PROMPT["QUERY"].format(
            ontology=get_formatted_ontology(
                data=kwargs.get("ontology", {}), exclude_entity_fields=["llm-guidance"]
            )
        )
        graph_retrieval_logger.debug(
            f"QueryAgent\nSystem prompt used:\n{system_prompt}"
        )

        user_prompt = kwargs.get("user_request", "")
        graph_retrieval_logger.debug(f"QueryAgent\nUser prompt used:\n{user_prompt}")

        response = await fetch_responses_openai(
            model="o4-mini",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            text={"format": {"type": "text"}},
            reasoning={"effort": "high"},
            max_output_tokens=100000,
            previous_response_id=kwargs.get("previous_response_id", None),
            tools=[],
        )

        graph_retrieval_logger.info(
            f"QueryAgent\nQueryAgent response details:\n{get_formatted_openai_response(response)}"
        )

        formatted_response = get_clean_json(response.output_text)
        formatted_response["id"] = response.id

        return formatted_response


class Text2CypherAgent(BaseAgent):
    """
    An agent responsible for generating Cypher query and performing Cypher retrieval.
    """

    async def handle_task(self, **kwargs):
        """
        Parameters:
            user_query (str),
            validated_entities list(str),
            ontology (dict),
            note (str | None)
            previous_response_id (str | None)
        """
        graph_retrieval_logger.info(f"Text2CypherAgent is called")

        system_prompt = PROMPT["TEXT2CYPHER"].format(
            ontology=get_formatted_ontology(
                data=kwargs.get("ontology", {}), exclude_entity_fields=["llm-guidance"]
            )
        )
        graph_retrieval_logger.debug(
            f"Text2CypherAgent\nSystem prompt used:\n{system_prompt}"
        )

        formatted_user_query = "User Query: " + kwargs.get("user_query", "") + "\n"
        formatted_validated_entities = (
            get_formatted_validated_entities(kwargs.get("validated_entities", []))
            + "\n"
        )
        formattted_note = "Note: " + kwargs.get("note", "NA")
        user_prompt = (
            formatted_user_query + formatted_validated_entities + formattted_note
        )
        graph_retrieval_logger.debug(
            f"Text2CypherAgent\nUser prompt used:\n{user_prompt}"
        )

        response = await fetch_responses_openai(
            model="o4-mini",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            text={"format": {"type": "text"}},
            reasoning={"effort": "high"},
            max_output_tokens=100000,
            previous_response_id=kwargs.get("previous_response_id", None),
            tools=[],
        )

        graph_retrieval_logger.info(
            f"Text2CypherAgent\nText2CypherAgent response details:\n{get_formatted_openai_response(response)}"
        )

        formatted_response = get_clean_json(response.output_text)
        formatted_response["id"] = response.id

        return formatted_response


class GraphRetrievalSystem(BaseMultiAgentSystem):
    def __init__(
        self,
        mongo_client: AsyncIOMotorClient,
        ontology_config: MongoStorageConfig,
        entity_vector_config: PineconeStorageConfig,
        graphdb_config: Neo4jStorageConfig,
        rag_vector_config: PineconeStorageConfig
    ):
        super().__init__(
            {
                "ChatAgent": ChatAgent("ChatAgent"),
                "RequestDecompositionAgent": RequestDecompositionAgent(
                    "RequestDecompositionAgent"
                ),
                "QueryAgent": QueryAgent("QueryAgent"),
                "Text2CypherAgent": Text2CypherAgent("Text2CypherAgent"),
                "RAGAgent": RAGAgent("RAGAgent", rag_vector_config),
            }
        )

        try:
            self.ontology_config = ontology_config
            self.entity_vector_config = entity_vector_config

            self.async_mongo_storage = AsyncMongoDBStorage(mongo_client)
            self.pinecone_storage = PineconeStorage(
                pinecone_api_key=entity_vector_config["pinecone_api_key"],
                openai_api_key=entity_vector_config["openai_api_key"],
            )
            self.pinecone_storage.create_index_if_not_exists(
                index_name=entity_vector_config["index_name"],
                dimension=entity_vector_config["pinecone_dimensions"],
                metric=entity_vector_config["pinecone_metric"],
                cloud=entity_vector_config["pinecone_cloud"],
                region=entity_vector_config["pinecone_environment"],
            )

            self.graph_storage = AsyncNeo4jStorage(**graphdb_config)

            self.current_chat_id = None

        except Exception as e:
            graph_retrieval_logger.error(f"GraphRetrievalSystem: {e}")
            raise ValueError(f"Failed to intialize GraphRetrievalSystem: {e}")

    async def query(
        self,
        user_request: str,
        top_k_for_similarity: int,
        similarity_threshold: float = 0.5,
    ):
        # Step 1 : Pass the user request to the ChatAgent
        yield "## Calling ChatAgent..."
        chat_agent_response = await self.agents["ChatAgent"].handle_task(
            chat_input=user_request,
            similarity_threshold=similarity_threshold,
            previous_chat_id=self.current_chat_id,
        )
        self._update_current_chat_id(chat_agent_response["id"])

        # Step 3 : Check if ChatAgent returns any response to display
        if chat_agent_response["type"] == "RESPONSE_GENERATION":
            yield chat_agent_response["payload"]["response"]

        # Step 4 : Check if ChatAgent tries to call EntityValidationTool
        elif chat_agent_response["type"] == "CALLING_ENTITIES_VALIDATION_TOOL":
            # Step 4.1 : Validate the entities
            yield "Validating entities in the query..."
            similar_entities = await self.pinecone_storage.get_index(
                self.entity_vector_config["index_name"]
            ).get_similar_results(
                query_texts=chat_agent_response["payload"]["entities_to_validate"],
                top_k=top_k_for_similarity,
                score_threshold=similarity_threshold,
            )
            formatted_similar_entities = get_formatted_similar_entities(
                query_texts=chat_agent_response["payload"]["entities_to_validate"],
                results=similar_entities,
            )
            yield formatted_similar_entities

            # Step 4.2 : Feed the entities to ChatAgent for further processing
            yield "Processing validated entities..."
            chat_agent_response = await self.agents["ChatAgent"].handle_task(
                chat_input=formatted_similar_entities,
                similarity_threshold=similarity_threshold,
                previous_chat_id=self.current_chat_id,
            )
            self._update_current_chat_id(chat_agent_response["id"])

            if chat_agent_response["type"] != "RESPONSE_GENERATION":
                yield "Unexpected error occur. Please contact the developer."
            yield chat_agent_response["payload"]["response"]

        # Step 5 : Check if tries to call GraphRAGAgent
        elif chat_agent_response["type"] == "CALLING_GRAPH_RAG_AGENT":
            # Step 5.1 : Decompose and rephrase the user request
            yield "## Calling RequestDecompositionAgent"
            request_decomposition_agent_response = await self.agents[
                "RequestDecompositionAgent"
            ].handle_task(
                user_request=chat_agent_response["payload"]["user_request"],
                validated_entities=chat_agent_response["payload"]["validated_entities"],
            )
            yield get_formatted_decomposed_request(request_decomposition_agent_response)

            # Step 5.2 : Process the sub-request(s) concurrenctly
            subrequests = request_decomposition_agent_response["requests"]
            latest_ontology = await self._get_latest_ontology()
            gens = []

            for i, subrequest in enumerate(subrequests, start=1):
                agent_name = f"Query Agent {i}"
                gens.append(
                    self._process_subrequest(
                        agent_name=agent_name,
                        sub_request=subrequest["sub_request"],
                        validated_entities=subrequest["validated_entities"],
                        ontology=latest_ontology,
                    )
                )

            # Fan-in results from all subrequests
            final_response=None
            async for result in self._fan_in_generators(gens):
                yield result
                if isinstance(result, str) and result.startswith("Combined Final Response from QueryAgents"):
                    final_response = result

            # Step 5.3 : Generating final result
            yield "## Calling ChatAgent..."
            chat_agent_response = await self.agents["ChatAgent"].handle_task(
                chat_input=final_response,
                similarity_threshold=similarity_threshold,
                previous_chat_id=self.current_chat_id,
            )
            self._update_current_chat_id(chat_agent_response["id"])
            if chat_agent_response["type"] == "RESPONSE_GENERATION":
                yield chat_agent_response["payload"]["response"]
        else:
            yield "Unexpected error occur. Please contact the developer."
            
    async def rag_query(
        self,
        user_request: str,
        top_k_for_similarity: int,
        similarity_threshold: float = 0.5,
    ):
        # RAG: Pass the user query to RAG Agent
        yield "## Calling RAGAgent..."
        rag_agent_response = await self.agents["RAGAgent"].handle_task(
            user_query = user_request,
            top_k = top_k_for_similarity,
        )
        yield rag_agent_response["payload"]["answer"]

    def _update_current_chat_id(self, new_chat_id: str):
        self.current_chat_id = new_chat_id

    async def _get_latest_ontology(self) -> dict:
        try:
            return (
                await self.async_mongo_storage.get_database(
                    self.ontology_config["database_name"]
                )
                .get_collection(self.ontology_config["collection_name"])
                .read_documents({"is_latest": True})
            )[0].get("ontology", {})

        except Exception as e:
            raise LookupError("Failed to fetch latest ontology") from e

    async def _fan_in_generators(self, gens: list[AsyncGenerator[str, None]]):
        """
        Runs multiple async generators concurrently and yields their results as soon as they are available.
        """
        queue = asyncio.Queue()
        final_responses = []

        async def consume(gen: AsyncGenerator[str, None]):
            try:
                async for item in gen:
                    # Detect if this is a final response line
                    if item.startswith("**") and "Final Response" in item:
                        final_responses.append(item)
                    await queue.put(item)
            except Exception as e:
                graph_retrieval_logger.error(
                    f"GraphRetrievalSystem: Error when retrieving result {e}"
                )
            finally:
                await queue.put(None)

        # Spawn a consumer task per generator
        tasks = [asyncio.create_task(consume(gen)) for gen in gens]
        active = len(tasks)

        while active > 0:
            item = await queue.get()
            if item is None:
                active -= 1
            else:
                yield item

        # Ensure cleanup
        await asyncio.gather(*tasks)
        
        final_response_str = "\n".join(final_responses)
        graph_retrieval_logger.debug(f"Checking the final response: \n{final_response_str}")

        if final_responses:
            combined = "\n\n".join(final_responses)
            yield "Combined Final Response from QueryAgents\n" + combined

    async def _process_subrequest(
        self,
        agent_name: str,
        sub_request: str,
        validated_entities: list[str],
        ontology: dict,
        max_iteration: int = 2,
    ) -> AsyncGenerator[str, None]:
        """
        Handles a sub-request by coordinating between QueryAgent and Text2CypherAgent.
        Iteratively generates queries, translates them to Cypher, executes them,
        and refines results until a final response is produced or the iteration limit is reached.
        """

        # Track response IDs for iterative refinement
        previous_query_agent_response_id = None
        previous_text2_cypher_agent_response_id = None

        query_agent_response = None
        text2cypher_agent_response = None
        current_iteration = 0

        # Step 1 : Initial query generation
        yield f"## Calling Query Agent ({agent_name}) for sub-request '{sub_request}'..."
        query_agent_response = await self.agents["QueryAgent"].handle_task(
            user_request=get_formatted_input_for_query_agent(
                type="QUERY_GENERATION",
                payload={
                    "user_request": sub_request,
                    "validated_entities": validated_entities,
                },
            ),
            ontology=ontology,
        )
        previous_query_agent_response_id = query_agent_response["id"]

        yield (
            f"**{agent_name}**:\n"
            f"Query: {query_agent_response['payload']['query']}\n"
            f"**Validated Entities:** {query_agent_response['payload']['validated_entities']}\n"
            f"**Note:** {query_agent_response['payload']['note'] or 'NA'}"
        )

        # Step 2 : Iterative refinement process
        if query_agent_response["type"] == "QUERY":
            while current_iteration < max_iteration:
                # Step 2.1: Convert natural query → Cypher
                yield f"## Calling Text2Cypher Agent for {agent_name}..."
                text2cypher_agent_response = await self.agents["Text2CypherAgent"].handle_task(
                    user_query=query_agent_response["payload"]["query"],
                    validated_entities=query_agent_response["payload"]["validated_entities"],
                    ontology=ontology,
                    note=query_agent_response["payload"]["note"],
                    previous_response_id=previous_text2_cypher_agent_response_id,
                )
                previous_text2_cypher_agent_response_id = text2cypher_agent_response["id"]

                # Step 2.2: Run Cypher query
                cypher_retrieval_result = await self.graph_storage.run_query(
                    query=text2cypher_agent_response["cypher_query"],
                    parameters=text2cypher_agent_response["parameters"],
                )

                # Step 2.3: Report Cypher + results
                yield (
                    f"**Response by Text2CypherAgent to {agent_name}:**\n"
                    f"**Cypher Query:** {get_formatted_cypher(query=text2cypher_agent_response['cypher_query'], params=text2cypher_agent_response['parameters'])}\n"
                    f"**Note:** {text2cypher_agent_response['note']}\n"
                    f"**Retrieval Result:**\n{get_formatted_cypher_retrieval_result(cypher_retrieval_result)}"
                )
                yield f"## Calling Query Agent ({agent_name}) to evaluate retrieval result..."

                # Step 2.4: If final iteration → force final report
                if current_iteration == max_iteration - 1:
                    yield f"## Max iteration reached for Query Agent ({agent_name}), generating final response..."
                    query_agent_response = await self.agents["QueryAgent"].handle_task(
                        user_request=get_formatted_input_for_query_agent(
                            type="REPORT_GENERATION",
                            payload={
                                "retrieval_result": get_formatted_cypher_retrieval_result(cypher_retrieval_result),
                                "cypher_query": get_formatted_cypher(
                                    query=text2cypher_agent_response["cypher_query"],
                                    params=text2cypher_agent_response["parameters"],
                                ),
                                "note": text2cypher_agent_response["note"],
                            },
                        ),
                        ontology=ontology,
                        previous_response_id=previous_query_agent_response_id,
                    )
                    previous_query_agent_response_id = query_agent_response["id"]

                    yield (
                        f"**{agent_name}**:\n"
                        f"**Final Response from {agent_name}:**  {query_agent_response['payload']['response']}\n"
                        f"**Note:** {query_agent_response['payload']['note'] or 'NA'}"
                    )
                    break

                else:
                    # Step 2.5: Intermediate evaluation by QueryAgent
                    query_agent_response = await self.agents["QueryAgent"].handle_task(
                        user_request=get_formatted_input_for_query_agent(
                            type="RETRIEVAL_RESULT_EVALUATION",
                            payload={
                                "retrieval_result": get_formatted_cypher_retrieval_result(cypher_retrieval_result),
                                "cypher_query": get_formatted_cypher(
                                    query=text2cypher_agent_response["cypher_query"],
                                    params=text2cypher_agent_response["parameters"],
                                ),
                                "note": text2cypher_agent_response["note"],
                            },
                        ),
                        ontology=ontology,
                        previous_response_id=previous_query_agent_response_id,
                    )
                    previous_query_agent_response_id = query_agent_response["id"]

                    # Step 2.6: Decide whether to re-query or finalize
                    if query_agent_response["type"] == "QUERY":
                        yield (
                            f"**{agent_name}**:\n"
                            f"Query: {query_agent_response['payload']['query']}\n"
                            f"**Validated Entities:** {query_agent_response['payload']['validated_entities']}\n"
                            f"**Note:** {query_agent_response['payload']['note'] or 'NA'}"
                        )
                    elif query_agent_response["type"] == "FINAL_RESPONSE":
                        yield (
                            f"**{agent_name}**:\n"
                            f"**Final Response from {agent_name}:** {query_agent_response['payload']['response']}\n"
                            f"**Note:** {query_agent_response['payload']['note'] or 'NA'}"
                        )
                        break
                current_iteration += 1
        else:
            yield f"**{agent_name}:** Unexpected error occurred. Please contact the developer."

