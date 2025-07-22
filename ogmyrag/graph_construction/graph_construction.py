from __future__ import annotations

import logging
import asyncio

from bson import ObjectId
from collections import defaultdict

from ..prompts import PROMPT
from ..llm import fetch_responses_openai
from ..util import (
    get_formatted_ontology,
    get_formatted_openai_response,
    get_clean_json,
    get_formatted_current_datetime,
)
from ..storage import MongoDBStorage, PineconeStorage, Neo4jStorage

from ..base import (
    BaseAgent,
    BaseMultiAgentSystem,
    MongoStorageConfig,
    PineconeStorageConfig,
    Neo4jStorageConfig,
)

from .graph_construction_util import (
    get_formatted_entities_and_relationships_for_db,
    get_formatted_entities_for_display,
    get_formatted_relationships_for_display,
    get_formatted_entity_for_vectordb,
    get_formatted_entity_for_graphdb,
    get_formatted_relationship_for_graphdb,
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
            exclude_entity_fields=["is_stable"],
            exclude_relationship_fields=["is_stable"],
        )

        system_prompt = PROMPT["ENTITIES_RELATIONSHIPS_PARSING"].format(
            ontology=formatted_ontology,
            document_publish_date=kwargs.get("source_text_publish_date", "NA") or "NA",
            document_constraints=kwargs.get("source_text_constraints", "NA") or "NA",
        )

        #   graph_construction_logger.debug(f"System Prompt:\n\n{system_prompt}")

        graph_construction_logger.info(f"EntityRelatonshipExtractionAgent is called")

        try:
            response = await fetch_responses_openai(
                model="o4-mini",
                system_prompt=system_prompt,
                user_prompt=kwargs.get("source_text", "NA") or "NA",
                text={"format": {"type": "text"}},
                reasoning={"effort": "medium"},
                max_output_tokens=100000,
                tools=[],
            )
            graph_construction_logger.info(
                f"EntityRelatonshipExtractionAgent\nEntity-relationship extraction response details:\n{get_formatted_openai_response(response)}"
            )

            return response.output_text
        except Exception as e:
            graph_construction_logger.error(
                f"EntityRelatonshipExtractionAgent\nEntity-relationship extraction failed: {str(e)}"
            )
            return ""

    def get_n_relationships_with_entity_types(ontology: dict, i: int, k: int):
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


class EntityRelationshipMergerAgent(BaseAgent):
    """
    An agent responsible for merging entities and relationships.
    """

    async def handle_task(self, **kwargs) -> str:
        """
        Parameters:
           entities (list): The entitites.
           relationships (list): The relationships.
        """
        system_prompt = PROMPT["ENTITY_RELATIONSHIP_MERGER"]

        formatted_entities_relationships = []
        formattted_entities = get_formatted_entities_for_display(
            kwargs.get("entities", []) or []
        )
        formattted_relationships = get_formatted_relationships_for_display(
            kwargs.get("relationships", []) or []
        )

        formatted_entities_relationships.append("Entities:")
        formatted_entities_relationships.append(formattted_entities)
        formatted_entities_relationships.append("Relationships:")
        formatted_entities_relationships.append(formattted_relationships)
        formatted_entities_relationships = "\n".join(formatted_entities_relationships)

        graph_construction_logger.info(
            f"GraphConstructionSystem\nEntities and relationships read from MongoDB:\n{formatted_entities_relationships}"
        )

        #   graph_construction_logger.debug(f"System Prompt:\n\n{system_prompt}")

        graph_construction_logger.info(f"EntityRelationshipMergerAgent is called")

        try:
            response = await fetch_responses_openai(
                model="o4-mini",
                system_prompt=system_prompt,
                user_prompt=formatted_entities_relationships,
                text={"format": {"type": "text"}},
                reasoning={"effort": "medium"},
                max_output_tokens=100000,
                tools=[],
            )
            graph_construction_logger.info(
                f"EntityRelationshipMergerAgent\nEntity-relationship merger response details:\n{get_formatted_openai_response(response)}"
            )

            return response.output_text
        except Exception as e:
            graph_construction_logger.error(
                f"EntityRelationshipMergerAgent\nEntity-relationship merger failed: {str(e)}"
            )
            return ""


class GraphConstructionSystem(BaseMultiAgentSystem):
    def __init__(
        self,
        ontology_config: MongoStorageConfig,
        disclosure_config: MongoStorageConfig,
        entity_config: MongoStorageConfig,
        relationship_config: MongoStorageConfig,
      #   entity_vector_config: PineconeStorageConfig,
      #   graphdb_config: Neo4jStorageConfig,
    ):
        super().__init__(
            {
                "EntityRelationshipExtractionAgent": EntityRelationshipExtractionAgent(
                    "EntityRelationshipExtractionAgent"
                ),
                "EntityRelationshipMergerAgent": EntityRelationshipMergerAgent(
                    "EntityRelationshipMergerAgent"
                ),
            }
        )

        try:
            self.onto_storage = MongoDBStorage(ontology_config["connection_uri"])
            self.onto_storage.use_database(ontology_config["database_name"])
            self.onto_storage.use_collection(ontology_config["collection_name"])

            self.disclosure_storage = MongoDBStorage(
                disclosure_config["connection_uri"]
            )
            self.disclosure_storage.use_database(disclosure_config["database_name"])
            self.disclosure_storage.use_collection(disclosure_config["collection_name"])

            self.entity_storage = MongoDBStorage(entity_config["connection_uri"])
            self.entity_storage.use_database(entity_config["database_name"])
            self.entity_storage.use_collection(entity_config["collection_name"])

            self.relationship_storage = MongoDBStorage(
                relationship_config["connection_uri"]
            )
            self.relationship_storage.use_database(relationship_config["database_name"])
            self.relationship_storage.use_collection(
                relationship_config["collection_name"]
            )

            # self.entity_vector_storage = PineconeStorage(**entity_vector_config)

            # self.graph_storage = Neo4jStorage(**graphdb_config)

            entities = self.entity_storage.read_documents()
            for entity in entities:
                self.entity_storage.update_document(
                    {"_id": entity["_id"]}, {"inserted_into_graphdb_at": ""}
                )
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
        # Step 1 : Prepare the ontology
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
            formatted_ontology = get_formatted_ontology(
                data=latest_onto,
                exclude_entity_fields=["is_stable"],
                exclude_relationship_fields=["is_stable"],
            )
            graph_construction_logger.info(
                f"GraphConstructionSystem\nOntology used for extraction\n\n{formatted_ontology}"
            )
        except Exception as e:
            graph_construction_logger.error(
                f"GraphConstructionSystem\nError while preparing ontology:{e}"
            )
            raise ValueError(f"Failed to prepare ontology: {e}")

        # Step 2 : Read the constraints from the disclosure storage
        try:
            graph_construction_logger.info(
                "GraphConstructionSystem\nPreparing constraints..."
            )
            constraints = []
            raw_document_constraints = self.disclosure_storage.read_documents(
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
            raw_documents = self.disclosure_storage.read_documents(
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
            tasks = [
                self.agents["EntityRelationshipExtractionAgent"].handle_task(
                    ontology=latest_onto,
                    source_text=doc,
                    source_text_publish_date=published_at,
                    source_text_constraints=formatted_constraints,
                )
                for doc in unparsed_documents
            ]
            extraction_agent_responses = await asyncio.gather(*tasks)
        except Exception as e:
            graph_construction_logger.error(
                f"GraphConstructionSystem\nError while extracting entities and relationships:{e}"
            )
            raise ValueError(f"Failed to extract entities and relationships: {e}")

        # Step 5 : Insert the entities and relationships into MongoDB
        try:
            graph_construction_logger.info(
                "GraphConstructionSystem\nInserting entities and relationships into MongoDB..."
            )
            for response in extraction_agent_responses:
                formatted_entities, formatted_relationships = (
                    get_formatted_entities_and_relationships_for_db(response)
                )
                if formatted_entities:
                    for formatted_entity in formatted_entities:
                        self.entity_storage.create_document(formatted_entity)
                if formatted_relationships:
                    for formatted_relationship in formatted_relationships:
                        self.relationship_storage.create_document(
                            formatted_relationship
                        )
            graph_construction_logger.info(
                f"GraphConstructionSystem\nSuccessfully inserted {len(formatted_entities)} entity(ies) and {len(formatted_relationships)} relationship(s) into MongoDB."
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
            for document in raw_documents:
                current_name = document.get("name", "")
                if current_name not in exclude_documents:
                    self.disclosure_storage.update_document(
                        {"_id": document["_id"]}, {"is_parsed": True}
                    )
                    graph_construction_logger.info(
                        f"GraphConstructionSystem\nUpdated the 'is_parsed' status of {current_name}."
                    )
        except Exception as e:
            graph_construction_logger.error(
                f"GraphConstructionSystem\nError while updating the 'is_parsed' status of documents:{e}"
            )
            raise ValueError(
                f"Failed to update the 'is_parsed' status of documents: {e}"
            )

    async def resolve_duplicated_entities_relationships(self):
        #  Step 1 : Read the entities and relationships from the MongoDB
        try:
            graph_construction_logger.info(
                "GraphConstructionSystem\nReading entities and relationships..."
            )

            entities = self.entity_storage.read_documents({"to_be_deleted": False})
            relationships = self.relationship_storage.read_documents(
                {"to_be_deleted": False}
            )
        except Exception as e:
            graph_construction_logger.error(
                f"GraphConstructionSystem\nError while reading entities and relationships from MongoDB:{e}"
            )
            raise ValueError(
                f"Failed to read entities and relationships from MongoDB: {e}"
            )

        # Step 2 : Calling LLM to merge the entities and relationships
        try:
            graph_construction_logger.info(
                "GraphConstructionSystem\nMerging entities and relationships..."
            )
            if not entities and not relationships:
                graph_construction_logger.info(
                    "GraphConstructionSystem\nNo entities and relationships found. Skipping merging."
                )
                raise ValueError(f"No entities and relationships found.")

            raw_response = await self.agents[
                "EntityRelationshipMergerAgent"
            ].handle_task(entities=entities, relationships=relationships)
            graph_construction_logger.info(
                f"GraphConstructionSystem\nMerged entities and relationships response details:\n{raw_response}"
            )
        except Exception as e:
            graph_construction_logger.error(
                f"GraphConstructionSystem\nError while merging entities and relationships:{e}"
            )
            raise ValueError(f"Failed to merge entities and relationships: {e}")

        # Step 3 : Remove and insert the merged entities and relationships into MongoDB
        try:
            graph_construction_logger.info(
                "GraphConstructionSystem\nUploading merged entities and relationships..."
            )

            merge_response = get_clean_json(raw_response)
            entities_to_be_removed = merge_response.get("entities_to_be_removed", [])
            relationships_to_be_removed = merge_response.get(
                "relationships_to_be_removed", []
            )
            entities_to_be_modified = merge_response.get("entities_to_be_modified", {})
            relationships_to_be_modified = merge_response.get(
                "relationships_to_be_modified", {}
            )

            for entity_id in entities_to_be_removed:
                self.entity_storage.update_document(
                    {"_id": ObjectId(entity_id)}, {"to_be_deleted": True}
                )

            for relationship_id in relationships_to_be_removed:
                self.relationship_storage.update_document(
                    {"_id": ObjectId(relationship_id)}, {"to_be_deleted": True}
                )

            for entity_id, new_description in entities_to_be_modified.items():
                self.entity_storage.update_document(
                    {"_id": ObjectId(entity_id)},
                    {
                        "description": new_description,
                        "last_modified_at": get_formatted_current_datetime(
                            "Asia/Kuala_Lumpur"
                        ),
                    },
                )

            for rel_id, updates in relationships_to_be_modified.items():
                update_fields = {}
                if "description" in updates:
                    update_fields["description"] = updates["description"]
                if "source" in updates:
                    update_fields["source"] = updates["source"]
                if "target" in updates:
                    update_fields["target"] = updates["target"]
                if "valid_date" in updates:
                    update_fields["valid_date"] = updates["valid_date"]
                if "invalid_date" in updates:
                    update_fields["invalid_date"] = updates["invalid_date"]
                if "temporal_note" in updates:
                    update_fields["temporal_note"] = updates["temporal_note"]
                update_fields["last_modified_at"] = get_formatted_current_datetime(
                    "Asia/Kuala_Lumpur"
                )

                self.relationship_storage.update_document(
                    {"_id": ObjectId(rel_id)}, update_fields
                )
            graph_construction_logger.info(
                "GraphConstructionSystem\nSuccessfully updated merged entities and relationships."
            )
        except Exception as e:
            graph_construction_logger.error(
                f"GraphConstructionSystem\nError while uploading merged entities and relationships:{e}"
            )
            raise ValueError(f"Failed to upload merged entities and relationships: {e}")

    async def insert_entities_into_pinecone(self):
        try:
            formatted_entities = []
            entities = self.entity_storage.read_documents(
                {"to_be_deleted": False, "inserted_into_vectordb_at": ""}
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

            for entity in entities:
                self.entity_storage.update_document(
                    {"_id": entity["_id"]},
                    {
                        "inserted_into_vectordb_at": get_formatted_current_datetime(
                            "Asia/Kuala_Lumpur"
                        )
                    },
                )

            graph_construction_logger.info(
                f"GraphConstructionSystem\nUpdated {len(entities)} entity(ies) with inserted_into_vectordb_at field."
            )
        except Exception as e:
            graph_construction_logger.error(
                f"GraphConstructionSystem\nError while inserting entities into Pinecone:{e}"
            )
            raise ValueError(f"Failed to insert entities into Pinecone: {e}")

    def insert_entities_into_neo4j(self):
        try:
            graph_construction_logger.info(
                f"GraphConstructionSystem\nReading entities from MongoDB..."
            )

            raw_entities = self.entity_storage.read_documents(
                {"inserted_into_graphdb_at": "", "to_be_deleted": False}
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
            for entity in raw_entities:
                self.entity_storage.update_document(
                    {"_id": entity["_id"]},
                    {
                        "inserted_into_graphdb_at": get_formatted_current_datetime(
                            "Asia/Kuala_Lumpur"
                        )
                    },
                )
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

    def insert_relationships_into_neo4j(self):
        try:
            graph_construction_logger.info(
                f"GraphConstructionSystem\nReading relationships from MongoDB..."
            )

            raw_relationships = self.relationship_storage.read_documents(
                {"inserted_into_graphdb_at": "", "to_be_deleted": False}
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
                f"GraphConstructionSystem\nSuccessfully inserted {len(raw_relationships)} entity(ies) into Neo4j."
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
            for relationship in raw_relationships:
                self.relationship_storage.update_document(
                    {"_id": relationship["_id"]},
                    {
                        "inserted_into_graphdb_at": get_formatted_current_datetime(
                            "Asia/Kuala_Lumpur"
                        )
                    },
                )
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
