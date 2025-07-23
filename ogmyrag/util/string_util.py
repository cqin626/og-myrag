import json


def get_normalized_string(data: str) -> str:
    return data.strip().upper() if data else ""


def get_formatted_report_definitions(definitions: dict) -> str:
    prompt = []

    for i, (key, value) in enumerate(definitions.items(), start=1):
        prompt.append(f"  {i}. {key}: {value}")

    return "\n".join(prompt)


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


def get_formatted_entities_and_relationships(json_string):
    data = json.loads(json_string)

    output = ["Entities"]
    for idx, entity in enumerate(data.get("entities", []), start=1):
        output.append(f"{idx}. {entity['name']}")
        output.append(f"- type: {entity['type']}")
        output.append(f"- desc: {entity['desc']}\n")

    output.append("Relationships:")
    for idx, rel in enumerate(data.get("relationships", []), start=1):
        output.append(f"{idx}. {rel['type']}")
        output.append(f"- source: {rel['source']}")
        output.append(f"- source_type: {rel['source_type']}")
        output.append(f"- target: {rel['target']}")
        output.append(f"- target_type: {rel['target_type']}")
        output.append(f"- desc: {rel['desc']}\n")

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
