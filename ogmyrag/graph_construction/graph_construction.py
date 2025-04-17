import logging
import json
from typing import Any

from ..util import get_normalized_string, get_formatted_current_datetime

app_logger = logging.getLogger("og-myrag")

def get_formatted_entities_relationships_parsing_query(
   prompt_template: str,
   ontology: str,
   source_txt_definitions: str,
   tuple_delimeter: str = "<|>"
   ) -> str:
   return prompt_template.format(
    ontology = ontology,
    source_text_definitions = source_txt_definitions,
    tuple_delimiter = tuple_delimeter,
)

def get_formatted_entities_and_relationships(response_string:str):
   formatted_entities = []
   formatted_relationships = []
   try:
      response_data = json.loads(response_string)
      formatted_entities = get_formatted_entities(response_data.get("entities", []))
      formatted_relationships = get_formatted_relationships(response_data.get("relationships", []))
   except json.JSONDecodeError as e:
      app_logger.info("Failed to parse JSON:", e)
   return formatted_entities, formatted_relationships

def get_formatted_company_data(
   document: str,
   document_name: str,
   document_type: str,
   company_name: str,
   timezone_str: str = "Asia/Kuala_Lumpur"
   )-> dict[str, Any]:
   return {
      "name": get_normalized_string(document_name),
      "type": get_normalized_string(document_type),
      "from_company": get_normalized_string(company_name),
      "created_at": get_formatted_current_datetime(timezone_str),
      "is_parsed" : False,
      "content": document
   }

def get_formatted_entities(
   entities: list[str], 
   delimiter: str = "<|>",
   timezone_str: str = "Asia/Kuala_Lumpur"
   ) -> list[dict[str, Any]]:
      app_logger.info(f"Formatting {len(entities)} entity(ies) with delimiter '{delimiter}'")
      
      formatted_entities = []
      
      for entity in entities:
         parts = entity.split(delimiter)
         if(len(parts) == 3):
            formatted_entity = get_formatted_entity(
               entity_name = get_normalized_string(parts[1]), 
               entity_type = get_normalized_string(parts[0]), 
               entity_description = parts[2].strip(),
               timezone = timezone_str
            )
            formatted_entities.append(formatted_entity)
         else:
            app_logger.error(f"Invalid entity format: {entity}. Expected format: '<entity_type>{delimiter}<entity_name>{delimiter}<entity_description>'.")
            
      return formatted_entities
   
def get_formatted_entity(
   entity_type: str, 
   entity_name: str, 
   entity_description: str,
   timezone: str
   ) -> dict[str, Any]:
      return {
         "name": entity_name,
         "type": entity_type,
         "description": entity_description,
         "created_at": get_formatted_current_datetime(timezone),
         "last_modified_at": get_formatted_current_datetime(timezone),
         "inserted_into_vectordb_at": "",
         "inserted_into_graphdb_at": "",
      }
      
      
def get_formatted_relationships(
   relationships: list[str], 
   delimiter: str = "<|>",
   timezone_str: str = "Asia/Kuala_Lumpur"
   ) -> list[dict[str, Any]]:
      app_logger.info(f"Formatting {len(relationships)} relationship(s) with delimiter '{delimiter}'")
      
      formatted_relationships = []
      
      for relationship in relationships:
         parts = relationship.split(delimiter)
         if(len(parts) == 4):
            formatted_relationship = get_formatted_relationship(
               relationship_type = parts[2].strip(), 
               relationship_source = get_normalized_string(parts[0]), 
               relationship_target = get_normalized_string(parts[1]),
               relationship_description = parts[3].strip(),
               timezone = timezone_str
            )
            formatted_relationships.append(formatted_relationship)
         else:
            app_logger.error(f"Invalid relationship format: {relationship}. Expected format: '<relationship_source>{delimiter}<relationship_target>{delimiter}<relationship_type>{delimiter}<relationship_description>'.")
            
      return formatted_relationships
   
def get_formatted_relationship(
   relationship_type: str, 
   relationship_source: str, 
   relationship_target: str, 
   relationship_description: str,
   timezone: str
   ) -> dict[str, Any]:
      return {
         "type": relationship_type,
         "source": relationship_source,
         "target": relationship_target,
         "description": relationship_description,
         "created_at": get_formatted_current_datetime(timezone),
         "last_modified_at": get_formatted_current_datetime(timezone),
         "inserted_into_graphdb_at": "",
      }

def get_formatted_entity_for_vectordb(
   entity: dict[str, Any], 
   timezone="Asia/Kuala_Lumpur"
   ) -> dict[str, Any]:
   return {
      "id": str(entity["_id"]),
      "name": entity["name"], 
      "namespace": entity["type"],
      "metadata": {
         "entity_name": entity["name"],
         "description": entity["description"],
         "created_at": get_formatted_current_datetime(timezone),
         "last_modified_at": get_formatted_current_datetime(timezone),
      }
   }

def get_formatted_entity_for_graphdb(
   entity: dict[str, Any], 
   timezone="Asia/Kuala_Lumpur"
) -> dict[str, Any]:
   return {
      "id": str(entity["_id"]),
      "name": entity["name"], 
      "description": entity["description"],
      "created_at": get_formatted_current_datetime(timezone),
      "last_modified_at": get_formatted_current_datetime(timezone),
   }
   
def get_formatted_relationship_for_graphdb(
   relationship: dict[str, Any], 
   timezone="Asia/Kuala_Lumpur"
) -> dict[str, Any]:
   return {
      "source_id": relationship["source_entity_id"], 
      "target_id": relationship["target_entity_id"],
      "type": relationship["type"],
      "properties": {
         "id": str(relationship["_id"]),
         "source_entity_name": relationship["source"],
         "target_entity_name": relationship["target"],
         "description": relationship["description"],
         "created_at": get_formatted_current_datetime(timezone),
         "last_modified_at": get_formatted_current_datetime(timezone),
      },
  
   }