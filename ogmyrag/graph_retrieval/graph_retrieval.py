from __future__ import annotations

import logging
import json
import asyncio
from typing import AsyncGenerator
from motor.motor_asyncio import AsyncIOMotorClient

from ogmyrag.report_retrieval.report_chunker import rag_answer_with_company_detection

from ..prompts import PROMPT
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
    BaseLLMClient,
    BaseMultiAgentSystem,
    MongoStorageConfig,
    PineconeStorageConfig,
    Neo4jStorageConfig,
)

from .graph_retrieval_util import (
    get_stringified_cypher_retrieval_result,
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

    def __init__(self, agent_name: str, agent_config: dict):
        super().__init__(agent_name=agent_name, agent_config=agent_config)

    async def handle_task(self, **kwargs):
        """
        Parameters:
            chat_input (str),
            similarity_threshold(float),
            previous_chat_id (str),
        """
        graph_retrieval_logger.info(f"ChatAgent is called")

        system_prompt = PROMPT["CHAT"].format(
            similarity_threshold=kwargs.get("similarity_threshold", 0.5) or 0.5,
        )
        graph_retrieval_logger.debug(f"ChatAgent\nSystem prompt used:\n{system_prompt}")

        user_prompt = kwargs.get("chat_input", "") or ""
        graph_retrieval_logger.debug(f"ChatAgent\nUser prompt used:\n{user_prompt}")

        graph_retrieval_logger.debug(
            f"ChatAgent\nAgent configuration used:\n{str(self.agent_config)}"
        )

        response = await self.agent_system.llm_client.fetch_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            previous_response_id=kwargs.get("previous_chat_id", None),
            **self.agent_config,
        )

        graph_retrieval_logger.info(
            f"ChatAgent\nChatAgent response details:\n{get_formatted_openai_response(response)}"
        )

        formatted_response = get_clean_json(response.output_text)
        formatted_response["id"] = response.id

        return formatted_response


class VectorRAGAgent(BaseAgent):
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
            # Single or batch:
            user_query (str) | query (str)            [OR]
            user_queries (list[str]) | queries(list[str])

            # Options applied to all queries:
            top_k (int)                               [default: 10]
            data_namespace (str)                      [default: ""]
            catalog_namespace (str)                   [default: "company-catalog"]
            doc_type (str)                            [optional]
            report_type_name (str)                    [optional]
            year (str|int)                            [optional]
            score_threshold (float)                   [optional]
            small_model (str)                         [default: "gpt-5-nano"]
            answer_model (str)                        [default: "gpt-5-nano"]

            # Concurrency:
            max_concurrency (int)                     [default: 4]
        """
        graph_retrieval_logger.info("VectorRAGAgent is called")

        def _clip(s: str, n: int = 300) -> str:
            s = (s or "").replace("\n", " ").strip()
            return s if len(s) <= n else s[:n] + "…"

        def _fmt_score(x) -> str:
            try:
                return f"{float(x):.3f}"
            except Exception:
                return str(x)

        # ---- normalize to a single query ----
        q = (kwargs.get("user_query") or kwargs.get("query") or "").strip()
        if not q:
            graph_retrieval_logger.warning(
                "Empty query received; returning empty answer."
            )
            return {"type": "RAG_RESPONSE", "payload": {"answer": ""}}

        graph_retrieval_logger.debug("VectorRAGAgent\nQuery used: %s", q)

        # ---- options ----
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
        max_concurrency = int(kwargs.get("max_concurrency", 4))  # forwarded to RAG

        # ---- minimal-change debug knobs (logging only) ----
        log_hits = bool(kwargs.get("log_hits", True))
        hits_per_subquery = int(kwargs.get("hits_per_subquery", 5))
        hits_preview_chars = int(kwargs.get("hits_preview_chars", 240))

        # ---- call the new RAG (which returns {"RAG_RESPONSE": <final answer>}) ----
        try:
            res = await rag_answer_with_company_detection(
                pine=self.pine,
                pinecone_config=self.pinecone_config,
                query=q,
                top_k=top_k,
                data_namespace=data_namespace,
                catalog_namespace=catalog_namespace,
                small_model=small_model,
                answer_model=answer_model,
                doc_type=doc_type,
                report_type_name=report_type_name,
                year=year,
                score_threshold=score_threshold,
                max_concurrency=max_concurrency,
                # request compact hits only if we intend to log them
                return_hits=log_hits,
                hits_per_subquery=hits_per_subquery,
                hits_preview_chars=hits_preview_chars,
            )
            graph_retrieval_logger.info("VectorRAGAgent: completed RAG for query=%r", q)
            final_answer = res.get("RAG_RESPONSE", "")
            graph_retrieval_logger.debug(
                "RAG_RESPONSE length=%d preview=%s",
                len(final_answer or ""),
                final_answer,
            )

            # ---- minimal-change: debug-log retrieved hits (not added to payload) ----
            if log_hits:
                dbg = (res or {}).get("RAG_DEBUG")
                if not dbg:
                    graph_retrieval_logger.warning(
                        "log_hits=True but no RAG_DEBUG returned."
                    )
                else:
                    subs = dbg.get("subqueries") or []
                    graph_retrieval_logger.debug("Subqueries (%d): %s", len(subs), subs)
                    for i, ps in enumerate(dbg.get("per_sub", []), 1):
                        graph_retrieval_logger.debug(
                            "Subquery #%d: %s | company=%r | normalized=%s",
                            i,
                            _clip(ps.get("subquery") or "", 300),
                            ps.get("company_used"),
                            _clip(ps.get("normalized_search_query") or "", 300),
                        )
                        hits = ps.get("hits") or []
                        graph_retrieval_logger.debug("  Hits returned: %d", len(hits))
                        for idx, h in enumerate(hits, 1):
                            hit_payload = {
                                "idx": idx,
                                "id": h.get("id"),
                                "score": h.get("score"),
                                "score_fmt": _fmt_score(h.get("score")),
                                "company": h.get("company"),
                                "section": h.get("section"),
                                "chunk_no": h.get("chunk_no"),
                                "year": h.get("year"),
                                "type": h.get("type"),
                                "snippet": h.get("snippet") or "",
                            }
                            graph_retrieval_logger.debug(
                                "    hit:\n%s",
                                json.dumps(hit_payload, ensure_ascii=False, indent=2),
                            )
        except Exception as e:
            graph_retrieval_logger.error(
                "VectorRAGAgent error during RAG call for %r: %s", q, e
            )
            final_answer = "Failed to generate an answer."

        # ---- single response ----
        return {
            "type": "RAG_RESPONSE",
            "payload": {"answer": final_answer},
        }


class RequestDecompositionAgent(BaseAgent):
    """
    An agent responsible for decomposing and rephrasing the user request.
    """
    def __init__(self, agent_name: str, agent_config: dict):
        super().__init__(agent_name=agent_name, agent_config=agent_config)
        
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

        graph_retrieval_logger.debug(
            f"RequestDecompositionAgent\nAgent configuration used:\n{str(self.agent_config)}"
        )

        response = await self.agent_system.llm_client.fetch_response(
            system_prompt=system_prompt, user_prompt=user_prompt, **self.agent_config
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
    
    def __init__(self, agent_name: str, agent_config: dict):
        super().__init__(agent_name=agent_name, agent_config=agent_config)

    async def handle_task(self, **kwargs):
        """
        Parameters:
            user_request (str),
            ontology (dict),
            previous_response_id (str | None),
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

        graph_retrieval_logger.debug(
            f"QueryAgent\nAgent configuration used:\n{str(self.agent_config)}"
        )

        response = await self.agent_system.llm_client.fetch_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            previous_response_id=kwargs.get("previous_response_id", None),
            **self.agent_config,
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
    
    def __init__(self, agent_name: str, agent_config: dict):
        super().__init__(agent_name=agent_name, agent_config=agent_config)

    async def handle_task(self, **kwargs):
        """
        Parameters:
            user_query (str),
            validated_entities list(str),
            ontology (dict),
            note (str | None),
            previous_response_id (str | None),
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

        graph_retrieval_logger.debug(
            f"Text2CypherAgent\nModel configuration used:\n{str(self.agent_config)}"
        )

        response = await self.agent_system.llm_client.fetch_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            previous_response_id=kwargs.get("previous_response_id", None),
            **self.agent_config,
        )

        graph_retrieval_logger.info(
            f"Text2CypherAgent\nText2CypherAgent response details:\n{get_formatted_openai_response(response)}"
        )

        formatted_response = get_clean_json(response.output_text)
        formatted_response["id"] = response.id

        return formatted_response


class RetrievalResultCompilationAgent(BaseAgent):
    """
    An agent responsible for compiling Cypher retrieval result.
    """
    
    def __init__(self, agent_name: str, agent_config: dict):
        super().__init__(agent_name=agent_name, agent_config=agent_config)

    async def handle_task(self, **kwargs):
        """
        Parameters:
            formatted_cypher_query (str),
            formatted_retrieval_result (str),
        """
        graph_retrieval_logger.info(f"RetrievalResultCompilationAgent is called")

        system_prompt = PROMPT["RETRIEVAL_RESULT_COMILATION"]
        graph_retrieval_logger.debug(
            f"RetrievalResultCompilationAgent\nSystem prompt used:\n{system_prompt}"
        )

        formatted_user_query = "Cypher query: " + kwargs.get(
            "formatted_cypher_query", ""
        )
        formatted_retrieval_result = "Retrieval result: " + kwargs.get(
            "formatted_retrieval_result", ""
        )
        user_prompt = formatted_user_query + "\n" + formatted_retrieval_result
        graph_retrieval_logger.debug(
            f"RetrievalResultCompilationAgent\nUser prompt used:\n{user_prompt}"
        )

        graph_retrieval_logger.debug(
            f"RetrievalResultCompilationAgent\nModel configuration used:\n{str(self.agent_config)}"
        )

        response = await self.agent_system.llm_client.fetch_response(
            system_prompt=system_prompt, user_prompt=user_prompt, **self.agent_config
        )

        graph_retrieval_logger.info(
            f"RetrievalResultCompilationAgent\nText2CypherAgent response details:\n{get_formatted_openai_response(response)}"
        )

        return get_clean_json(response.output_text)


class GraphRetrievalSystem(BaseMultiAgentSystem):
    def __init__(
        self,
        mongo_client: AsyncIOMotorClient,
        ontology_config: MongoStorageConfig,
        entity_vector_config: PineconeStorageConfig,
        graphdb_config: Neo4jStorageConfig,
        rag_vector_config: PineconeStorageConfig,
        llm_client: BaseLLMClient,
        agent_configs: dict[str, dict],
    ):
        super().__init__(
            agents={
                "ChatAgent": ChatAgent(
                    agent_name="ChatAgent",
                    agent_config=agent_configs["ChatAgent"],
                ),
                "RequestDecompositionAgent": RequestDecompositionAgent(
                    agent_name="RequestDecompositionAgent",
                    agent_config=agent_configs["RequestDecompositionAgent"],
                ),
                "QueryAgent": QueryAgent(
                    agent_name="QueryAgent",
                    agent_config=agent_configs["QueryAgent"],
                ),
                "Text2CypherAgent": Text2CypherAgent(
                    agent_name="Text2CypherAgent",
                    agent_config=agent_configs["Text2CypherAgent"],
                ),
                "VectorRAGAgent": VectorRAGAgent(
                    agent_name="VectorRAGAgent", pinecone_config=rag_vector_config
                ),
                "RetrievalResultCompilationAgent": RetrievalResultCompilationAgent(
                    agent_name="RetrievalResultCompilationAgent",
                    agent_config=agent_configs["RetrievalResultCompilationAgent"],
                ),
            },
            llm_client=llm_client,
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
        max_tool_call: int = 3,
    ):
        yield "## Calling ChatAgent..."
        chat_agent_response = await self.agents["ChatAgent"].handle_task(
            chat_input=user_request,
            similarity_threshold=similarity_threshold,
            previous_chat_id=self.current_chat_id,
        )

        tool_call = 0
        while True:
            self._update_current_chat_id(chat_agent_response["id"])

            if chat_agent_response["type"] == "RESPONSE_GENERATION":
                yield chat_agent_response["payload"]["response"]
                break

            if tool_call >= max_tool_call:
                yield f"**Maximum number of tool calls ({max_tool_call}) reached. Forcing final response generation...**"
                final_response_generation = await self.agents["ChatAgent"].handle_task(
                    chat_input="You have reached the maximum number of tool calls. You must now generate the final result based on the information and context you have gathered so far, regardless of its quality. Do not call any more tools.",
                    similarity_threshold=similarity_threshold,
                    previous_chat_id=self.current_chat_id,
                )
                if final_response_generation["type"] == "RESPONSE_GENERATION":
                    yield final_response_generation["payload"]["response"]
                else:
                    yield "**Agent failed to generate a final response after reaching the tool call limit.**"
                break

            if chat_agent_response["type"] == "CALLING_ENTITY_VALIDATION_TOOL":
                yield "## Calling EntityValidationTool"
                yield "**Validating entities in the query...**"
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

                yield "**Processing validated entities...**"
                chat_agent_response = await self.agents["ChatAgent"].handle_task(
                    chat_input=formatted_similar_entities,
                    similarity_threshold=similarity_threshold,
                    previous_chat_id=self.current_chat_id,
                )

            elif chat_agent_response["type"] == "CALLING_GRAPH_RAG_AGENT":
                yield "## Calling GraphRAGAgent..."
                yield "## Calling RequestDecompositionAgent..."
                request_decomposition_agent_response = await self.agents[
                    "RequestDecompositionAgent"
                ].handle_task(
                    user_request=chat_agent_response["payload"]["request"],
                    validated_entities=chat_agent_response["payload"][
                        "validated_entities"
                    ],
                )
                yield get_formatted_decomposed_request(
                    request_decomposition_agent_response
                )

                # Process the decomposed subrequests concurrently
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
                final_response = None
                async for result in self._fan_in_generators(gens):
                    yield result
                    if isinstance(result, str) and result.startswith(
                        "## Combined Final Response from QueryAgents"
                    ):
                        final_response = result

                # Generate final result
                yield "## Calling ChatAgent to process combined final response..."
                chat_agent_response = await self.agents["ChatAgent"].handle_task(
                    chat_input=final_response,
                    similarity_threshold=similarity_threshold,
                    previous_chat_id=self.current_chat_id,
                )
                tool_call += 1

            elif chat_agent_response["type"] == "CALLING_VECTOR_RAG_AGENT":
                yield "## Calling VectorRAGAgent..."
                request = chat_agent_response["payload"]["request"]
                rag_agent_response = await self.agents["VectorRAGAgent"].handle_task(
                    user_query=request,
                    top_k=top_k_for_similarity,
                )

                retrieved_result = rag_agent_response["payload"]["answer"]

                yield f"**Retrieved result by the VectorRAGAgent:**\n{retrieved_result}"
                yield "## Calling ChatAgent to process combined final response..."
                chat_agent_response = await self.agents["ChatAgent"].handle_task(
                    chat_input=retrieved_result,
                    similarity_threshold=similarity_threshold,
                    previous_chat_id=self.current_chat_id,
                )
                tool_call += 1

            else:
                yield "**Unexpected error occured. Please contact the developer.**"
                break

    async def rag_query(
        self,
        user_request: str | list[str],
        top_k_for_similarity: int,
        similarity_threshold: float = 0.5,
    ):
        """
        for RAG testing purposes
        """
        # normalize to list and strip empties
        queries = user_request if isinstance(user_request, list) else [user_request]
        queries = [q.strip() for q in queries if isinstance(q, str) and q.strip()]

        # Call VectorRAGAgent (now single-query mode)
        yield "## Calling VectorRAGAgent..."

        multi = len(queries) > 1

        # run sequentially with minimal changes
        for q in queries:
            try:
                rag_agent_response = await self.agents["VectorRAGAgent"].handle_task(
                    user_query=q,
                    top_k=top_k_for_similarity,
                )
                answer = (rag_agent_response.get("payload") or {}).get("answer") or ""
            except Exception as e:
                answer = f"Failed to generate an answer. Error: {e}"

            yield f"### {q}\n{answer}" if multi else answer

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
        graph_retrieval_logger.debug(
            f"Checking the final response: \n{final_response_str}"
        )

        if final_responses:
            combined = "\n\n".join(final_responses)
            yield "## Combined Final Response from QueryAgents" + "\n" + combined

    async def _process_subrequest(
        self,
        agent_name: str,
        sub_request: str,
        validated_entities: list[str],
        ontology: dict,
        max_iteration: int = 3,
    ) -> AsyncGenerator[str, None]:
        """
        Handles a sub-request by coordinating between QueryAgent and Text2CypherAgent.
        Iteratively generates queries, translates them to Cypher, executes them,
        and refines results until a final response is produced or the iteration limit is reached.
        """
        # Track response IDs for iterative refinement
        query_agent_response = None
        text2cypher_agent_response = None
        previous_query_agent_response_id = None
        previous_text2_cypher_agent_response_id = None

        # Step 1: Initial query generation
        yield f"## Calling Query Agent ({agent_name}) for sub-request'{sub_request}'..."
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

        # Check if the initial call failed to produce a query
        if query_agent_response["type"] != "QUERY":
            yield f"**{agent_name}:** Failed to generate initial query. Aborting."
            return

        yield (
            f"**{agent_name}**:\n"
            f"**Query:** {query_agent_response['payload']['query']}\n"
            f"**Validated Entities:** {query_agent_response['payload']['validated_entities']}\n"
            f"**Note:** {query_agent_response['payload']['note'] or 'NA'}"
        )

        # Step 2: Iterative Refinement Loop
        for current_iteration in range(max_iteration):

            # Step 2.1: Convert Natural Language Query to Cypher
            yield f"## Calling Text2Cypher Agent for {agent_name} (Iteration {current_iteration + 1}/{max_iteration})..."
            text2cypher_agent_response = await self.agents[
                "Text2CypherAgent"
            ].handle_task(
                user_query=query_agent_response["payload"]["query"],
                validated_entities=query_agent_response["payload"][
                    "validated_entities"
                ],
                ontology=ontology,
                note=query_agent_response["payload"]["note"],
                previous_response_id=previous_text2_cypher_agent_response_id,
            )
            previous_text2_cypher_agent_response_id = text2cypher_agent_response["id"]

            # Step 2.2: Execute the Cypher query
            formatted_cypher = get_formatted_cypher(
                query=text2cypher_agent_response["cypher_query"],
                params=text2cypher_agent_response["parameters"],
            )
            yield f"**Executing the generated Cypher query:**\n{formatted_cypher}"
            cypher_retrieval_result = await self.graph_storage.run_query(
                query=text2cypher_agent_response["cypher_query"],
                parameters=text2cypher_agent_response["parameters"],
            )
            stringified_cypher_retrieval_result = (
                get_stringified_cypher_retrieval_result(cypher_retrieval_result)
            )
            graph_retrieval_logger.debug(stringified_cypher_retrieval_result)

            # Step 2.3: Compile the Cypher retrieval result
            yield "**Compiling the Cypher retrieval result...**"
            result = await self.agents["RetrievalResultCompilationAgent"].handle_task(
                formatted_cypher_query=formatted_cypher,
                formatted_retrieval_result=stringified_cypher_retrieval_result,
            )
            formatted_retrieval_result = result["compiled_result"]

            yield (
                f"**Response by Text2CypherAgent to {agent_name}:**\n"
                f"**Cypher Query:** {formatted_cypher}\n"
                f"**Note:** {text2cypher_agent_response['note']}\n"
                f"**Retrieval Result:**\n{formatted_retrieval_result}"
            )

            # Step 2.4: Evaluate the retrieval result
            is_last_iteration = current_iteration == max_iteration - 1

            if is_last_iteration:
                yield f"**Max iteration reached for {agent_name}, forcing final report generation...**"
            else:
                yield f"## Calling Query Agent ({agent_name}) to evaluate retrieval result..."

            query_agent_response = await self.agents["QueryAgent"].handle_task(
                user_request=get_formatted_input_for_query_agent(
                    type=(
                        "REPORT_GENERATION"
                        if is_last_iteration
                        else "RETRIEVAL_RESULT_EVALUATION"
                    ),
                    payload={
                        "retrieval_result": formatted_retrieval_result,
                        "cypher_query": formatted_cypher,
                        "note": text2cypher_agent_response["note"],
                    },
                ),
                ontology=ontology,
                previous_response_id=previous_query_agent_response_id,
            )
            previous_query_agent_response_id = query_agent_response["id"]

            # Step 2.5: Decide continue or break
            if query_agent_response["type"] == "QUERY":
                yield (
                    f"**{agent_name} (Refining Query)**:\n"
                    f"**New Query:** {query_agent_response['payload']['query']}\n"
                    f"**Validated Entities:** {query_agent_response['payload']['validated_entities']}\n"
                    f"**Note:** {query_agent_response['payload']['note'] or 'NA'}"
                )

            elif query_agent_response["type"] == "FINAL_RESPONSE":
                yield (
                    f"**{agent_name}**:\n"
                    f"**Final Response:** {query_agent_response['payload']['response']}\n"
                    f"**Note:** {query_agent_response['payload']['note'] or 'NA'}"
                )
                return

            else:
                yield f"**{agent_name}:** Unexpected occurred from QueryAgent. Aborting."
                return
