import logging
import json

from ..util import get_clean_json
from typing import Any

from ..util import get_normalized_string, get_formatted_current_datetime


def get_formatted_company_data(
    document: str,
    document_name: str,
    document_type: str,
    company_name: str,
    published_at: str,
    timezone_str: str = "Asia/Kuala_Lumpur",
) -> dict[str, Any]:
    return {
        "name": get_normalized_string(document_name),
        "type": get_normalized_string(document_type),
        "from_company": get_normalized_string(company_name),
        "created_at": get_formatted_current_datetime(timezone_str),
        "is_parsed": False,
        "content": document,
        "published_at": published_at,
    }


def get_formatted_entities_and_relationships_for_db(
    response_string: str,
) -> tuple[list, list]:
    try:
        response_data = get_clean_json(response_string)
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
                "name": entity.get("name", "").strip(),
                "type": entity.get("type", "").strip(),
                "description": entity.get("desc", ""),
                "created_at": get_formatted_current_datetime(timezone),
                "last_modified_at": get_formatted_current_datetime(timezone),
                "inserted_into_vectordb_at": "",
                "inserted_into_graphdb_at": "",
                "to_be_deleted": False,
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
                "type": relationship.get("type", "").strip(),
                "source": relationship.get("source", "").strip(),
                "target": relationship.get("target", "").strip(),
                "source_type": relationship.get("source_type", "").strip(),
                "target_type": relationship.get("target_type", "").strip(),
                "description": relationship.get("desc", ""),
                "created_at": get_formatted_current_datetime(timezone),
                "last_modified_at": get_formatted_current_datetime(timezone),
                "inserted_into_graphdb_at": "",
                "to_be_deleted": False,
            }
        )
    return formatted_relationships


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
        "source_name": relationship["source"],
        "target_name": relationship["target"],
        "source_type": relationship["source_type"],
        "target_type": relationship["target_type"],
        "type": relationship["type"],
        "properties": {
            "id": str(relationship["_id"]),
            "description": relationship["description"],
            "last_modified_at": get_formatted_current_datetime(timezone),
        },
    }
