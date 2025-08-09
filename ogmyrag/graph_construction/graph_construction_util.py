import logging
import json
from bson import ObjectId

from ..util import get_clean_json
from typing import Any

from ..util import get_normalized_string, get_formatted_current_datetime


def get_formatted_entities_and_relationships_for_db(
    response_string: str,
) -> tuple[list, list]:
    try:
        unprocessed_response_data = get_clean_json(response_string)
        response_data = get_entities_relationships_with_updated_ids(
            unprocessed_response_data
        )
        formatted_entities = get_formatted_entities_for_db(
            response_data.get("entities", [])
        )
        formatted_relationships = get_formatted_relationships_for_db(
            response_data.get("relationships", [])
        )

        return formatted_entities, formatted_relationships
    except Exception as e:
        raise ValueError(f"Failed to parse response string: {e}")


def get_formatted_entities_for_db(
    entities: list[dict[str, Any]], timezone: str = "Asia/Kuala_Lumpur"
) -> list[dict[str, Any]]:
    formatted_entities = []
    for entity in entities:
        formatted_entities.append(
            {
                "_id": entity.get("id"),
                "name": entity.get("name", "").strip(),
                "type": entity.get("type", "").strip(),
                "description": entity.get("desc", ""),
                "created_at": get_formatted_current_datetime(timezone),
                "last_modified_at": get_formatted_current_datetime(timezone),
                "inserted_into_vectordb_at": "",
                "inserted_into_graphdb_at": "",
                "deduplication_info": {
                    "check_duplicated": False,
                    "merge_into": None,
                    "is_removed_from_vectordb": False,
                    "is_removed_from_graphdb": False,
                },
            }
        )
    return formatted_entities


def get_formatted_relationships_for_db(
    relationships: list[str], timezone: str = "Asia/Kuala_Lumpur"
) -> list[dict[str, Any]]:
    formatted_relationships = []
    for relationship in relationships:
        formatted_relationships.append(
            {
                "_id": relationship.get("id"),
                "source_id": relationship.get("source_id", ""),
                "target_id": relationship.get("target_id", ""),
                "type": relationship.get("type", "").strip(),
                "description": relationship.get("desc", ""),
                "valid_in": relationship.get("valid_in", []),
                "created_at": get_formatted_current_datetime(timezone),
                "last_modified_at": get_formatted_current_datetime(timezone),
                "inserted_into_graphdb_at": "",
                "deduplication_info": {
                    "check_duplicated": False,
                    "merge_into": None,
                    "is_removed_from_graphdb": False,
                },
            }
        )
    return formatted_relationships


def get_entities_relationships_with_updated_ids(data: dict):
    old_to_new_ids = {}

    # Step 1: Assign new ObjectIds to entities
    for entity in data.get("entities", []):
        new_id = ObjectId()
        old_to_new_ids[entity["id"]] = new_id
        entity["id"] = new_id

    # Step 2: Assign new ObjectIds to relationships and update source/target IDs
    for rel in data.get("relationships", []):
        rel["id"] = ObjectId()
        rel["source_id"] = old_to_new_ids.get(rel["source_id"], rel["source_id"])
        rel["target_id"] = old_to_new_ids.get(rel["target_id"], rel["target_id"])

    # Step 3: Filter out unused entities
    used_entity_ids = set()
    for rel in data.get("relationships", []):
        used_entity_ids.add(rel["source_id"])
        used_entity_ids.add(rel["target_id"])

    data["entities"] = [
        entity for entity in data.get("entities", []) if entity["id"] in used_entity_ids
    ]

    return data


def get_formatted_entity_for_vectordb(
    entity: dict[str, Any], timezone="Asia/Kuala_Lumpur"
) -> dict[str, Any]:
    return {
        "id": str(entity["_id"]),
        "name": entity["name"],
        "metadata": {
            "entity_name": entity["name"],
            "entity_type": entity["type"],
            "description": entity["description"],
            "last_modified_at": get_formatted_current_datetime(timezone),
        },
    }


def get_formatted_entity_for_graphdb(
    entity: dict[str, Any], timezone="Asia/Kuala_Lumpur"
) -> dict[str, Any]:
    return {
        "id": str(entity["_id"]),
        "name": entity["name"],
        "description": entity["description"],
        "last_modified_at": get_formatted_current_datetime(timezone),
    }


def get_formatted_relationship_for_graphdb(
    relationship: dict[str, Any], timezone="Asia/Kuala_Lumpur"
) -> dict[str, Any]:
    return {
        "source_id": str(relationship["source_id"]),
        "target_id": str(relationship["target_id"]),
        "type": relationship["type"],
        "properties": {
            "id": str(relationship["_id"]),
            "description": relationship["description"],
            "last_modified_at": get_formatted_current_datetime(timezone),
            "valid_in": relationship["valid_in"],
        },
    }


def get_simplified_similar_entities_list(results: list[dict]) -> list[dict]:
    """
    Converts Pinecone similarity search results into a simplified list of entity dicts.

    Each dictionary contains:
      - id: vector ID
      - entity_name: value from metadata["entity_name"]
      - entity_type: value from metadata["entity_type"]
      - description: value from metadata["description"]
      - similarity_score: value from match["score"]

    Args:
        results (list[dict]): List of result dicts returned from get_similar_results_no_namespace in pinecone storage.

    Returns:
        list[dict]: Flattened list of entity info dicts.
    """
    simplified = []

    for result in results:
        for match in result.get("matches", []):
            metadata = match.get("metadata", {})
            simplified.append(
                {
                    "id": match.get("id", ""),
                    "entity_name": metadata.get("entity_name", ""),
                    "entity_type": metadata.get("entity_type", ""),
                    "description": metadata.get("description", ""),
                    "similarity_score": match.get("score", 0.0),
                }
            )

    return simplified


def get_formatted_similar_entities_for_deduplication(entities: list[dict]):
    output = "Similar Entities:"
    for i, entity in enumerate(entities, 1):
        output += f"\n{i}. {entity.get('entity_name', '')}"
        output += f"\n- Similarity Score: {entity.get('similarity_score', 0.0)}"
        output += f"\n- Description: {entity.get('description', '')}\n"
    return output.strip()
