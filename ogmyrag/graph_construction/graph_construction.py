from __future__ import annotations

import logging
import asyncio
import json
from collections import defaultdict
from bson import ObjectId
from pymongo import ASCENDING, DESCENDING
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

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
)
from ..storage import AsyncMongoDBStorage, PineconeStorage, Neo4jStorage

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
    get_simplified_similar_entities_list,
    # get_formatted_entity_cache_for_db,
    # get_formatted_entity_cache_for_vectordb,
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
        #   graph_construction_logger.debug(f"User prompt used:\n{user_prompt}")

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


class GraphConstructionSystem(BaseMultiAgentSystem):
    def __init__(
        self,
        async_mongo_client: AsyncIOMotorClient,
        ontology_config: MongoStorageConfig,
        disclosure_config: MongoStorageConfig,
        entity_config: MongoStorageConfig,
        relationship_config: MongoStorageConfig,
        entity_cache_config: MongoStorageConfig,
        entity_vector_config: PineconeStorageConfig,
        entity_cache_vector_config: PineconeStorageConfig,
        graphdb_config: Neo4jStorageConfig,
    ):
        super().__init__(
            {
                "EntityRelationshipExtractionAgent": EntityRelationshipExtractionAgent(
                    "EntityRelationshipExtractionAgent"
                )
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
                    new_values={"is_parsed": True},
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
        cache_size: int,
        similarity_threshold: float,
    ):
        # unchecked_entities = await self.entity_storage.read_documents(
        #     {"deduplication_info.check_duplicated": False}, limit=10
        # )

        # for entity in unchecked_entities:

        #     simplified_similar_results = (
        #         get_formatted_similar_entities_for_deduplication(
        #             get_simplified_similar_entities_list(similar_results)
        #         )
        #     )

        #     graph_construction_logger.info(
        #         f"GraphConstructionSystem\nTesting deduplication for entity {str(entity.get('_id',''))}：\n{simplified_similar_results} "
        #     )
        # deduplication_tasks = []

        # entities = await self.entity_cache_vector_storage.get_similar_results(
        #     query_texts=entity_name, namespace=namespace, top_k=1
        # )
        entities_to_deduplicate = await self._get_entities_to_deduplicate(
            from_company=from_company,
            num_of_entities_to_fetch=num_of_entities_per_batch,
        )
        graph_construction_logger.info(
            f"GraphConstructionSystem\nEntities to deduplicate:\n{json.dumps(entities_to_deduplicate,indent=4,default=str)}"
        )

    async def deduplicate_entity(
        self, entity: dict, from_company: str, similarity_threshold: float
    ):
        # similar_result = (
        #     await self.async_mongo_storage.get_database(
        #         self.entity_cache_config["database_name"]
        #     )
        #     .get_collection(self.entity_cache_config["collection_name"])
        #     .get_similar_results(
        #         query_texts=entity.get("name", ""),
        #         top_k=1,
        #         query_filter={"entity_type": {"$eq": entity.get("type", "")}},
        #         score_threshold=similarity_threshold,
        #     )
        # )
        pass

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

            await self.pinecone_storage.get_index(self.entity_vector_config["index_name"]).upsert_vectors(formatted_entities)

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
        similar_entities = await self.pinecone_storage.get_index(self.entity_vector_config["index_name"]).get_similar_results(
            query_texts=query_texts,
            top_k=top_k,
            query_filter=query_filter,
            score_threshold=score_threshold,
        )
        formatted_similar_entities = get_formatted_similar_entities(
            query_texts=query_texts, results=similar_entities
        )
        return formatted_similar_entities
