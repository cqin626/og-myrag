import logging
import json
from bson import ObjectId

from ..util import get_clean_json, get_current_datetime
from typing import Any

from ..util import get_normalized_string, get_formatted_current_datetime


def get_formatted_entities_and_relationships_for_db(
    data: dict, from_company: str
) -> tuple[list, list]:
    formatted_entities = _get_formatted_entities_for_db(
        entities=data.get("entities", []), from_company=from_company
    )
    formatted_relationships = _get_formatted_relationships_for_db(
        relationships=data.get("relationships", []), from_company=from_company
    )

    return formatted_entities, formatted_relationships


def _get_formatted_entities_for_db(
    entities: list[dict[str, Any]],
    from_company: str,
    timezone: str = "Asia/Kuala_Lumpur",
) -> list[dict[str, Any]]:
    formatted_entities = []
    for entity in entities:
        formatted_entities.append(
            {
                "_id": entity.get("id"),
                "name": entity.get("name", "").strip(),
                "type": entity.get("type", "").strip(),
                "description": [entity.get("desc", "")],
                "originated_from": [from_company],
                "status": "TO_BE_DEDUPLICATED",
                "created_at": get_current_datetime(timezone),
                "last_modified_at": get_current_datetime(timezone),
            }
        )
    return formatted_entities


def _get_formatted_relationships_for_db(
    relationships: list[str], from_company: str, timezone: str = "Asia/Kuala_Lumpur"
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
                "originated_from": [from_company],
                "status": "TO_BE_DEDUPLICATED",
                "created_at": get_current_datetime(timezone),
                "last_modified_at": get_current_datetime(timezone),
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
        rel["source_id"] = old_to_new_ids[rel["source_id"]]
        rel["target_id"] = old_to_new_ids[rel["target_id"]]

    # Step 3: Filter out unused entities
    used_entity_ids = set()
    for rel in data.get("relationships", []):
        used_entity_ids.add(rel["source_id"])
        used_entity_ids.add(rel["target_id"])

    data["entities"] = [
        entity for entity in data.get("entities", []) if entity["id"] in used_entity_ids
    ]

    return data


def get_formatted_entity_cache_for_db(
    entity: dict, timezone: str = "Asia/Kuala_Lumpur"
) -> dict[str, Any]:
    return {
        "_id": entity.get("_id"),
        "name": entity.get("name"),
        "type": entity.get("type"),
        "description": entity.get("description"),
        "last_modified_at": get_current_datetime(timezone),
    }


def get_formatted_entities_deduplication_pending_task(
    from_company: str,
    payload: dict[str, Any],
    timezone: str = "Asia/Kuala_Lumpur",
) -> dict[str, Any]:
    return {
        "from_company": from_company,
        "status": "PENDING",
        "payload": payload,
        "created_at": get_current_datetime(timezone),
    }


def get_formatted_entity_for_vectordb(
    entity: dict[str, Any], timezone="Asia/Kuala_Lumpur"
) -> dict[str, Any]:
    """
    Used for both vector entities cache and actual vector entities storage
    """
    return {
        "id": str(entity["_id"]),
        "name": entity["name"],
        "metadata": {
            "name": entity["name"],
            "type": entity["type"],
            "description": entity["description"],
        },
    }


def get_formatted_entity_details_for_deduplication(
    entity: dict, entity_label: str, associated_relationships: list
):
    output = []

    output.append(f"{entity_label}: ")
    output.append(f"- Entity Name: {entity['name']}")
    output.append(f"- Entity Type: {entity['type']}")
    output.append(f"- Entity Description(s): {entity['description']}")
    output.append(f"- Associated Relationships:")

    for i, relationship in enumerate(associated_relationships, start=1):
        output.append(f"  {i}. {relationship.get('description', '')}")

    return "\n".join(output)


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


# def get_simplified_similar_entities_list(results: list[dict]) -> list[dict]:
#     """
#     Converts Pinecone similarity search results into a simplified list of entity dicts.

#     Each dictionary contains:
#       - id: vector ID
#       - entity_name: value from metadata["entity_name"]
#       - entity_type: value from metadata["entity_type"]
#       - description: value from metadata["description"]
#       - similarity_score: value from match["score"]

#     Args:
#         results (list[dict]): List of result dicts returned from get_similar_results in pinecone storage.

#     Returns:
#         list[dict]: Flattened list of entity info dicts.
#     """
#     simplified = []

#     for result in results:
#         for match in result.get("matches", []):
#             metadata = match.get("metadata", {})
#             simplified.append(
#                 {
#                     "id": match.get("id", ""),
#                     "entity_name": metadata.get("entity_name", ""),
#                     "entity_type": metadata.get("entity_type", ""),
#                     "description": metadata.get("description", ""),
#                     "similarity_score": match.get("score", 0.0),
#                 }
#             )

#     return simplified
