from __future__ import annotations

import logging
import asyncio

from collections import defaultdict

from ..prompts import PROMPT
from ..llm import fetch_responses_openai
from ..util import (
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

from .graph_construction_util import (
    get_formatted_entities_and_relationships_for_db,
    get_formatted_entity_for_vectordb,
    get_formatted_entity_for_graphdb,
    get_formatted_relationship_for_graphdb,
    get_simplified_similar_entities_list,
    get_formatted_similar_entities_for_deduplication,
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
        formatted_ontology = get_formatted_ontology(
            data=kwargs.get("ontology", {}) or {},
        )

        system_prompt = PROMPT["ENTITIES_RELATIONSHIPS_PARSING"].format(
            ontology=formatted_ontology,
            publish_date=kwargs.get("source_text_publish_date", "NA") or "NA",
        )

        constraints = kwargs.get("source_text_constraints") or ""
        source_text = kwargs.get("source_text") or "NA"
        user_prompt = constraints + source_text

        #   graph_construction_logger.debug(f"System Prompt:\n\n{system_prompt}")

        graph_construction_logger.info(f"EntityRelatonshipExtractionAgent is called")

        # graph_construction_logger.info(
        #     f"EntityRelatonshipExtractionAgent\nOntology used:\n{formatted_ontology}"
        # )

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
            graph_construction_logger.info(
                f"EntityRelatonshipExtractionAgent\nEntity-relationship extraction response details:\n{get_formatted_openai_response(response)}"
            )

            graph_construction_logger.info(
                f"EntityRelatonshipExtractionAgent\nEntities and relationships extracted:\n{get_formatted_entities_and_relationships(response.output_text)}"
            )

            return response.output_text
        except Exception as e:
            graph_construction_logger.error(
                f"EntityRelatonshipExtractionAgent\nEntity-relationship extraction failed: {str(e)}"
            )
            return ""


class GraphConstructionSystem(BaseMultiAgentSystem):
    def __init__(
        self,
        ontology_config: MongoStorageConfig,
        disclosure_config: MongoStorageConfig,
        entity_config: MongoStorageConfig,
        relationship_config: MongoStorageConfig,
        deduplication_log_config: MongoStorageConfig,
        entity_vector_config: PineconeStorageConfig,
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
            self.onto_storage = MongoDBStorage(ontology_config["connection_uri"])
            self.onto_storage.use_database(ontology_config["database_name"])
            self.onto_storage.use_collection(ontology_config["collection_name"])

            self.disclosure_storage = AsyncMongoDBStorage(
                disclosure_config["connection_uri"]
            )
            self.disclosure_storage.use_database(disclosure_config["database_name"])
            self.disclosure_storage.use_collection(disclosure_config["collection_name"])

            self.entity_storage = AsyncMongoDBStorage(entity_config["connection_uri"])
            self.entity_storage.use_database(entity_config["database_name"])
            self.entity_storage.use_collection(entity_config["collection_name"])

            self.relationship_storage = AsyncMongoDBStorage(
                relationship_config["connection_uri"]
            )
            self.relationship_storage.use_database(relationship_config["database_name"])
            self.relationship_storage.use_collection(
                relationship_config["collection_name"]
            )

            self.deduplication_log_storage = AsyncMongoDBStorage(
                deduplication_log_config["connection_uri"]
            )
            self.deduplication_log_storage.use_database(
                deduplication_log_config["database_name"]
            )
            self.deduplication_log_storage.use_collection(
                deduplication_log_config["collection_name"]
            )

            self.entity_vector_storage = PineconeStorage(**entity_vector_config)

            self.graph_storage = Neo4jStorage(**graphdb_config)

        except Exception as e:
            graph_construction_logger.error(f"GraphConstructionSystem: {e}")
            raise ValueError(f"Failed to intialize GraphConstructionSystem: {e}")

    def get_n_relationships_with_entity_types(self, ontology: dict, i: int, k: int):
        """
        Extracts relationships from index i to k (inclusive of i, exclusive of k), and returns a JSON structure containing:
        - unique entity types involved (with their metadata)
        - full relationship definitions

        Parameters:
        - ontology: The ontology dictionary
        - i (int): start index (inclusive)
        - k (int): end index (exclusive)

        Returns:
        - A dictionary with "entities" and "relationships".
        """

        result = {"entities": {}, "relationships": {}}

        relationships = ontology["relationships"]
        entities = ontology["entities"]

        rel_items = list(relationships.items())

        # Clamp k to avoid index error
        k = min(k, len(rel_items))

        for rel_name, rel_data in rel_items[i:k]:
            # Add the relationship
            result["relationships"][rel_name] = rel_data

            # Handle source(s)
            sources = rel_data.get("source")
            if isinstance(sources, list):
                for src in sources:
                    result["entities"][src] = ontology["entities"][src]
            else:
                result["entities"][sources] = ontology["entities"][sources]

            # Handle target(s)
            targets = rel_data.get("target")
            if isinstance(targets, list):
                for target in targets:
                    result["entities"][target] = ontology["entities"][target]
            else:
                result["entities"][targets] = ontology["entities"][targets]

        return result

    async def insert_entities_relationships_from_unparsed_documents_into_mongodb(
        self,
        from_company: str,
        type: str,
        published_at: str,
        exclude_documents: list[str],
    ) -> None:
        """
        Insert the entities and relationships extracted from specified documents into MongoDB.
        """
        # Step 1 : Get the latest ontology
        try:
            graph_construction_logger.info(
                "GraphConstructionSystem\nPreparing ontology..."
            )
            latest_onto = (
                self.onto_storage.read_documents({"is_latest": True})[0].get(
                    "ontology", {}
                )
                or {}
            )
        except Exception as e:
            graph_construction_logger.error(
                f"GraphConstructionSystem\nError while getting latest ontology:{e}"
            )
            raise ValueError(f"Failed to latest ontology: {e}")

        # Step 2 : Read the constraints from the disclosure storage
        try:
            graph_construction_logger.info(
                "GraphConstructionSystem\nPreparing constraints..."
            )
            constraints = []
            raw_document_constraints = await self.disclosure_storage.read_documents(
                {
                    "from_company": from_company.strip().upper(),
                    "type": "CONSTRAINTS",
                    "published_at": published_at,
                }
            )
            for doc in raw_document_constraints:
                constraints.append(doc.get("content", ""))
            formatted_constraints = "\n".join(constraints)
            graph_construction_logger.info(
                f"GraphConstructionSystem\nConstraints used for extraction\n\n{formatted_constraints}"
            )
        except Exception as e:
            graph_construction_logger.error(
                f"GraphConstructionSystem\nError while preparing constraints:{e}"
            )
            raise ValueError(f"Failed to prepare constraints: {e}")

        # Step 3 : Read the unparsed documents from the disclosure storage
        try:
            graph_construction_logger.info(
                "GraphConstructionSystem\nPreparing unparsed documents..."
            )
            unparsed_documents = []
            raw_documents = await self.disclosure_storage.read_documents(
                {
                    "from_company": from_company.strip().upper(),
                    "type": type.strip().upper(),
                    "published_at": published_at,
                    "is_parsed": False,
                }
            )
            for i, doc in enumerate(raw_documents, start=1):
                name = doc.get("name", "")
                if name not in exclude_documents:
                    unparsed_documents.append(doc.get("content", ""))
                    graph_construction_logger.info(
                        f"GraphConstructionSystem\nDocuments to be parsed: {i}. {name}"
                    )
        except Exception as e:
            graph_construction_logger.error(
                f"GraphConstructionSystem\nError while preparing unparsed documents:{e}"
            )
            raise ValueError(f"Failed to prepare unparsed documents: {e}")

        # Step 4 : Calling LLM to extract entities and relationships from the documents

        try:
            graph_construction_logger.info(
                "GraphConstructionSystem\nExtracting entities and relationships from unparsed documents..."
            )
            if not unparsed_documents:
                graph_construction_logger.info(
                    "GraphConstructionSystem\nNo unparsed documents found. Skipping extraction."
                )
                raise ValueError(f"No unparsed documents found.")

            extraction_agent_responses = (
                await self.extract_entities_relationships_from_multiple_documents(
                    ontology=latest_onto,
                    source_texts=unparsed_documents,
                    source_texts_publish_date=published_at,
                    source_texts_constraints=formatted_constraints,
                )
            )

        except Exception as e:
            graph_construction_logger.error(
                f"GraphConstructionSystem\nError while extracting entities and relationships:{e}"
            )
            raise ValueError(f"Failed to extract entities and relationships: {e}")

        # Step 5: Insert the entities and relationships into MongoDB (Async)
        try:
            graph_construction_logger.info(
                "GraphConstructionSystem\nInserting entities and relationships into MongoDB..."
            )

            entity_insert_tasks = []
            relationship_insert_tasks = []

            for response in extraction_agent_responses:
                formatted_entities, formatted_relationships = (
                    get_formatted_entities_and_relationships_for_db(response)
                )
                if formatted_entities:
                    for entity in formatted_entities:
                        entity_insert_tasks.append(
                            self.entity_storage.create_document(entity)
                        )

                if formatted_relationships:
                    for relationship in formatted_relationships:
                        relationship_insert_tasks.append(
                            self.relationship_storage.create_document(relationship)
                        )

            inserted_entity_ids = await asyncio.gather(*entity_insert_tasks)
            inserted_relationship_ids = await asyncio.gather(*relationship_insert_tasks)

            graph_construction_logger.info(
                f"GraphConstructionSystem\nSuccessfully inserted {len(inserted_entity_ids)} entity(ies) and {len(inserted_relationship_ids)} relationship(s) into MongoDB."
            )

        except Exception as e:
            graph_construction_logger.error(
                f"GraphConstructionSystem\nError while inserting entities and relationships into MongoDB:{e}"
            )
            raise ValueError(
                f"Failed to insert entities and relationships into MongoDB: {e}"
            )

        # Step 6 : Update the unparsed documents in the disclosure storage
        try:
            graph_construction_logger.info(
                "GraphConstructionSystem\nUpdating the 'is_parsed' status of documents..."
            )
            update_document_status_tasks = []

            for document in raw_documents:
                current_name = document.get("name", "")
                if current_name not in exclude_documents:
                    update_document_status_tasks.append(
                        self.disclosure_storage.update_document(
                            {"_id": document["_id"]}, {"is_parsed": True}
                        )
                    )
            update_document_status_tasks = await asyncio.gather(
                *update_document_status_tasks
            )
            graph_construction_logger.info(
                f"GraphConstructionSystem\nUpdated the 'is_parsed' status of {len(update_document_status_tasks)} documents."
            )
        except Exception as e:
            graph_construction_logger.error(
                f"GraphConstructionSystem\nError while updating the 'is_parsed' status of documents:{e}"
            )
            raise ValueError(
                f"Failed to update the 'is_parsed' status of documents: {e}"
            )

    async def extract_entities_relationships_from_multiple_documents(
        self,
        ontology: dict,
        source_texts: list,
        source_texts_publish_date: str,
        source_texts_constraints: str,
    ) -> dict:
        all_tasks = []
        num_of_relationships = len(ontology["relationships"])
        num_of_relationships_per_onto = 10

        for source_text in source_texts:
            for i in range(0, num_of_relationships, num_of_relationships_per_onto):
                sliced_ontology = self.get_n_relationships_with_entity_types(
                    ontology=ontology,
                    i=i,
                    k=min(i + num_of_relationships_per_onto, num_of_relationships),
                )
                task = self.agents["EntityRelationshipExtractionAgent"].handle_task(
                    ontology=sliced_ontology,
                    source_text=source_text,
                    source_text_publish_date=source_texts_publish_date,
                    source_text_constraints=source_texts_constraints,
                )
                all_tasks.append(task)

        graph_construction_logger.info(
            f"GraphConstructionSystem\n{len(all_tasks)} coroutines are created to perform extraction."
        )
        results = await asyncio.gather(*all_tasks)
        return results

    async def insert_entities_into_pinecone(self):
        try:
            formatted_entities = []
            entities = await self.entity_storage.read_documents(
                {"inserted_into_vectordb_at": ""}
            )

            if not entities:
                graph_construction_logger.info(
                    "GraphConstructionSystem\nNo entities found. Skipping insertion into Pinecone."
                )
                raise ValueError(f"No entities found.")

            for entity in entities:
                formatted_entities.append(get_formatted_entity_for_vectordb(entity))

            await self.entity_vector_storage.create_vectors_without_namespace(
                formatted_entities
            )

            update_tasks = []

            for entity in entities:
                update_tasks.append(
                    self.entity_storage.update_document(
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
            raise ValueError(f"Failed to insert entities into Pinecone: {e}")

    async def insert_entities_into_neo4j(self):
        try:
            graph_construction_logger.info(
                f"GraphConstructionSystem\nReading entities from MongoDB..."
            )

            raw_entities = await self.entity_storage.read_documents(
                {"inserted_into_graphdb_at": ""}
            )

            if not raw_entities:
                graph_construction_logger.info(
                    f"GraphConstructionSystem\nNo entities that have not been uploaded to Neo4j."
                )
                raise ValueError(f"No entities that have not been uploaded to Neo4j.")

            graph_construction_logger.info(
                f"GraphConstructionSystem\nRead {len(raw_entities)} entity(ies) that have not been uploaded to Neo4j."
            )
        except Exception as e:
            graph_construction_logger.error(
                f"GraphConstructionSystem\nError while reading entities from MongoDB:{e}"
            )
            raise ValueError(f"Failed to read entities from MongoDB: {e}")

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
            raise ValueError(f"Failed to insert entity(ies) into Neo4j: {e}")

        try:
            graph_construction_logger.info(
                f"GraphConstructionSystem\nUpdating {len(raw_entities)} entity(ies) with 'inserted_into_graphdb_at' field."
            )

            update_tasks = []

            for entity in raw_entities:
                update_tasks.append(
                    self.entity_storage.update_document(
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
            raise ValueError(
                f"Failed to update entity(ies) with 'inserted_into_graphdb_at' field: {e}"
            )

    async def insert_relationships_into_neo4j(self):
        try:
            graph_construction_logger.info(
                f"GraphConstructionSystem\nReading relationships from MongoDB..."
            )

            raw_relationships = await self.relationship_storage.read_documents(
                {"inserted_into_graphdb_at": ""}
            )

            if not raw_relationships:
                graph_construction_logger.info(
                    f"GraphConstructionSystem\nNo relationships that have not been uploaded to Neo4j."
                )
                raise ValueError(
                    f"No relationships that have not been uploaded to Neo4j."
                )

            graph_construction_logger.info(
                f"GraphConstructionSystem\nRead {len(raw_relationships)} relationship(s) that have not been uploaded to Neo4j."
            )
        except Exception as e:
            graph_construction_logger.error(
                f"GraphConstructionSystem\nError while reading relationships from MongoDB:{e}"
            )
            raise ValueError(f"Failed to read relationships from MongoDB: {e}")

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
            raise ValueError(f"Failed to insert relationship(s) into Neo4j: {e}")

        try:
            graph_construction_logger.info(
                f"GraphConstructionSystem\nUpdating {len(raw_relationships)} relationship(s) with 'inserted_into_graphdb_at' field."
            )
            update_tasks = []
            for relationship in raw_relationships:
                update_tasks.append(
                    self.relationship_storage.update_document(
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
            raise ValueError(
                f"Failed to update relationship(s) with 'inserted_into_graphdb_at' field: {e}"
            )

    async def deduplicate_entities(self, top_k: int, score_threshold: float):
        i = 0
        while i < 5:
            unchecked_entities = await self.entity_storage.read_documents(
                {"deduplication_info.check_duplicated": False}, limit=1
            )

            if not unchecked_entities:
                break

            entity = unchecked_entities[0]

            similar_results = (
                await self.entity_vector_storage.get_similar_results_no_namespace(
                    query_texts=entity.get("name", ""),
                    top_k=top_k,
                    query_filter={"entity_type": {"$eq": entity.get("type", "")}},
                    score_threshold=score_threshold,
                )
            )

            simplified_similar_results = (
                get_formatted_similar_entities_for_deduplication(
                    get_simplified_similar_entities_list(similar_results)
                )
            )

            graph_construction_logger.info(
                f"GraphConstructionSystem\nTesting deduplication for entity {str(entity.get('_id',''))}：\n{simplified_similar_results} "
            )

            i += 1

    async def get_formatted_similar_results_from_pinecone(
        self,
        query_texts: str | list[str],
        top_k: int,
        query_filter: dict | None = None,
        score_threshold: float = 0.0,
    ):
        return (
            await self.entity_vector_storage.get_formatted_similar_results_no_namespace(
                query_texts=query_texts,
                top_k=top_k,
                query_filter=query_filter,
                score_threshold=score_threshold,
            )
        )
