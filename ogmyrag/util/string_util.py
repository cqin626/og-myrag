import json


def get_normalized_string(data: str) -> str:
    return data.strip().upper() if data else ""


def get_formatted_report_definitions(definitions: dict) -> str:
    prompt = []

    for i, (key, value) in enumerate(definitions.items(), start=1):
        prompt.append(f"  {i}. {key}: {value}")

    return "\n".join(prompt)


def get_sliced_ontology(ontology: dict, i: int, k: int):
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


def get_formatted_ontology(
    data: dict,
    exclude_entity_fields: list[str] = [],
    exclude_relationship_fields: list[str] = [],
    include_entities: bool = True,
    include_relationships: bool = True,
) -> str:
    output_lines = []

    if include_entities:
        entities = data.get("entities", {})
        output_lines.append("Entities:")
        for idx, (entity, details) in enumerate(entities.items(), start=1):
            output_lines.append(f"{idx}. {entity}")
            if "definition" not in exclude_entity_fields:
                output_lines.append(f"- definition: {details.get('definition', '')}")
            if "llm-guidance" not in exclude_entity_fields:
                output_lines.append(
                    f"- llm-guidance: {details.get('llm-guidance', '')}"
                )
            if "examples" not in exclude_entity_fields:
                examples = ", ".join(details.get("examples", []))
                output_lines.append(f"- examples: {examples}")
            output_lines.append("")  # blank line between entities

    if include_relationships:
        relationships = data.get("relationships", {})
        output_lines.append("Relationships:")
        for idx, (relation, details) in enumerate(relationships.items(), start=1):
            output_lines.append(f"{idx}. {relation}")
            output_lines.append(f"- source: {details.get('source', '')}")
            output_lines.append(f"- target: {details.get('target', '')}")
            if "llm-guidance" not in exclude_relationship_fields:
                output_lines.append(
                    f"- llm-guidance: {details.get('llm-guidance', '')}"
                )
            if "examples" not in exclude_relationship_fields:
                examples = ", ".join(details.get("examples", []))
                output_lines.append(f"- examples: {examples}")
            output_lines.append("")  # blank line between relationships

    return "\n".join(output_lines) if output_lines else ""


def get_formatted_entities_and_relationships(data: dict):
    output = ["Entities"]
    for idx, entity in enumerate(data.get("entities", []), start=1):
        output.append(f"{idx}. {entity['name']}")
        output.append(f"- id: {str(entity['id'])}")
        output.append(f"- type: {entity['type']}")
        output.append(f"- desc: {entity['desc']}\n")

    output.append("Relationships:")
    for idx, rel in enumerate(data.get("relationships", []), start=1):
        output.append(f"{idx}. {rel['type']}")
        output.append(f"- id: {str(rel['id'])}")
        output.append(f"- source_id: {str(rel['source_id'])}")
        output.append(f"- target_id: {str(rel['target_id'])}")
        output.append(f"- desc: {rel['desc']}")
        output.append(f"- valid_in: {rel['valid_in']}\n")

    return "\n".join(output)


def get_formatted_openai_response(response_obj):
    try:
        # Use model_dump() for Pydantic-based objects (OpenAI Python SDK >= 1.0.0)
        response_dict = response_obj.model_dump(exclude_unset=True)
    except AttributeError:
        # Fallback for older SDK versions or non-Pydantic objects
        response_dict = (
            response_obj.to_dict()
            if hasattr(response_obj, "to_dict")
            else vars(response_obj)
        )

    return json.dumps(response_dict, indent=2, sort_keys=False)
