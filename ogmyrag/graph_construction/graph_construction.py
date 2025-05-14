from __future__ import annotations

import logging
import asyncio

from ..prompts import PROMPT
from ..llm import fetch_responses_openai
from ..util import get_formatted_ontology, get_formatted_openai_response
from ..storage import MongoDBStorage

from ..base import (
   BaseAgent, 
   BaseMultiAgentSystem, 
   MongoStorageConfig
)

from .graph_construction_util import (
   get_formatted_entities_and_relationships_for_db
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
           data=kwargs.get("ontology",{}) or {},
           exclude_entity_fields=["is_stable"], 
           exclude_relationship_fields=["is_stable"]
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
                text={
                  "format": {"type": "text"}
                },
                reasoning={
                  "effort": "medium"
                },
                max_output_tokens=100000,
                tools=[],
            )
            graph_construction_logger.info(f"EntityRelatonshipExtractionAgent\nEntity-relationship extraction response details:\n{get_formatted_openai_response(response)}")
            
            return response.output_text
        except Exception as e:
            graph_construction_logger.error(f"EntityRelatonshipExtractionAgent\nEntity-relationship extraction failed: {str(e)}")
            return ""

class GraphConstructionSystem(BaseMultiAgentSystem):
    def __init__(
       self,
       ontology_config: MongoStorageConfig,
       disclosure_config: MongoStorageConfig,
       entity_config: MongoStorageConfig,
       relationship_config: MongoStorageConfig,
      ):
        super().__init__(
            {
               "EntityRelationshipExtractionAgent": EntityRelationshipExtractionAgent("EntityRelationshipExtractionAgent")
            }
        )
        
        try:
         self.onto_storage = MongoDBStorage(ontology_config["connection_uri"])
         self.onto_storage.use_database(ontology_config["database_name"])
         self.onto_storage.use_collection(ontology_config["collection_name"])
         
         self.disclosure_storage = MongoDBStorage(disclosure_config["connection_uri"])
         self.disclosure_storage.use_database(disclosure_config["database_name"])
         self.disclosure_storage.use_collection(disclosure_config["collection_name"])
         
         self.entity_storage = MongoDBStorage(entity_config["connection_uri"])
         self.entity_storage.use_database(entity_config["database_name"])
         self.entity_storage.use_collection(entity_config["collection_name"])
         
         self.relationship_storage = MongoDBStorage(relationship_config["connection_uri"])
         self.relationship_storage.use_database(relationship_config["database_name"])
         self.relationship_storage.use_collection(relationship_config["collection_name"])
      
        except Exception as e:
           graph_construction_logger.error(f"GraphConstructionSystem: {e}")
           raise ValueError(f"Failed to intialize GraphConstructionSystem: {e}")
    
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
           graph_construction_logger.info("GraphConstructionSystem\nPreparing ontology...")
           latest_onto = self.onto_storage.read_documents({"is_latest": True})[0].get("ontology", {}) or {}
           formatted_ontology = get_formatted_ontology(
              data=latest_onto,
              exclude_entity_fields=["is_stable"],
              exclude_relationship_fields=["is_stable"]
            )
           graph_construction_logger.info(f"GraphConstructionSystem\nOntology used for extraction\n\n{formatted_ontology}")
         except Exception as e:
            graph_construction_logger.error(f"GraphConstructionSystem\nError while preparing ontology:{e}")
            raise ValueError(f"Failed to prepare ontology: {e}")
         
         # Step 2 : Read the constraints from the disclosure storage
         try:
            graph_construction_logger.info("GraphConstructionSystem\nPreparing constraints...")
            constraints = []
            raw_document_constraints= self.disclosure_storage.read_documents({
               "from_company": from_company.strip().upper(),
               "type": "CONSTRAINTS",
               "published_at": published_at
            })
            for doc in raw_document_constraints:
               constraints.append(doc.get("content", ""))
            formatted_constraints = "\n".join(constraints)
            graph_construction_logger.info(f"GraphConstructionSystem\nConstraints used for extraction\n\n{formatted_constraints}")
         except Exception as e:
            graph_construction_logger.error(f"GraphConstructionSystem\nError while preparing constraints:{e}")
            raise ValueError(f"Failed to prepare constraints: {e}") 
         
         # Step 3 : Read the unparsed documents from the disclosure storage
         try:
            graph_construction_logger.info("GraphConstructionSystem\nPreparing unparsed documents...")
            unparsed_documents = []
            raw_documents = self.disclosure_storage.read_documents({
               "from_company": from_company.strip().upper(),
               "type": type.strip().upper(),
               "published_at": published_at,
               "is_parsed": False
            })
            for i, doc in enumerate(raw_documents, start=1):
               name = doc.get("name", "")
               if name not in exclude_documents:
                  unparsed_documents.append(doc.get("content", ""))
                  graph_construction_logger.info(f"GraphConstructionSystem\nDocuments to be parsed: {i}. {name}")
         except Exception as e:
            graph_construction_logger.error(f"GraphConstructionSystem\nError while preparing unparsed documents:{e}")
            raise ValueError(f"Failed to prepare unparsed documents: {e}")
         
         # Step 4 : Calling LLM to extract entities and relationships from the documents
         try:
            graph_construction_logger.info("GraphConstructionSystem\nExtracting entities and relationships from unparsed documents...")
            if not unparsed_documents:
               graph_construction_logger.info("GraphConstructionSystem\nNo unparsed documents found. Skipping extraction.")
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
            graph_construction_logger.error(f"GraphConstructionSystem\nError while extracting entities and relationships:{e}")
            raise ValueError(f"Failed to extract entities and relationships: {e}")
        
         # Step 5 : Insert the entities and relationships into MongoDB
         try:
            graph_construction_logger.info("GraphConstructionSystem\nInserting entities and relationships into MongoDB...")
            for response in extraction_agent_responses:
               formatted_entities, formatted_relationships = get_formatted_entities_and_relationships_for_db(response)
               if formatted_entities:
                  for formatted_entity in formatted_entities:
                     self.entity_storage.create_document(formatted_entity)
               if formatted_relationships:
                  for formatted_relationship in formatted_relationships:
                     self.relationship_storage.create_document(formatted_relationship)
            graph_construction_logger.info(f"GraphConstructionSystem\nSuccessfully inserted {len(formatted_entities)} entity(ies) and {len(formatted_relationships)} relationship(s) into MongoDB.")
         except Exception as e:
            graph_construction_logger.error(f"GraphConstructionSystem\nError while inserting entities and relationships into MongoDB:{e}")
            raise ValueError(f"Failed to insert entities and relationships into MongoDB: {e}")

         # Step 6 : Update the unparsed documents in the disclosure storage
         try:
            graph_construction_logger.info("GraphConstructionSystem\nUpdating the 'is_parsed' status of documents...")
            for document in raw_documents:
               current_name = document.get("name", "")
               if current_name not in exclude_documents:
                  self.disclosure_storage.update_document(
                     {"_id": document["_id"]},
                     {"is_parsed": True}
                  )
                  graph_construction_logger.info(f"GraphConstructionSystem\nUpdated the 'is_parsed' status of {current_name}.")
         except Exception as e:
            graph_construction_logger.error(f"GraphConstructionSystem\nError while updating the 'is_parsed' status of documents:{e}")
            raise ValueError(f"Failed to update the 'is_parsed' status of documents: {e}")
    