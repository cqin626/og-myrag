from __future__ import annotations

import logging
import asyncio
import json
import copy
from datetime import timedelta
from collections import defaultdict
from bson import ObjectId
from pymongo import ASCENDING, DESCENDING
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
from ..prompts import PROMPT
from ..llm import fetch_responses_openai
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
from ..storage import AsyncMongoDBStorage, PineconeStorage, Neo4jStorage, DatabaseError

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
    get_formatted_entities_and_relationships_for_db,
)

graph_construction_logger = logging.getLogger("graph_construction")


class EntityRelationshipExtractionAgent(BaseAgent):
    """
    An agent responsible for extracting entities and relationships from document given.
    """

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
        # graph_construction_logger.info(
        #     f"EntityRelatonshipExtractionAgent\nOntology used:\n{formatted_ontology}"
        # )

        system_prompt = PROMPT["ENTITIES_RELATIONSHIPS_PARSING"].format(
            ontology=formatted_ontology,
            publish_date=kwargs.get("source_text_publish_date", "NA") or "NA",
        )
        # graph_construction_logger.info(
        #     f"EntityRelatonshipExtractionAgent\System prompt used:\n{system_prompt}"
        # )

        constraints = kwargs.get("source_text_constraints") or ""
        source_text = kwargs.get("source_text") or "NA"
        user_prompt = constraints + source_text
        graph_construction_logger.debug(f"User prompt used:\n{user_prompt}")

        response = await fetch_responses_openai(
            model="o4-mini",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            text={"format": {"type": "text"}},
            reasoning={"effort": "medium"},
            max_output_tokens=100000,
            stream=False,
            tools=[],
        )
        graph_construction_logger.info(
            f"EntityRelatonshipExtractionAgent\nEntity-relationship extraction response details:\n{get_formatted_openai_response(response)}"
        )

        return response.output_text


class EntityDeduplicationAgent(BaseAgent):
    """
    An agent responsible for deduplicating extracted entities.
    """

    async def handle_task(self, **kwargs) -> str:
        """
        Parameters:
           entities_to_compare (str)
        """
        graph_construction_logger.info(f"EntityDeduplicationAgent is called")

        system_prompt = PROMPT["ENTITIES_DEDUPLICATION"]
        # graph_construction_logger.debug(
        #     f"EntityDeduplicationAgent\System prompt used:\n{system_prompt}"
        # )

        user_prompt = kwargs.get("entities_to_compare") or ""
        # graph_construction_logger.debug(f"User prompt used:\n{user_prompt}")

        response = await fetch_responses_openai(
            model="o4-mini",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            text={"format": {"type": "text"}},
            reasoning={"effort": "medium"},
            max_output_tokens=100000,
            stream=False,
            tools=[],
        )
        graph_construction_logger.info(
            f"EntityDeduplicationAgent\nEntity deduplication response details:\n{get_formatted_openai_response(response)}"
        )

        return response.output_text


class GraphConstructionSystem(BaseMultiAgentSystem):
    def __init__(
        self,
        async_mongo_client: AsyncIOMotorClient,
        ontology_config: MongoStorageConfig,
        disclosure_config: MongoStorageConfig,
        entity_config: MongoStorageConfig,
        relationship_config: MongoStorageConfig,
        entity_cache_config: MongoStorageConfig,
        entities_deduplication_pending_tasks_config: MongoStorageConfig,
        entity_vector_config: PineconeStorageConfig,
        entity_cache_vector_config: PineconeStorageConfig,
        graphdb_config: Neo4jStorageConfig,
    ):
        super().__init__(
            {
                "EntityRelationshipExtractionAgent": EntityRelationshipExtractionAgent(
                    "EntityRelationshipExtractionAgent"
                ),
                "EntityDeduplicationAgent": EntityDeduplicationAgent(
                    "EntityDeduplicationAgent"
                ),
            }
        )

        try:
            self.ontology_config = ontology_config
            self.disclosure_config = disclosure_config
            self.entity_config = entity_config
            self.relationship_config = relationship_config
            self.entity_cache_config = entity_cache_config
            self.entity_vector_config = entity_vector_config
            self.entity_cache_vector_config = entity_cache_vector_config
            self.entities_deduplication_pending_tasks_config = (
                entities_deduplication_pending_tasks_config
            )
            self.async_mongo_storage = AsyncMongoDBStorage(async_mongo_client)

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

            self.graph_storage = Neo4jStorage(**graphdb_config)

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
                await self.async_mongo_storage.get_database(
                    self.disclosure_config["database_name"]
                )
                .get_collection(self.disclosure_config["collection_name"])
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
                await self.async_mongo_storage.get_database(
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

                # Step 3: Update the company disclosure as processed
                await self.async_mongo_storage.get_database(
                    self.disclosure_config["database_name"]
                ).get_collection(
                    self.disclosure_config["collection_name"]
                ).update_document(
                    query={"_id": data["document_id"]},
                    update_data={"is_parsed": True},
                    session=session,
                )

                graph_construction_logger.info(
                    f"GraphConstructionSystem\nSuccessfully inserted {len(inserted_entity_ids)} entity(ies) and {len(inserted_relationship_ids)} relationship(s) into MongoDB."
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
            # Step 1 : Fetch unparsed entities
            entities_to_deduplicate = await self._get_entities_to_deduplicate(
                from_company=from_company,
                num_of_entities_to_fetch=num_of_entities_per_batch,
            )

            # Step 2 : Check the exit condition for the loop
            if not entities_to_deduplicate:
                graph_construction_logger.info(
                    "GraphConstructionSystem\nNo more entities to deduplicate. Exiting process."
                )
                break

            graph_construction_logger.debug(
                f"GraphConstructionSystem\nEntities to deduplicate:\n{json.dumps(entities_to_deduplicate,indent=4,default=str)}"
            )

            # Step 3 : Deduplicate entities concurrently
            deduplication_tasks = [
                self.deduplicate_entity(
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

            # Step 4 : Resolve any pending tasks created by the batch (upserting entities into Pinecone)
            await self.resolve_entities_deduplication_pending_tasks(
                from_company=from_company,
                entities_to_resolve_per_batch=num_of_entities_per_batch,
            )

        graph_construction_logger.info(
            f"GraphConstructionSystem\nContinuous deduplication process for company {from_company} has completed."
        )

    @retry(
        retry=retry_if_exception_type(DatabaseError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def deduplicate_entity(
        self,
        entity: dict,
        from_company: str,
        similarity_threshold: float,
        num_of_relationships_to_fetch: int,
        max_wait_time_minutes: int,
    ):
        """
        Finds and deduplicates a single entity, with automatic retries for
        transient database errors like WriteConflict.
        """
        # Step 1 : Find a candidate in cache storage
        raw_results = await self.pinecone_storage.get_index(
            self.entity_cache_vector_config["index_name"]
        ).get_similar_results(
            query_texts=entity.get("name", ""),
            top_k=1,
            query_filter={"type": {"$eq": entity.get("type", "")}},
            score_threshold=similarity_threshold,
            namespace=from_company,
        )

        graph_construction_logger.debug(
            f"GraphConstructionSystem\nSimilar results fetched in deduplicate_entity(): {raw_results}"
        )

        similar_results = raw_results[0].get("matches", [])

        if similar_results:
            # Step 2a : If there is a matching candidate entity, attempt to acquire its write lock
            # Response is from Pinecone, thereby it is 'id' not '_id'
            candidate_entity_id = similar_results[0]["id"]
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
                f"GraphConstructionSystem\nSuccessfully inserted entity with id: {str(entity['_id'])}"
            )

    # async def _update_cache_size(
    #     self, max_cache_size: int, num_of_entities_per_batch: int, from_company: str
    # ):
    #     current_cache_size = await (
    #         self.async_mongo_storage.get_database(
    #             self.entity_cache_config["database_name"]
    #         )
    #         .get_collection(from_company)
    #         .get_doc_counts()
    #     )

    #     if current_cache_size >= (max_cache_size - num_of_entities_per_batch):
    #         num_of_cache_to_remove = current_cache_size - (
    #             max_cache_size - num_of_entities_per_batch
    #         )

    #         async with self.async_mongo_storage.with_transaction() as session:
    #             last_n_items = await (
    #                 self.async_mongo_storage.get_database(
    #                     self.entity_cache_config["database_name"]
    #                 )
    #                 .get_collection(from_company)
    #                 .read_documents(
    #                     query={},
    #                     sort=[("last_modified_at", ASCENDING)],
    #                     limit=num_of_entities_per_batch,
    #                     session=session,
    #                 ),
    #             )

    #             ids_to_delete = [item["_id"] for item in last_n_items]

    #             self.async_mongo_storage.get_database(
    #                 self.entity_cache_config["database_name"]
    #             ).get_collection(from_company).update_documents(
    #                 query={"_id": {"$in": ids_to_delete}}, update={}, session=session
    #             )

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

    async def resolve_entities_deduplication_pending_tasks(
        self, from_company: str, entities_to_resolve_per_batch: int = 200
    ):
        """
        Insert entities for caching in mongodb into vectordb (idempotent).
        Called after every batch of deduplication OR sudden breakdown that leaves to inconsistent state in Pinecone
        """
        # Step 1 : Fetch the entities that are not yet inserted into Pinecone
        pending_tasks = await (
            self.async_mongo_storage.get_database(
                self.entities_deduplication_pending_tasks_config["database_name"]
            )
            .get_collection(
                self.entities_deduplication_pending_tasks_config["collection_name"]
            )
            .read_documents(
                query={"status": "PENDING", "from_company": from_company},
                limit=entities_to_resolve_per_batch,
            )
        )

        if not pending_tasks:
            return

        formatted_entities_to_insert = []
        update_tasks = []

        for task in pending_tasks:
            entity = task["payload"]

            formatted_entities_to_insert.append(
                get_formatted_entity_for_vectordb(entity)
            )

            update_tasks.append(
                self.async_mongo_storage.get_database(
                    self.entities_deduplication_pending_tasks_config["database_name"]
                )
                .get_collection(
                    self.entities_deduplication_pending_tasks_config["collection_name"]
                )
                .update_document(
                    query={"_id": task["_id"]}, update_data={"status": "COMPLETED"}
                )
            )

        # Step 2 : Upsert the entities into Pinecone
        await self.pinecone_storage.get_index(
            self.entity_cache_vector_config["index_name"]
        ).upsert_vectors(items=formatted_entities_to_insert, namespace=from_company)

        # Step 3 : Update the status of pending task to 'COMPLETED'
        await asyncio.gather(*update_tasks)

        graph_construction_logger.info(
            f"GraphConstructionSystem\nSuccessfully inserted {len(pending_tasks)} into Pinecone for caching."
        )

    async def revert_entities_deduplication_status(
        self, from_company: str, from_status: str, to_status: str
    ) -> None:
        # Function for debugging purpose
        deduplicated_entities = (
            await self.async_mongo_storage.get_database(
                self.entity_config["database_name"]
            )
            .get_collection(self.entity_config["collection_name"])
            .read_documents(
                query={
                    "status": from_status,
                    "originated_from": {"$in": [from_company]},
                }
            )
        )
        await asyncio.gather(
            *[
                self.async_mongo_storage.get_database(
                    self.entity_config["database_name"]
                )
                .get_collection(self.entity_config["collection_name"])
                .update_document(
                    query={"_id": entity["_id"]},
                    update_data={"status": to_status},
                )
                for entity in deduplicated_entities
            ]
        )

        graph_construction_logger.debug(
            f"GraphConstructionSystem\nChanged the status for {len(deduplicated_entities)}"
        )

    async def insert_entities_into_pinecone(self):
        try:
            formatted_entities = []
            entities = (
                await self.async_mongo_storage.get_database(
                    self.entity_config["database_name"]
                )
                .get_collection(self.entity_config["collection_name"])
                .read_documents({"inserted_into_vectordb_at": ""})
            )

            if not entities:
                graph_construction_logger.info(
                    "GraphConstructionSystem\nNo entities found. Skipping insertion into Pinecone."
                )
                raise RuntimeError(f"No entities found.")

            for entity in entities:
                formatted_entities.append(get_formatted_entity_for_vectordb(entity))

            await self.pinecone_storage.get_index(
                self.entity_vector_config["index_name"]
            ).upsert_vectors(formatted_entities)

            update_tasks = []

            for entity in entities:
                update_tasks.append(
                    self.async_mongo_storage.get_database(
                        self.entity_config["database_name"]
                    )
                    .get_collection(self.entity_config["collection_name"])
                    .update_document(
                        {"_id": entity["_id"]},
                        {
                            "inserted_into_vectordb_at": get_formatted_current_datetime(
                                "Asia/Kuala_Lumpur"
                            )
                        },
                    )
                )

            await asyncio.gather(*update_tasks)

            graph_construction_logger.info(
                f"GraphConstructionSystem\nUpdated {len(entities)} entity(ies) with inserted_into_vectordb_at field."
            )
        except Exception as e:
            graph_construction_logger.error(
                f"GraphConstructionSystem\nError while inserting entities into Pinecone:{e}"
            )
            raise RuntimeError(f"Failed to insert entities into Pinecone: {e}")

    async def insert_entities_into_neo4j(self):
        try:
            graph_construction_logger.info(
                f"GraphConstructionSystem\nReading entities from MongoDB..."
            )

            raw_entities = (
                await self.async_mongo_storage.get_database(
                    self.entity_config["database_name"]
                )
                .get_collection(self.entity_config["collection_name"])
                .read_documents({"inserted_into_graphdb_at": ""})
            )

            if not raw_entities:
                graph_construction_logger.info(
                    f"GraphConstructionSystem\nNo entities that have not been uploaded to Neo4j."
                )
                raise RuntimeError(f"No entities that have not been uploaded to Neo4j.")

            graph_construction_logger.info(
                f"GraphConstructionSystem\nRead {len(raw_entities)} entity(ies) that have not been uploaded to Neo4j."
            )
        except Exception as e:
            graph_construction_logger.error(
                f"GraphConstructionSystem\nError while reading entities from MongoDB:{e}"
            )
            raise RuntimeError(f"Failed to read entities from MongoDB: {e}")

        try:
            graph_construction_logger.info(
                f"GraphConstructionSystem\nInserting {len(raw_entities)} entity(ies) into Neo4j..."
            )

            grouped_entities = defaultdict(list)
            for raw_entity in raw_entities:
                entity_type = raw_entity["type"]
                grouped_entities[entity_type].append(raw_entity)

            for entity_type, entities in grouped_entities.items():
                formatted_entities = [
                    get_formatted_entity_for_graphdb(e) for e in entities
                ]
                self.graph_storage.insert_entities(
                    entities=formatted_entities, label=entity_type
                )
            graph_construction_logger.info(
                f"GraphConstructionSystem\nSuccessfully inserted {len(raw_entities)} entity(ies) into Neo4j."
            )
        except Exception as e:
            graph_construction_logger.error(
                f"GraphConstructionSystem\nError while inserting entity(ies) into Neo4j:{e}"
            )
            raise RuntimeError(f"Failed to insert entity(ies) into Neo4j: {e}")

        try:
            graph_construction_logger.info(
                f"GraphConstructionSystem\nUpdating {len(raw_entities)} entity(ies) with 'inserted_into_graphdb_at' field."
            )

            update_tasks = []

            for entity in raw_entities:
                update_tasks.append(
                    self.async_mongo_storage.get_database(
                        self.entity_config["database_name"]
                    )
                    .get_collection(self.entity_config["collection_name"])
                    .update_document(
                        {"_id": entity["_id"]},
                        {
                            "inserted_into_graphdb_at": get_formatted_current_datetime(
                                "Asia/Kuala_Lumpur"
                            )
                        },
                    )
                )

            await asyncio.gather(*update_tasks)

            graph_construction_logger.info(
                f"GraphConstructionSystem\nUpdated {len(raw_entities)} entity(ies) with 'inserted_into_graphdb_at' field."
            )
        except Exception as e:
            graph_construction_logger.error(
                f"GraphConstructionSystem\nError while updating entity(ies) with 'inserted_into_graphdb_at' field:{e}"
            )
            raise RuntimeError(
                f"Failed to update entity(ies) with 'inserted_into_graphdb_at' field: {e}"
            )

    async def insert_relationships_into_neo4j(self):
        try:
            graph_construction_logger.info(
                f"GraphConstructionSystem\nReading relationships from MongoDB..."
            )

            raw_relationships = (
                await self.async_mongo_storage.get_database(
                    self.relationship_config["database_name"]
                )
                .get_collection(self.relationship_config["collection_name"])
                .read_documents({"inserted_into_graphdb_at": ""})
            )

            if not raw_relationships:
                graph_construction_logger.info(
                    f"GraphConstructionSystem\nNo relationships that have not been uploaded to Neo4j."
                )
                raise RuntimeError(
                    f"No relationships that have not been uploaded to Neo4j."
                )

            graph_construction_logger.info(
                f"GraphConstructionSystem\nRead {len(raw_relationships)} relationship(s) that have not been uploaded to Neo4j."
            )
        except Exception as e:
            graph_construction_logger.error(
                f"GraphConstructionSystem\nError while reading relationships from MongoDB:{e}"
            )
            raise RuntimeError(f"Failed to read relationships from MongoDB: {e}")

        try:
            graph_construction_logger.info(
                f"GraphConstructionSystem\nInserting {len(raw_relationships)} relationship(s) into Neo4j..."
            )

            formatted_relationships = []
            for raw_relationship in raw_relationships:
                formatted_relationships.append(
                    get_formatted_relationship_for_graphdb(raw_relationship)
                )

            self.graph_storage.insert_relationships(formatted_relationships)
            graph_construction_logger.info(
                f"GraphConstructionSystem\nSuccessfully inserted {len(raw_relationships)} relationship(s) into Neo4j."
            )
        except Exception as e:
            graph_construction_logger.error(
                f"GraphConstructionSystem\nError while inserting relationship(s) into Neo4j:{e}"
            )
            raise RuntimeError(f"Failed to insert relationship(s) into Neo4j: {e}")

        try:
            graph_construction_logger.info(
                f"GraphConstructionSystem\nUpdating {len(raw_relationships)} relationship(s) with 'inserted_into_graphdb_at' field."
            )
            update_tasks = []
            for relationship in raw_relationships:
                update_tasks.append(
                    self.async_mongo_storage.get_database(
                        self.relationship_config["database_name"]
                    )
                    .get_collection(self.relationship_config["collection_name"])
                    .update_document(
                        {"_id": relationship["_id"]},
                        {
                            "inserted_into_graphdb_at": get_formatted_current_datetime(
                                "Asia/Kuala_Lumpur"
                            )
                        },
                    )
                )

            await asyncio.gather(*update_tasks)

            graph_construction_logger.info(
                f"GraphConstructionSystem\nUpdated {len(raw_relationships)} relationship(s) with 'inserted_into_graphdb_at' field."
            )
        except Exception as e:
            graph_construction_logger.error(
                f"GraphConstructionSystem\nError while updating relationship(s) with 'inserted_into_graphdb_at' field:{e}"
            )
            raise RuntimeError(
                f"Failed to update relationship(s) with 'inserted_into_graphdb_at' field: {e}"
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
