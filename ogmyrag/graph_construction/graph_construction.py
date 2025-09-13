from __future__ import annotations

import logging
import asyncio
import json
from datetime import timedelta
from bson import ObjectId
from pymongo import ASCENDING, DESCENDING
from motor.motor_asyncio import AsyncIOMotorClient
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
from ..base import BaseLLMClient
from ..prompts import PROMPT
from ..util import (
    get_formatted_ontology,
    get_formatted_openai_response,
    get_formatted_entities_and_relationships,
    get_formatted_current_datetime,
    get_formatted_similar_entities,
    get_sliced_ontology,
    get_clean_json,
    get_current_datetime,
)
from ..storage import (
    AsyncMongoDBStorage,
    PineconeStorage,
    AsyncNeo4jStorage,
    DatabaseError,
    AsyncCollectionHandler,
)

from ..base import (
    BaseAgent,
    BaseMultiAgentSystem,
    MongoStorageConfig,
    PineconeStorageConfig,
    Neo4jStorageConfig,
)

from .graph_construction_util import (
    get_entities_relationships_with_updated_ids,
    get_formatted_entity_for_vectordb,
    get_formatted_entity_for_graphdb,
    get_formatted_relationship_for_graphdb,
    get_formatted_entity_details_for_deduplication,
    get_formatted_entities_deduplication_pending_task,
    get_formatted_entity_cache_for_db,
    get_formatted_relationship_cache_for_db,
    get_formatted_entities_and_relationships_for_db,
)

graph_construction_logger = logging.getLogger("graph_construction")


class EntityRelationshipExtractionAgent(BaseAgent):
    """
    An agent responsible for extracting entities and relationships from document given.
    """

    def __init__(self, agent_name: str, agent_config: dict):
        super().__init__(agent_name=agent_name, agent_config=agent_config)

    async def handle_task(self, **kwargs) -> str:
        """
        Parameters:
           ontology (dict): The ontology.
           source_text (str): The source text to be parsed.
           source_text_publish_date (str): The date when the source text was published.
           source_text_constraints (str): The constraints to adhere while parsing the source text.
        """
        graph_construction_logger.info(f"EntityRelatonshipExtractionAgent is called")

        formatted_ontology = get_formatted_ontology(
            data=kwargs.get("ontology", {}) or {},
        )
        graph_construction_logger.debug(
            f"EntityRelatonshipExtractionAgent\nOntology used:\n{formatted_ontology}"
        )

        system_prompt = PROMPT["ENTITIES_RELATIONSHIPS_PARSING"].format(
            ontology=formatted_ontology,
            publish_date=kwargs.get("source_text_publish_date", "NA") or "NA",
        )
        graph_construction_logger.debug(
            f"EntityRelatonshipExtractionAgent\System prompt used:\n{system_prompt}"
        )

        constraints_prefix = (
            "The following key-value pairs aid in interpreting the source text. "
            "Apply these mappings when extracting and storing entities and relationships "
            "to maintain consistency and accuracy. This means that if your extraction "
            "involves translating a key into its representative value—for example, if the "
            "key is `CYT` and the value is `Choo Yan Tiee, the Promoter, Specified "
            "Shareholder, major shareholder, Executive Director and Managing Director of "
            "our Company`—then instead of extracting `CYT` as the entity name, you should "
            "extract `Choo Yan Tiee` as the entity name.\n"
        )
        constraints_body = (
            kwargs.get("source_text_constraints") or "Constraints not available."
        )
        constraints = constraints_prefix + constraints_body
        source_text = kwargs.get("source_text") or "NA"
        user_prompt = constraints + source_text
        graph_construction_logger.debug(f"User prompt used:\n{user_prompt}")

        graph_construction_logger.debug(
            f"EntityRelationshipExtractionAgent\nAgent configuration used:\n{str(self.agent_config)}"
        )

        response = await self.agent_system.llm_client.fetch_response(
            system_prompt=system_prompt, user_prompt=user_prompt, **self.agent_config
        )
        graph_construction_logger.info(
            f"EntityRelatonshipExtractionAgent\nEntity-relationship extraction response details:\n{get_formatted_openai_response(response)}"
        )

        return response.output_text


class EntityDeduplicationAgent(BaseAgent):
    """
    An agent responsible for deduplicating extracted entities.
    """

    def __init__(self, agent_name: str, agent_config: dict):
        super().__init__(agent_name=agent_name, agent_config=agent_config)

    async def handle_task(self, **kwargs) -> str:
        """
        Parameters:
           entities_to_compare (str)
        """
        graph_construction_logger.info(f"EntityDeduplicationAgent is called")

        system_prompt = PROMPT["ENTITY_DEDUPLICATION"]
        graph_construction_logger.debug(
            f"EntityDeduplicationAgent\System prompt used:\n{system_prompt}"
        )

        user_prompt = kwargs.get("entities_to_compare") or ""
        graph_construction_logger.debug(f"User prompt used:\n{user_prompt}")

        graph_construction_logger.debug(
            f"EntityDeduplicationAgent\nAgent configuration used:\n{str(self.agent_config)}"
        )

        response = await self.agent_system.llm_client.fetch_response(
            system_prompt=system_prompt, user_prompt=user_prompt, **self.agent_config
        )
        graph_construction_logger.info(
            f"EntityDeduplicationAgent\nEntity deduplication response details:\n{get_formatted_openai_response(response)}"
        )

        return response.output_text


class RelationshipDeduplicationAgent(BaseAgent):
    """
    An agent responsible for deduplicating extracted relationships.
    Works by merging the descriptions of both relationships
    """

    def __init__(self, agent_name: str, agent_config: dict):
        super().__init__(agent_name=agent_name, agent_config=agent_config)

    async def handle_task(self, **kwargs) -> str:
        """
        Parameters:
           relationship_description (list(str))
        """
        graph_construction_logger.info(f"RelationshipDeduplicationAgent is called")

        system_prompt = PROMPT["RELATIONSHIP_DEDUPLICATION"]
        graph_construction_logger.debug(
            f"RelationshipDeduplicationAgent\nSystem prompt used:\n{system_prompt}"
        )

        user_prompt_list = kwargs.get("relationship_description") or []
        user_prompt = "\n".join(user_prompt_list)
        graph_construction_logger.debug(
            f"RelationshipDeduplicationAgent\nUser prompt used:\n{user_prompt}"
        )

        graph_construction_logger.debug(
            f"RelationshipDeduplicationAgent\nAgent configuration used:\n{str(self.agent_config)}"
        )

        response = await self.agent_system.llm_client.fetch_response(
            system_prompt=system_prompt, user_prompt=user_prompt, **self.agent_config
        )
        graph_construction_logger.info(
            f"RelationshipDeduplicationAgent\nRelationship deduplication response details:\n{get_formatted_openai_response(response)}"
        )

        return response.output_text


class GraphConstructionSystem(BaseMultiAgentSystem):
    def __init__(
        self,
        async_mongo_client: AsyncIOMotorClient,
        async_mongo_client_reports: AsyncIOMotorClient,
        ontology_config: MongoStorageConfig,
        disclosure_config: MongoStorageConfig,
        constraints_config: MongoStorageConfig,
        entity_config: MongoStorageConfig,
        relationship_config: MongoStorageConfig,
        entity_cache_config: MongoStorageConfig,
        relationship_cache_config: MongoStorageConfig,
        entities_deduplication_pending_tasks_config: MongoStorageConfig,
        entity_vector_config: PineconeStorageConfig,
        entity_cache_vector_config: PineconeStorageConfig,
        graphdb_config: Neo4jStorageConfig,
        llm_client: BaseLLMClient,
        agent_configs: dict[str, dict],
    ):
        super().__init__(
            {
                "EntityRelationshipExtractionAgent": EntityRelationshipExtractionAgent(
                    agent_name="EntityRelationshipExtractionAgent",
                    agent_config=agent_configs["EntityRelationshipExtractionAgent"],
                ),
                "EntityDeduplicationAgent": EntityDeduplicationAgent(
                    agent_name="EntityDeduplicationAgent",
                    agent_config=agent_configs["EntityDeduplicationAgent"],
                ),
                "RelationshipDeduplicationAgent": RelationshipDeduplicationAgent(
                    agent_name="RelationshipDeduplicationAgent",
                    agent_config=agent_configs["RelationshipDeduplicationAgent"],
                ),
            }
        )

        try:
            self.ontology_config = ontology_config
            self.disclosure_config = disclosure_config
            self.constraints_config = constraints_config
            self.entity_config = entity_config
            self.relationship_config = relationship_config
            self.entity_cache_config = entity_cache_config
            self.relationship_cache_config = relationship_cache_config
            self.entity_vector_config = entity_vector_config
            self.entity_cache_vector_config = entity_cache_vector_config
            self.entities_deduplication_pending_tasks_config = (
                entities_deduplication_pending_tasks_config
            )
            self.async_mongo_storage = AsyncMongoDBStorage(async_mongo_client)
            self.async_mongo_storage_reports = AsyncMongoDBStorage(
                async_mongo_client_reports
            )

            # Both indices use the same OpenAI API Key and PineconeAPI Key at the current momment
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
            self.pinecone_storage.create_index_if_not_exists(
                index_name=entity_cache_vector_config["index_name"],
                dimension=entity_cache_vector_config["pinecone_dimensions"],
                metric=entity_cache_vector_config["pinecone_metric"],
                cloud=entity_cache_vector_config["pinecone_cloud"],
                region=entity_cache_vector_config["pinecone_environment"],
            )

            self.graph_storage = AsyncNeo4jStorage(**graphdb_config)

            self.llm_client = llm_client

        except Exception as e:
            graph_construction_logger.error(f"GraphConstructionSystem: {e}")
            raise RuntimeError(f"Failed to intialize GraphConstructionSystem: {e}")

    async def extract_entities_relationships_from_unparsed_documents(
        self,
        from_company: str,
        document_type: str,
        published_at: str,
        exclude_documents: list[str],
        num_of_relationships_per_onto: int = 10,
        concurrency_limit: int = 20,
    ) -> None:
        """
        Process unparsed disclosure documents concurrently with controlled parallelism
        and guaranteed atomicity per document.
        """
        # Step 1 : Gather the ontology, constraints, and documents.
        latest_onto = await self._get_latest_ontology()
        graph_construction_logger.info(
            f"GraphConstructionSystem\Ontology fetched:\n{get_formatted_ontology(latest_onto)}"
        )
        constraints = await self._get_parsing_constraints(
            from_company=from_company, published_at=published_at
        )
        graph_construction_logger.info(
            f"GraphConstructionSystem\nConstraints fetched:\n{constraints}"
        )

        unparsed_documents = await self._get_unparsed_documents(
            from_company=from_company,
            published_at=published_at,
            document_type=document_type,
            exclude_documents=exclude_documents,
        )
        if not unparsed_documents:
            graph_construction_logger.info(
                "GraphConstructionSystem\nNo unparsed documents found."
            )
            return

        documents_to_parse = "\n".join(
            f"{index}. {document.get('name')}"
            for index, document in enumerate(unparsed_documents, start=1)
        )
        graph_construction_logger.info(
            f"GraphConstructionSystem\nDocuments to parse:\n{documents_to_parse}"
        )

        # Step 2 : Create a single task for each document that handles the full E-T-L pipeline.
        semaphore = asyncio.Semaphore(concurrency_limit)
        processing_tasks = [
            self._process_single_document_pipeline(
                document=doc,
                ontology=latest_onto,
                constraints=constraints,
                from_company=from_company,
                num_of_relationships_per_onto=num_of_relationships_per_onto,
                semaphore=semaphore,
            )
            for doc in unparsed_documents
        ]
        await asyncio.gather(*processing_tasks)

        graph_construction_logger.info(
            f"Successfully completed processing batch of {len(unparsed_documents)} documents."
        )

    async def _process_single_document_pipeline(
        self,
        document: dict,
        ontology: dict,
        constraints: str,
        from_company: str,
        semaphore: asyncio.Semaphore,
        num_of_relationships_per_onto: int = 10,
    ):
        """
        A single, atomic pipeline for one document: Extract -> Insert -> Update Status.
        """
        async with semaphore:
            try:
                # Step 1 : Extraction (LLM call)
                graph_construction_logger.info(
                    f"Pipeline started for document: {document.get('name')}"
                )
                extracted_data = await self._get_extracted_entities_and_relationships(
                    ontology=ontology,
                    source_text_details=document,
                    source_text_constraints=constraints,
                    num_of_relationships_per_onto=num_of_relationships_per_onto,
                )

                # Step 2 : Insertion and Status Update (DB transaction)
                await self._insert_entities_and_relationships_into_db(
                    data=extracted_data, from_company=from_company
                )

            except Exception as e:
                graph_construction_logger.error(
                    f"Pipeline for document {document.get('name')} (ID: {document.get('id')}) failed. Error: {e}",
                    exc_info=True,
                )
                raise

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

    async def _get_parsing_constraints(self, from_company: str, published_at: str):
        try:
            raw_constraints = (
                await self.async_mongo_storage_reports.get_database(
                    self.constraints_config["database_name"]
                )
                .get_collection(self.constraints_config["collection_name"])
                .read_documents(
                    {
                        "from_company": from_company,
                        "type": "CONSTRAINTS",
                        "published_at": published_at,
                    }
                )
            )
        except Exception as e:
            raise LookupError("Failed to fetch related constraints") from e
        return "\n".join(doc.get("content", "") for doc in raw_constraints)

    async def _get_unparsed_documents(
        self,
        from_company: str,
        published_at: str,
        document_type: str,
        exclude_documents: list[str],
    ) -> list[dict]:
        try:
            raw_documents = (
                await self.async_mongo_storage_reports.get_database(
                    self.disclosure_config["database_name"]
                )
                .get_collection(self.disclosure_config["collection_name"])
                .read_documents(
                    {
                        "from_company": from_company,
                        "type": document_type,
                        "published_at": published_at,
                        "is_parsed": False,
                    }
                )
            )
        except Exception as e:
            raise LookupError(f"Failed to fetch unparsed documents") from e
        return [
            {
                "id": doc.get("_id"),
                "name": doc.get("name", ""),
                "published_at": doc.get("published_at", ""),
                "content": doc.get("content", ""),
            }
            for doc in raw_documents
            if doc.get("name", "") not in exclude_documents
        ]

    async def _get_extracted_entities_and_relationships(
        self,
        ontology: dict,
        source_text_details: dict,
        source_text_constraints: str,
        num_of_relationships_per_onto: int,
    ) -> dict:
        all_tasks = []
        num_of_relationships = len(ontology["relationships"])

        for i in range(0, num_of_relationships, num_of_relationships_per_onto):
            sliced_ontology = get_sliced_ontology(
                ontology=ontology,
                i=i,
                k=min(i + num_of_relationships_per_onto, num_of_relationships),
            )
            task = self.agents["EntityRelationshipExtractionAgent"].handle_task(
                ontology=sliced_ontology,
                source_text=source_text_details.get("content"),
                source_text_publish_date=source_text_details.get("published_at"),
                source_text_constraints=source_text_constraints,
            )
            all_tasks.append(task)

        graph_construction_logger.info(
            f"GraphConstructionSystem\n{len(all_tasks)} coroutines are created to extract entities and relationships for {source_text_details.get('name')}"
        )

        try:
            extraction_results = await asyncio.gather(*all_tasks)

            combined_extraction_results = {
                "document_id": source_text_details.get("id"),
                "document_name": source_text_details.get("name"),
                "entities": [],
                "relationships": [],
            }

            for result in extraction_results:
                # Assign actual IDs (ObjectID) to the entities and relationships to ensure uniquess
                processed_result = get_entities_relationships_with_updated_ids(
                    get_clean_json(result)
                )

                combined_extraction_results["entities"].extend(
                    processed_result["entities"]
                )
                combined_extraction_results["relationships"].extend(
                    processed_result["relationships"]
                )

            graph_construction_logger.info(
                f"EntityRelatonshipExtractionAgent\nEntities and relationships extracted for {source_text_details.get('name')}:\n{get_formatted_entities_and_relationships(combined_extraction_results)}"
            )
            return combined_extraction_results
        except Exception as e:
            graph_construction_logger.info(
                f"EntityRelatonshipExtractionAgent\nError occurs during extracting entities and relationships for {source_text_details.get('name')}"
            )
            raise RuntimeError("Failed to extract entities and relationships") from e

    async def _insert_entities_and_relationships_into_db(
        self, data: dict, from_company: str
    ) -> None:
        graph_construction_logger.info(
            "GraphConstructionSystem\nInserting entities and relationships into MongoDB..."
        )

        formatted_entities, formatted_relationships = (
            get_formatted_entities_and_relationships_for_db(
                data=data, from_company=from_company
            )
        )
        if formatted_entities and formatted_relationships:
            async with self.async_mongo_storage.with_transaction() as session:
                # Step 1: Insert entities
                inserted_entity_ids = (
                    await self.async_mongo_storage.get_database(
                        self.entity_config["database_name"]
                    )
                    .get_collection(self.entity_config["collection_name"])
                    .create_documents(data=formatted_entities, session=session)
                )

                # Step 2: Insert relationships
                inserted_relationship_ids = (
                    await self.async_mongo_storage.get_database(
                        self.relationship_config["database_name"]
                    )
                    .get_collection(self.relationship_config["collection_name"])
                    .create_documents(data=formatted_relationships, session=session)
                )

                graph_construction_logger.info(
                    f"GraphConstructionSystem\nSuccessfully inserted {len(inserted_entity_ids)} entity(ies) and {len(inserted_relationship_ids)} relationship(s) into MongoDB."
                )

            # Step 3: Update the company disclosure as processed
            # Since the reports are currently stored in different locations. This operation cannot be placed into a single transaction
            await self.async_mongo_storage_reports.get_database(
                self.disclosure_config["database_name"]
            ).get_collection(self.disclosure_config["collection_name"]).update_document(
                query={"_id": data["document_id"]},
                update_data={"is_parsed": True},
            )

            graph_construction_logger.info(
                f"GraphConstructionSystem\nSuccessfully updated the 'is_parsed' status of {data['document_name']}."
            )

    async def deduplicate_entities(
        self,
        from_company: str,
        num_of_entities_per_batch: int,
        max_cache_size: int,
        similarity_threshold: float,
        num_of_relationships_to_fetch: int = 5,
        max_wait_time_per_task: int = 5,
    ):
        while True:
            # Step 1 : Update the cache size
            await self._update_entities_cache_size(
                max_cache_size=max_cache_size,
                num_of_entities_per_batch=num_of_entities_per_batch,
                from_company=from_company,
            )

            # Step 2 : Resolve any pending tasks created by the batch (upserting entities into and deleting from Pinecone)
            await self.resolve_entities_deduplication_pending_tasks(
                from_company=from_company,
            )

            # Step 3 : Fetch unparsed entities
            entities_to_deduplicate = await self._get_entities_to_deduplicate(
                from_company=from_company,
                num_of_entities_to_fetch=num_of_entities_per_batch,
            )

            # Step 4 : Check the exit condition for the loop
            if not entities_to_deduplicate:
                graph_construction_logger.info(
                    "GraphConstructionSystem\nNo more entities to deduplicate. Exiting process."
                )
                break

            graph_construction_logger.debug(
                f"GraphConstructionSystem\nEntities to deduplicate:\n{json.dumps(entities_to_deduplicate,indent=4,default=str)}"
            )

            # Step 5 : Deduplicate entities concurrently
            deduplication_tasks = [
                self._deduplicate_entity(
                    entity=entity,
                    from_company=from_company,
                    similarity_threshold=similarity_threshold,
                    num_of_relationships_to_fetch=num_of_relationships_to_fetch,
                    max_wait_time_minutes=max_wait_time_per_task,
                )
                for entity in entities_to_deduplicate
            ]

            results = await asyncio.gather(*deduplication_tasks, return_exceptions=True)

            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    entity_id = str(entities_to_deduplicate[i].get("_id"))
                    graph_construction_logger.error(
                        f"GraphConstructionSystem\nDeduplication for entity {entity_id} failed in batch: {result}"
                    )

        graph_construction_logger.info(
            f"GraphConstructionSystem\nContinuous entities deduplication process for company {from_company} has completed."
        )

    @retry(
        retry=retry_if_exception_type(DatabaseError),
        stop=stop_after_attempt(10),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def _deduplicate_entity(
        self,
        entity: dict,
        from_company: str,
        similarity_threshold: float,
        num_of_relationships_to_fetch: int,
        max_wait_time_minutes: int,
    ):
        """
        Finds and deduplicates a single entity. It first queries for a pool of
        potential candidates from the vector store, selects the best one that meets
        the similarity threshold, and then proceeds with the merge/insert logic.
        """
        CANDIDATE_POOL_SIZE = 10

        # Step 1 : Find a candidate in cache storage
        query_results = await self.pinecone_storage.get_index(
            self.entity_cache_vector_config["index_name"]
        ).get_similar_results(
            query_texts=entity.get("name", ""),
            top_k=CANDIDATE_POOL_SIZE,
            query_filter={"type": {"$eq": entity.get("type", "")}},
            score_threshold=similarity_threshold,
            namespace=from_company,
        )

        matches = query_results[0].get("matches", []) if query_results else []

        graph_construction_logger.debug(
            f"GraphConstructionSystem\nSimilar results fetched in deduplicate_entity() for {entity.get('name')}: {query_results}"
        )

        if matches:
            # Step 2a : If there is a matching candidate entity, attempt to acquire its write lock
            # Response is from Pinecone, thereby it is 'id' not '_id'

            best_candidate = matches[0]

            graph_construction_logger.info(
                f"Best candidate name: '{best_candidate.get('name')}'. "
                f"Best candidate id: {best_candidate.get('id')}, "
                f"Similarity score: {best_candidate.get('score', 0.0):.4f}"
            )

            candidate_entity_id = best_candidate["id"]
            lock_acquired = False
            wait_time = timedelta(minutes=max_wait_time_minutes)
            poll_interval_seconds = 10
            start_time = get_current_datetime()

            try:
                while (get_current_datetime() - start_time) < wait_time:
                    graph_construction_logger.info(
                        f"GraphConstructionSystem\nAttempting to lock candidate entity: {candidate_entity_id}"
                    )
                    # Atomic operation to acquire the lock
                    lock_result = (
                        await self.async_mongo_storage.get_database(
                            self.entity_cache_config["database_name"]
                        )
                        .get_collection(from_company)
                        .update_document(
                            query={
                                "_id": ObjectId(candidate_entity_id),
                                "lock_status": {"$ne": "LOCKED"},
                            },
                            update_data={
                                "lock_status": "LOCKED",
                                "lock_timestamp": get_current_datetime(),
                            },
                        )
                    )

                    if lock_result == 1:
                        lock_acquired = True
                        graph_construction_logger.info(
                            f"GraphConstructionSystem\nSuccessfully acquired lock on candidate: {candidate_entity_id}"
                        )
                        break
                    else:
                        graph_construction_logger.info(
                            f"GraphConstructionSystem\nCandidate {candidate_entity_id} is locked. Waiting for {poll_interval_seconds} seconds..."
                        )
                        await asyncio.sleep(poll_interval_seconds)

                # Step 3a : Check if the write lock is acquired
                if not lock_acquired:
                    graph_construction_logger.error(
                        f"GraphConstructionSystem\nFailed to acquire lock on {candidate_entity_id} within the timeout period. Aborting merge."
                    )
                    raise asyncio.TimeoutError(
                        f"GraphConstructionSystem\nTimed out waiting for lock on entity {candidate_entity_id}"
                    )

                # Step 4a : Fetch the full candidate entity details after locking
                candidate_entity = (
                    await self.async_mongo_storage.get_database(
                        self.entity_cache_config["database_name"]
                    )
                    .get_collection(from_company)
                    .read_documents(query={"_id": ObjectId(candidate_entity_id)})
                )[0]

                # Step 5a : Prepare entities details for LLM comparison
                candidate_entity_details = (
                    await self.get_formatted_entity_with_relationships(
                        entity=candidate_entity,
                        entity_label="Candidate Entity",
                        from_company=from_company,
                        num_of_relationships_to_fetch=num_of_relationships_to_fetch,
                    )
                )
                primary_entity_details = (
                    await self.get_formatted_entity_with_relationships(
                        entity=entity,
                        entity_label="Primary Entity",
                        from_company=from_company,
                        num_of_relationships_to_fetch=num_of_relationships_to_fetch,
                    )
                )
                entities_to_compare = (
                    f"{primary_entity_details}\n\n{candidate_entity_details}"
                )

                # Step 6a : Call the EntityDeduplicationagent
                deduplication_raw_response = await self.agents[
                    "EntityDeduplicationAgent"
                ].handle_task(
                    entities_to_compare=entities_to_compare,
                )
                deduplication_formatted_response = get_clean_json(
                    deduplication_raw_response
                )
                llm_merging_decision = deduplication_formatted_response["decision"]

                # Step 7a : Execute the merging decision
                if llm_merging_decision == "MERGE":
                    await self._merge_entity(
                        primary_entity=entity,
                        candidate_entity=candidate_entity,
                        new_descriptions=deduplication_formatted_response[
                            "new_description"
                        ],
                        from_company=from_company,
                    )

                    graph_construction_logger.debug(
                        f"GraphConstructionSystem\nSuccessfully merge primary_entity with id: {str(entity['_id'])} into candidate_entity with id: {str(candidate_entity['_id'])}"
                    )

                else:
                    await self._insert_entity_into_cache(
                        entity=entity, from_company=from_company
                    )
                    graph_construction_logger.debug(
                        f"GraphConstructionSystem\nSuccessfully inserted entity with id: {str(entity['_id'])}"
                    )
            except Exception as e:
                graph_construction_logger.error(
                    f"GraphConstructionSystem\nAn error occurred during deduplication for entity {candidate_entity_id}: {e}",
                    exc_info=True,
                )
                raise
            finally:
                # Step 8a : Release the lock regardless of writing is performed
                if lock_acquired:
                    graph_construction_logger.info(
                        f"GraphConstructionSystem\nReleasing lock on candidate entity: {candidate_entity_id}"
                    )
                    await self.async_mongo_storage.get_database(
                        self.entity_cache_config["database_name"]
                    ).get_collection(from_company).update_document(
                        query={"_id": ObjectId(candidate_entity_id)},
                        update_data={
                            "$unset": {"lock_status": "", "lock_timestamp": ""}
                        },
                    )
        else:
            # Step 2b : If there is no matching candidate entity, insert the entity

            await self._insert_entity_into_cache(
                entity=entity, from_company=from_company
            )
            graph_construction_logger.debug(
                f"GraphConstructionSystem\nSuccessfully inserted entity with id: {str(entity['_id'])} into entities cache"
            )

    async def _update_entities_cache_size(
        self, max_cache_size: int, num_of_entities_per_batch: int, from_company: str
    ):
        """
        Checks the entity cache size and evicts the oldest items if the cache is nearing its capacity.
        This is a proactive eviction to make space for an incoming batch.
        """
        # DRY: Get collection objects once to improve readability
        entity_cache_collection = self.async_mongo_storage.get_database(
            self.entity_cache_config["database_name"]
        ).get_collection(from_company)

        pending_tasks_collection = self.async_mongo_storage.get_database(
            self.entities_deduplication_pending_tasks_config["database_name"]
        ).get_collection(
            self.entities_deduplication_pending_tasks_config["collection_name"]
        )

        current_cache_size = await entity_cache_collection.get_doc_counts()

        # Proactively make space if the cache is close to full
        if current_cache_size >= (max_cache_size - num_of_entities_per_batch):
            num_of_cache_to_remove = current_cache_size - (
                max_cache_size - num_of_entities_per_batch
            )
            if num_of_cache_to_remove <= 0:
                return

            graph_construction_logger.info(
                f"Cache size ({current_cache_size}) is nearing limit ({max_cache_size}). "
                f"Evicting {num_of_cache_to_remove} oldest items from '{from_company}'."
            )

            try:
                async with self.async_mongo_storage.with_transaction() as session:
                    # Step 1 : Get the oldest entities to remove
                    oldest_items = await entity_cache_collection.read_documents(
                        query={},
                        sort=[("last_modified_at", ASCENDING)],
                        limit=num_of_cache_to_remove,
                        session=session,
                    )

                    if not oldest_items:
                        return

                    ids_to_delete = [item["_id"] for item in oldest_items]

                    # Step 2 : Delete the entities from the MongoDB cache in a single batch
                    delete_result = await entity_cache_collection.delete_documents(
                        query={"_id": {"$in": ids_to_delete}}, session=session
                    )

                    # Step 3 : Prepare the pending "DELETE" tasks for the vector cache
                    pending_delete_tasks = [
                        get_formatted_entities_deduplication_pending_task(
                            from_company=from_company,
                            task_type="DELETE",
                            payload={"_id": entity_id},
                        )
                        for entity_id in ids_to_delete
                    ]

                    # Step 4 : Create all pending tasks in a single batch operation
                    if pending_delete_tasks:
                        await pending_tasks_collection.create_documents(
                            data=pending_delete_tasks, session=session
                        )

                    graph_construction_logger.info(
                        f"Successfully evicted {delete_result.deleted_count} entities from MongoDB cache "
                        f"and created {len(pending_delete_tasks)} pending delete tasks."
                    )
            except Exception as e:
                graph_construction_logger.error(f"Failed during cache eviction: {e}")
                raise

    async def _get_entities_to_deduplicate(
        self, from_company: str, num_of_entities_to_fetch: int
    ) -> list[dict]:
        return await (
            self.async_mongo_storage.get_database(self.entity_config["database_name"])
            .get_collection(self.entity_config["collection_name"])
            .read_documents(
                query={
                    "status": "TO_BE_DEDUPLICATED",
                    "originated_from": {"$in": [from_company]},
                },
                limit=num_of_entities_to_fetch,
            )
        )

    async def get_formatted_entity_with_relationships(
        self,
        entity: dict,
        entity_label: str,
        from_company: str,
        num_of_relationships_to_fetch: int = 5,
    ):
        associated_relationships = (
            await self.async_mongo_storage.get_database(
                self.relationship_config["database_name"]
            )
            .get_collection(self.relationship_config["collection_name"])
            .read_documents(
                query={
                    "status": "TO_BE_DEDUPLICATED",
                    "originated_from": {"$in": [from_company]},
                    "$or": [
                        {"source_id": entity["_id"]},
                        {"target_id": entity["_id"]},
                    ],
                },
                limit=num_of_relationships_to_fetch,
            )
        )
        return get_formatted_entity_details_for_deduplication(
            entity=entity,
            entity_label=entity_label,
            associated_relationships=associated_relationships,
        )

    async def _insert_entity_into_cache(self, entity: dict, from_company: str):
        async with self.async_mongo_storage.with_transaction() as session:
            # Step 1 : Insert the entity into mongodb cache storage
            await self.async_mongo_storage.get_database(
                self.entity_cache_config["database_name"]
            ).get_collection(from_company).create_document(
                data=get_formatted_entity_cache_for_db(entity=entity),
                session=session,
            )

            # Step 2 : Update the status of the inserted entity in permanent entities storage
            await self.async_mongo_storage.get_database(
                self.entity_config["database_name"]
            ).get_collection(self.entity_config["collection_name"]).update_document(
                query={"_id": entity["_id"]},
                update_data={
                    "status": "TO_BE_UPSERTED_INTO_VECTOR_DB",
                    "last_modified_at": get_current_datetime(),
                },
                session=session,
            )

            # Step 3 : Add a pending task to insert the entity into vector db
            await self.async_mongo_storage.get_database(
                self.entities_deduplication_pending_tasks_config["database_name"]
            ).get_collection(
                self.entities_deduplication_pending_tasks_config["collection_name"]
            ).create_document(
                data=get_formatted_entities_deduplication_pending_task(
                    from_company=from_company,
                    task_type="UPSERT",
                    payload={
                        "_id": entity["_id"],
                        "name": entity["name"],
                        "type": entity["type"],
                        "description": entity["description"],
                    },
                ),
                session=session,
            )

    async def _merge_entity(
        self,
        primary_entity: dict,
        candidate_entity: dict,
        new_descriptions: list[str],
        from_company: str,
    ):
        async with self.async_mongo_storage.with_transaction() as session:
            current_timestamp = get_current_datetime()

            # Step 1 : Update the candidate_entity with new description into mongodb cache storage
            await self.async_mongo_storage.get_database(
                self.entity_cache_config["database_name"]
            ).get_collection(from_company).update_document(
                query={"_id": candidate_entity["_id"]},
                update_data={
                    "description": new_descriptions,
                    "last_modified_at": current_timestamp,
                },
                session=session,
            )

            # Step 2 : Update the status of the candidate_entity in permanent entities storage
            await self.async_mongo_storage.get_database(
                self.entity_config["database_name"]
            ).get_collection(self.entity_config["collection_name"]).update_document(
                query={"_id": candidate_entity["_id"]},
                update_data={
                    "status": "TO_BE_UPSERTED_INTO_VECTOR_DB",
                    "description": new_descriptions,
                    "last_modified_at": current_timestamp,
                },
                session=session,
            )

            # Step 3 : Add a pending task to upsert candidate_entity into vector db
            await self.async_mongo_storage.get_database(
                self.entities_deduplication_pending_tasks_config["database_name"]
            ).get_collection(
                self.entities_deduplication_pending_tasks_config["collection_name"]
            ).create_document(
                data=get_formatted_entities_deduplication_pending_task(
                    from_company=from_company,
                    task_type="UPSERT",
                    payload={
                        "_id": candidate_entity["_id"],
                        "name": candidate_entity["name"],
                        "type": candidate_entity["type"],
                        "description": new_descriptions,
                    },
                ),
                session=session,
            )

            # Step 4 : Update the source_id/target_id of affected relationships due to the deletion of primary_entity
            update_result_outgoing = (
                await self.async_mongo_storage.get_database(
                    self.relationship_config["database_name"]
                )
                .get_collection(self.relationship_config["collection_name"])
                .update_documents(
                    query={"source_id": primary_entity["_id"]},
                    update={
                        "$set": {
                            "source_id": candidate_entity["_id"],
                            "last_modified_at": current_timestamp,
                        }
                    },
                    session=session,
                )
            )
            graph_construction_logger.info(
                f"Updated {update_result_outgoing.modified_count} outgoing relationships for entity with id: {str(primary_entity['_id'])}."
            )

            update_result_incoming = (
                await self.async_mongo_storage.get_database(
                    self.relationship_config["database_name"]
                )
                .get_collection(self.relationship_config["collection_name"])
                .update_documents(
                    query={"target_id": primary_entity["_id"]},
                    update={
                        "$set": {
                            "target_id": candidate_entity["_id"],
                            "last_modified_at": current_timestamp,
                        }
                    },
                    session=session,
                )
            )
            graph_construction_logger.info(
                f"Updated {update_result_incoming.modified_count} incoming relationships for entity with id: {str(primary_entity['_id'])}."
            )

            # Step 5 : Update the status of the primary_entity in permanent entities storage
            await self.async_mongo_storage.get_database(
                self.entity_config["database_name"]
            ).get_collection(self.entity_config["collection_name"]).update_document(
                query={"_id": primary_entity["_id"]},
                update_data={
                    "status": "TO_BE_DELETED",
                    "last_modified_at": current_timestamp,
                },
                session=session,
            )

    async def resolve_entities_deduplication_pending_tasks(self, from_company: str):
        """
        Processes pending upsert and delete tasks for the entity cache.
        This operation is designed to be idempotent and safe to retry.
        """
        pending_tasks_collection = self.async_mongo_storage.get_database(
            self.entities_deduplication_pending_tasks_config["database_name"]
        ).get_collection(
            self.entities_deduplication_pending_tasks_config["collection_name"]
        )

        # Step 1 : Fetch all pending tasks concurrently
        upsert_fetch_task = pending_tasks_collection.read_documents(
            query={"pending": True, "type": "UPSERT", "from_company": from_company}
        )
        delete_fetch_task = pending_tasks_collection.read_documents(
            query={"pending": True, "type": "DELETE", "from_company": from_company}
        )

        upsert_pending_tasks, deletion_pending_tasks = await asyncio.gather(
            upsert_fetch_task, delete_fetch_task
        )

        # Step 2 : Create and run processing tasks for upserts and deletes concurrently
        processing_tasks = []
        if upsert_pending_tasks:
            processing_tasks.append(
                self._process_upsert_tasks(
                    upsert_pending_tasks, from_company, pending_tasks_collection
                )
            )
        if deletion_pending_tasks:
            processing_tasks.append(
                self._process_delete_tasks(
                    deletion_pending_tasks, from_company, pending_tasks_collection
                )
            )
        if processing_tasks:
            await asyncio.gather(*processing_tasks)

    async def _process_upsert_tasks(
        self, tasks: list, from_company: str, collection: AsyncCollectionHandler
    ):
        graph_construction_logger.info(
            f"Processing {len(tasks)} pending upsert tasks..."
        )
        task_ids = [task["_id"] for task in tasks]

        try:
            formatted_entities_to_insert = [
                get_formatted_entity_for_vectordb(task["payload"]) for task in tasks
            ]

            # Step 1 : Perform the external operation (Pinecone)
            await self.pinecone_storage.get_index(
                self.entity_cache_vector_config["index_name"]
            ).upsert_vectors(items=formatted_entities_to_insert, namespace=from_company)

            # Step 2 : On success, update internal state in a SINGLE batch operation
            await collection.update_documents(
                query={"_id": {"$in": task_ids}}, update={"$set": {"pending": False}}
            )

            graph_construction_logger.info(
                f"Successfully upserted {len(tasks)} entities and completed tasks."
            )
        except Exception as e:
            graph_construction_logger.error(f"Failed to process upsert batch: {e}")
            raise

    async def _process_delete_tasks(
        self, tasks: list, from_company: str, collection: AsyncCollectionHandler
    ):
        graph_construction_logger.info(
            f"Processing {len(tasks)} pending deletion tasks..."
        )
        task_ids = [task["_id"] for task in tasks]

        try:
            entities_to_remove = [str(task["payload"]["_id"]) for task in tasks]

            # Step 1 : Perform the external operation (Pinecone)
            await self.pinecone_storage.get_index(
                self.entity_cache_vector_config["index_name"]
            ).delete_vectors(ids=entities_to_remove, namespace=from_company)

            # Step 2 : On success, update internal state in a SINGLE batch operation
            await collection.update_documents(
                {"_id": {"$in": task_ids}}, {"$set": {"pending": False}}
            )

            graph_construction_logger.info(
                f"Successfully deleted {len(tasks)} entities and completed tasks."
            )
        except Exception as e:
            graph_construction_logger.error(f"Failed to process delete batch: {e}")
            raise

    async def deduplicate_relationships(
        self,
        from_company: str,
        num_of_relationships_per_batch: int,
        max_cache_size: int,
        max_wait_time_per_task: int,
    ):
        while True:
            # Step 1 : Update relationships cache size
            await self._update_relationships_cache_size(
                max_cache_size=max_cache_size,
                num_of_relationships_per_batch=num_of_relationships_per_batch,
                from_company=from_company,
            )

            # Step 2 : Fetch unprocessed relationships
            relationships_to_deduplicate = await self._get_relationships_to_deduplicate(
                from_company=from_company,
                num_of_relationships_per_batch=num_of_relationships_per_batch,
            )

            # Step 3 : Check the exit condition for the loop
            if not relationships_to_deduplicate:
                graph_construction_logger.info(
                    "GraphConstructionSystem\nNo more relationsips to deduplicate. Exiting process."
                )
                break

            graph_construction_logger.debug(
                f"GraphConstructionSystem\nRelationships to deduplicate:\n{json.dumps(relationships_to_deduplicate,indent=4,default=str)}"
            )

            # Step 4 : Deduplicate relationships concurrently
            deduplication_tasks = [
                self._deduplicate_relationship(
                    relationship=relationship,
                    from_company=from_company,
                    max_wait_time_minutes=max_wait_time_per_task,
                )
                for relationship in relationships_to_deduplicate
            ]

            results = await asyncio.gather(*deduplication_tasks, return_exceptions=True)

            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    relationship_id = str(relationships_to_deduplicate[i].get("_id"))
                    graph_construction_logger.error(
                        f"GraphConstructionSystem\nDeduplication for relationship {relationship_id} failed in batch: {result}"
                    )
        graph_construction_logger.info(
            f"GraphConstructionSystem\nContinuous relationships deduplication process for company {from_company} has completed."
        )

    @retry(
        retry=retry_if_exception_type(DatabaseError),
        stop=stop_after_attempt(10),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def _deduplicate_relationship(
        self,
        relationship: dict,
        from_company: str,
        max_wait_time_minutes: int,
    ):
        # Step 1 : Find candidate relationship in cache
        matches = await (
            self.async_mongo_storage.get_database(
                self.relationship_cache_config["database_name"]
            )
            .get_collection(from_company)
            .read_documents(
                query={
                    "source_id": relationship["source_id"],
                    "target_id": relationship["target_id"],
                    "type": relationship["type"],
                }
            )
        )
        if matches:
            # Step 2a : If there is a matching relationship, attempt to acquire its write lock
            candidate_relationship_id = matches[0]["_id"]
            lock_acquired = False
            wait_time = timedelta(minutes=max_wait_time_minutes)
            poll_interval_seconds = 10
            start_time = get_current_datetime()

            try:
                while (get_current_datetime() - start_time) < wait_time:
                    graph_construction_logger.info(
                        f"GraphConstructionSystem\nAttempting to lock candidate relationship: '{str(candidate_relationship_id)}'"
                    )
                    # Atomic operation to acquire the lock
                    lock_result = (
                        await self.async_mongo_storage.get_database(
                            self.relationship_cache_config["database_name"]
                        )
                        .get_collection(from_company)
                        .update_document(
                            query={
                                "_id": candidate_relationship_id,
                                "lock_status": {"$ne": "LOCKED"},
                            },
                            update_data={
                                "lock_status": "LOCKED",
                                "lock_timestamp": get_current_datetime(),
                            },
                        )
                    )

                    if lock_result == 1:
                        lock_acquired = True
                        graph_construction_logger.info(
                            f"GraphConstructionSystem\nSuccessfully acquired lock on candidate: '{str(candidate_relationship_id)}'"
                        )
                        break
                    else:
                        graph_construction_logger.info(
                            f"GraphConstructionSystem\nCandidate '{str(candidate_relationship_id)}' is locked. Waiting for {poll_interval_seconds} seconds..."
                        )
                        await asyncio.sleep(poll_interval_seconds)

                # Step 3a : Check if the write lock is acquired
                if not lock_acquired:
                    graph_construction_logger.error(
                        f"GraphConstructionSystem\nFailed to acquire lock on '{str(candidate_relationship_id)}' within the timeout period. Aborting merge."
                    )
                    raise asyncio.TimeoutError(
                        f"GraphConstructionSystem\nTimed out waiting for lock on relationship '{str(candidate_relationship_id)}'"
                    )

                # Step 4a : Refetch the candidate relalationship after locking
                candidate_relationship = (
                    await self.async_mongo_storage.get_database(
                        self.relationship_cache_config["database_name"]
                    )
                    .get_collection(from_company)
                    .read_documents(query={"_id": candidate_relationship_id})
                )[0]

                # Step 5a : Merge the relationships
                await self._merge_relationships(
                    primary_relationship=relationship,
                    candidate_relationship=candidate_relationship,
                    from_company=from_company,
                )
                graph_construction_logger.debug(
                    f"GraphConstructionSystem\nSuccessfully merge primary_relationship with id: {str(relationship['_id'])} into candidate_relationship with id: {str(candidate_relationship['_id'])}"
                )
            except Exception as e:
                graph_construction_logger.error(
                    f"GraphConstructionSystem\nAn error occurred during deduplication for relationship {str(candidate_relationship_id)}: {e}",
                    exc_info=True,
                )
                raise
            finally:
                # Step 6a : Release the lock regardless of writing is performed
                if lock_acquired:
                    graph_construction_logger.info(
                        f"GraphConstructionSystem\nReleasing lock on candidate relationship: {str(candidate_relationship_id)}"
                    )
                    await self.async_mongo_storage.get_database(
                        self.relationship_cache_config["database_name"]
                    ).get_collection(from_company).update_document(
                        query={"_id": candidate_relationship_id},
                        update_data={
                            "$unset": {"lock_status": "", "lock_timestamp": ""}
                        },
                    )
        else:
            # Step 2b : If there is no matching relationship, insert the relationship
            await self._insert_realtionship_into_cache(
                relationship=relationship, from_company=from_company
            )
            graph_construction_logger.debug(
                f"GraphConstructionSystem\nSuccessfully inserted relationship with id: {str(relationship['_id'])} into relationships cache"
            )

    async def _insert_realtionship_into_cache(
        self, relationship: dict, from_company: str
    ):
        async with self.async_mongo_storage.with_transaction() as session:
            # Step 1 : Insert the relationship into mongodb relationships cache
            await self.async_mongo_storage.get_database(
                self.relationship_cache_config["database_name"]
            ).get_collection(from_company).create_document(
                data=get_formatted_relationship_cache_for_db(relationship=relationship),
                session=session,
            )

            # Step 2 : Update the status of the inserted relationship in permanent relationships storage
            await self.async_mongo_storage.get_database(
                self.relationship_config["database_name"]
            ).get_collection(
                self.relationship_config["collection_name"]
            ).update_document(
                query={"_id": relationship["_id"]},
                update_data={
                    "status": "TO_BE_UPSERTED_INTO_GRAPH_DB",
                    "last_modified_at": get_current_datetime(),
                },
                session=session,
            )

    async def _merge_relationships(
        self,
        primary_relationship: dict,
        candidate_relationship: dict,
        from_company: str,
    ):
        # Step 1 : Prepare the merged data
        new_valid_in = list(
            set(primary_relationship["valid_in"])
            | set(candidate_relationship["valid_in"])
        )
        llm_raw_result = await self.agents[
            "RelationshipDeduplicationAgent"
        ].handle_task(
            relationship_description=(
                primary_relationship["description"]
                + candidate_relationship["description"]
            ),
        )
        new_description = get_clean_json(llm_raw_result)["new_description"]

        async with self.async_mongo_storage.with_transaction() as session:
            current_timestamp = get_current_datetime()

            # Step 2 : Update the candidate_relationship in mongodb cache storage with new attributes
            await self.async_mongo_storage.get_database(
                self.relationship_cache_config["database_name"]
            ).get_collection(from_company).update_document(
                query={"_id": candidate_relationship["_id"]},
                update_data={
                    "description": new_description,
                    "valid_in": new_valid_in,
                    "last_modified_at": current_timestamp,
                },
                session=session,
            )

            # Step 3 : Update the status of the candidate_relationship in permanent relationships storage
            await self.async_mongo_storage.get_database(
                self.relationship_config["database_name"]
            ).get_collection(
                self.relationship_config["collection_name"]
            ).update_document(
                query={"_id": candidate_relationship["_id"]},
                update_data={
                    "status": "TO_BE_UPSERTED_INTO_GRAPH_DB",
                    "description": new_description,
                    "valid_in": new_valid_in,
                    "last_modified_at": current_timestamp,
                },
                session=session,
            )

            # Step 4 : Update the status of the primary_relationship in permanent relationships storage
            await self.async_mongo_storage.get_database(
                self.relationship_config["database_name"]
            ).get_collection(
                self.relationship_config["collection_name"]
            ).update_document(
                query={"_id": primary_relationship["_id"]},
                update_data={
                    "status": "TO_BE_DELETED",
                    "last_modified_at": current_timestamp,
                },
                session=session,
            )

    async def _update_relationships_cache_size(
        self,
        max_cache_size: int,
        num_of_relationships_per_batch: int,
        from_company: str,
    ):
        """
        Checks the relationships cache size and evicts the oldest items if the cache is nearing its capacity.
        This is a proactive eviction to make space for an incoming batch.
        """
        relationship_cache_collection = self.async_mongo_storage.get_database(
            self.relationship_cache_config["database_name"]
        ).get_collection(from_company)

        current_cache_size = await relationship_cache_collection.get_doc_counts()

        # Proactively make space if the cache is close to full
        if current_cache_size >= (max_cache_size - num_of_relationships_per_batch):
            num_of_cache_to_remove = current_cache_size - (
                max_cache_size - num_of_relationships_per_batch
            )
            if num_of_cache_to_remove <= 0:
                return

            graph_construction_logger.info(
                f"Cache size ({current_cache_size}) is nearing limit ({max_cache_size}). "
                f"Evicting {num_of_cache_to_remove} oldest items from '{from_company}'."
            )

            try:
                async with self.async_mongo_storage.with_transaction() as session:
                    # Step 1 : Get the oldest relationsihps to remove
                    oldest_items = await relationship_cache_collection.read_documents(
                        query={},
                        sort=[("last_modified_at", ASCENDING)],
                        limit=num_of_cache_to_remove,
                        session=session,
                    )

                    if not oldest_items:
                        return

                    ids_to_delete = [item["_id"] for item in oldest_items]

                    # Step 2 : Delete the relationships from the MongoDB cache in a single batch
                    delete_result = (
                        await relationship_cache_collection.delete_documents(
                            query={"_id": {"$in": ids_to_delete}}, session=session
                        )
                    )

                    graph_construction_logger.info(
                        f"Successfully evicted {delete_result.deleted_count} relationships from MongoDB cache "
                    )
            except Exception as e:
                graph_construction_logger.error(f"Failed during cache eviction: {e}")
                raise

    async def _get_relationships_to_deduplicate(
        self, from_company: str, num_of_relationships_per_batch: int
    ) -> list[dict]:
        return await (
            self.async_mongo_storage.get_database(
                self.relationship_config["database_name"]
            )
            .get_collection(self.relationship_config["collection_name"])
            .read_documents(
                query={
                    "status": "TO_BE_DEDUPLICATED",
                    "originated_from": {"$in": [from_company]},
                },
                limit=num_of_relationships_per_batch,
            )
        )

    async def revert_deduplication_status(
        self,
        from_company: str,
        from_status: str,
        to_status: str,
        collection_to_revert: str,
    ) -> None:
        """
        Function for debugging purpose
        """
        config_map = {
            "ENTITIES": self.entity_config,
            "RELATIONSHIPS": self.relationship_config,
        }

        config = config_map.get(collection_to_revert)
        if not config:
            graph_construction_logger.warning(
                f"Invalid collection name '{collection_to_revert}'. Valid options are: {list(config_map.keys())}. Aborting revert."
            )
            return

        try:
            result = (
                await self.async_mongo_storage.get_database(config["database_name"])
                .get_collection(config["collection_name"])
                .update_documents(
                    query={
                        "status": from_status,
                        "originated_from": {"$in": [from_company]},
                    },
                    update={"$set": {"status": to_status}},
                )
            )

            graph_construction_logger.info(
                f"Revert status successful for collection '{collection_to_revert}'. "
                f"Updated {result.modified_count} documents from status '{from_status}' to '{to_status}'."
            )

        except Exception as e:
            graph_construction_logger.error(
                f"Failed to revert status for collection '{collection_to_revert}': {e}"
            )
            raise

    async def upsert_entities_into_pinecone(self, from_company: str, batch_size: int):
        """
        Finds and upserts entities into Pinecone in manageable batches.
        """

        entity_collection = self.async_mongo_storage.get_database(
            self.entity_config["database_name"]
        ).get_collection(self.entity_config["collection_name"])

        graph_construction_logger.info(
            "Starting batch upsert process for entities into Pinecone."
        )

        total_processed = 0
        while True:
            try:
                # Step 1: Fetch one batch of entities
                entities_in_batch = await entity_collection.read_documents(
                    query={
                        "status": "TO_BE_UPSERTED_INTO_VECTOR_DB",
                        "originated_from": {"$in": [from_company]},
                    },
                    limit=batch_size,
                )
                if not entities_in_batch:
                    graph_construction_logger.info(
                        "No more entities to process. Batch upsert completed."
                    )
                    break

                # Step 2: Format and upsert the current batch into Pinecone
                formatted_entities = [
                    get_formatted_entity_for_vectordb(entity)
                    for entity in entities_in_batch
                ]
                await self.pinecone_storage.get_index(
                    self.entity_vector_config["index_name"]
                ).upsert_vectors(items=formatted_entities)

                # Step 3: Update the status ONLY for the entities in this successful batch
                entity_ids = [entity["_id"] for entity in entities_in_batch]
                await entity_collection.update_documents(
                    query={"_id": {"$in": entity_ids}},
                    update={"$set": {"status": "TO_BE_UPSERTED_INTO_GRAPH_DB"}},
                )

                total_processed += len(entities_in_batch)
                graph_construction_logger.info(
                    f"Successfully processed batch. Total entities processed so far: {total_processed}"
                )

            except Exception as e:
                graph_construction_logger.error(
                    f"An error occurred while processing a batch: {e}. Stopping process."
                )
                raise

        graph_construction_logger.info(
            f"GraphConstructionSystem\nFinished upserting entities into Pinecone. Total entities processed: {total_processed}."
        )

    async def upsert_entities_and_relationships_into_neo4j(
        self, from_company: str, batch_size: int
    ):
        await self._upsert_entities_into_neo4j(
            from_company=from_company, batch_size=batch_size
        )
        await self._upsert_relationships_into_neo4j(
            from_company=from_company, batch_size=batch_size
        )

    async def _upsert_entities_into_neo4j(
        self, from_company: str, batch_size: int = 100
    ):
        """
        Finds and upserts entities into Neo4j in manageable batches.
        """

        entity_collection = self.async_mongo_storage.get_database(
            self.entity_config["database_name"]
        ).get_collection(self.entity_config["collection_name"])

        graph_construction_logger.info(
            "Starting batch upsert process for entities into Neo4j."
        )

        total_processed = 0
        while True:
            try:
                # Step 1: Fetch one batch of entities
                entities_in_batch = await entity_collection.read_documents(
                    query={
                        "status": "TO_BE_UPSERTED_INTO_GRAPH_DB",
                        "originated_from": {"$in": [from_company]},
                    },
                    limit=batch_size,
                )
                if not entities_in_batch:
                    graph_construction_logger.info(
                        "No more entities to process. Batch upsert completed."
                    )
                    break

                # Step 2 : Format and upsert the current batch into Neo4j
                formatted_entities = [
                    get_formatted_entity_for_graphdb(entity)
                    for entity in entities_in_batch
                ]
                await self.graph_storage.upsert_entities(formatted_entities)

                # Step 3: Update the status ONLY for the entities in this successful batch
                entity_ids = [entity["_id"] for entity in entities_in_batch]
                await entity_collection.update_documents(
                    query={"_id": {"$in": entity_ids}},
                    update={"$set": {"status": "UPSERTED_INTO_GRAPH_DB"}},
                )

                total_processed += len(entities_in_batch)
                graph_construction_logger.info(
                    f"Successfully processed batch. Total entities processed so far: {total_processed}"
                )
            except Exception as e:
                graph_construction_logger.error(
                    f"An error occurred while processing a batch: {e}. Stopping process."
                )
                raise

        graph_construction_logger.info(
            f"GraphConstructionSystem\nFinished upserting entities into Neo4j. Total entities processed: {total_processed}."
        )

    async def _upsert_relationships_into_neo4j(
        self, from_company: str, batch_size: int = 100
    ):
        """
        Finds and upserts relationships into Neo4j in manageable batches.
        """
        relationship_collection = self.async_mongo_storage.get_database(
            self.relationship_config["database_name"]
        ).get_collection(self.relationship_config["collection_name"])
        graph_construction_logger.info(
            "Starting batch upsert process for relationships into Neo4j."
        )

        total_processed = 0
        while True:
            try:
                # Step 1: Fetch one batch of relationships
                relationships_in_batch = await relationship_collection.read_documents(
                    query={
                        "status": "TO_BE_UPSERTED_INTO_GRAPH_DB",
                        "originated_from": {"$in": [from_company]},
                    },
                    limit=batch_size,
                )
                if not relationships_in_batch:
                    graph_construction_logger.info("No more relationships to process.")
                    break

                # Step 2: Format and upsert the current batch into Neo4j
                formatted_relationships = [
                    get_formatted_relationship_for_graphdb(relationship)
                    for relationship in relationships_in_batch
                ]
                await self.graph_storage.upsert_relationships(formatted_relationships)

                # Step 3: Update the status ONLY for the relationships in this successful batch
                relationship_ids = [
                    relationship["_id"] for relationship in relationships_in_batch
                ]
                await relationship_collection.update_documents(
                    query={"_id": {"$in": relationship_ids}},
                    update={"$set": {"status": "UPSERTED_INTO_GRAPH_DB"}},
                )

                total_processed += len(relationships_in_batch)
                graph_construction_logger.info(
                    f"Successfully processed batch. Total relationships processed so far: {total_processed}"
                )

            except Exception as e:
                graph_construction_logger.error(
                    f"An error occurred while processing a batch: {e}. Stopping process."
                )
                raise
        graph_construction_logger.info(
            f"GraphConstructionSystem\nFinished upserting relationships into Neo4j. Total relationships processed: {total_processed}."
        )

    async def get_entity_count(self, query: dict):
        return await (
            self.async_mongo_storage.get_database(self.entity_config["database_name"])
            .get_collection(self.entity_config["collection_name"])
            .get_doc_counts(query=query)
        )

    async def get_relationship_count(self, query: dict):
        return await (
            self.async_mongo_storage.get_database(
                self.relationship_config["database_name"]
            )
            .get_collection(self.relationship_config["collection_name"])
            .get_doc_counts(query=query)
        )

    async def get_formatted_similar_entities_from_pinecone(
        self,
        query_texts: str | list[str],
        top_k: int,
        query_filter: dict | None = None,
        score_threshold: float = 0.0,
    ):
        similar_entities = await self.pinecone_storage.get_index(
            self.entity_vector_config["index_name"]
        ).get_similar_results(
            query_texts=query_texts,
            top_k=top_k,
            query_filter=query_filter,
            score_threshold=score_threshold,
        )
        formatted_similar_entities = get_formatted_similar_entities(
            query_texts=query_texts, results=similar_entities
        )
        return formatted_similar_entities
