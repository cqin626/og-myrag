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
    include_relationships: bool = True
) -> str:
    output_lines = []

    if include_entities:
        entities = data.get("entities", {})
        output_lines.append("Entities:")
        for idx, (entity, details) in enumerate(entities.items(), start=1):
            output_lines.append(f"  {idx}. {entity}")
            if "definition" not in exclude_entity_fields:
                output_lines.append(f"  - definition: {details.get('definition', '')}")
            if "llm-guidance" not in exclude_entity_fields:
                output_lines.append(f"  - llm-guidance: {details.get('llm-guidance', '')}")
            if "is_stable" not in exclude_entity_fields:
                output_lines.append(f"  - is_stable: {details.get('is_stable', '')}")
            if "examples" not in exclude_entity_fields:
                examples = ", ".join(details.get("examples", []))
                output_lines.append(f"  - examples: {examples}")
            output_lines.append("")

    if include_relationships:
        relationships = data.get("relationships", {})
        output_lines.append("Relationships:")
        for idx, (relation, details) in enumerate(relationships.items(), start=1):
            source = details.get("source", "")
            target = details.get("target", "")
            output_lines.append(f"  {idx}. {source} {relation} {target}")
            if "llm-guidance" not in exclude_relationship_fields:
                output_lines.append(f"  - llm-guidance: {details.get('llm-guidance', '')}")
            if "is_stable" not in exclude_relationship_fields:
                output_lines.append(f"  - is_stable: {details.get('is_stable', '')}")
            if "examples" not in exclude_relationship_fields:
                examples = ", ".join(details.get("examples", []))
                output_lines.append(f"  - examples: {examples}")
            output_lines.append("")

    return "\n".join(output_lines) if output_lines else "No content to display."


# def get_formatted_ontology(ontology: dict) -> str:
#     prompt = []

#     prompt.append("  Entities:")
#     for idx, (class_name, class_info) in enumerate(ontology.get("classes", {}).items(), 1):
#         prompt.append(f"    {idx}. {class_name}")
#         prompt.append(f"    - Definition: {class_info.get('high-level definition', '')}")
#         prompt.append(f"    - Note: {class_info.get('llm-guidance', '')}")
#         examples = class_info.get("examples", [])
#         if examples:
#             joined_examples = ", ".join(examples)
#             prompt.append(f"    - Examples: {joined_examples}")
#         prompt.append("")

#     prompt.append("  Relationships:")
#     relationships = ontology.get("axioms", {}).get("relationships", [])
#     for idx, rel in enumerate(relationships, 1):
#         r_type = rel.get("type", "N/A")
#         source = rel.get("source", "N/A")
#         target = rel.get("target", "N/A")
#         note = rel.get("llm-guidance", "")
#         example = rel.get("example", "")
#         prompt.append(f"    {idx}. {source} {r_type} {target}")
#         prompt.append(f"    - Note: {note}")
#         if example:
#             prompt.append(f"    - Examples: {example}")
#         prompt.append("")

#     return "\n".join(prompt)

# def get_ontology_for_query(ontology:dict)-> str:
#     prompt = []

#     prompt.append("  Entities:")
#     for idx, (class_name, class_info) in enumerate(ontology.get("classes", {}).items(), 1):
#         prompt.append(f"    {idx}. {class_name}")
#         prompt.append(f"    - Definition: {class_info.get('high-level definition', '')}")
#         prompt.append(f"    - Guidance given to the agent responsible for entity extraction: {class_info.get('llm-guidance', '')}")
#         examples = class_info.get("examples", [])
#         if examples:
#             joined_examples = ", ".join(examples)
#             prompt.append(f"    - Examples: {joined_examples}")
#         prompt.append("")

#     prompt.append("  Relationships:")
#     relationships = ontology.get("axioms", {}).get("relationships", [])
#     for idx, rel in enumerate(relationships, 1):
#         r_type = rel.get("type", "N/A")
#         source = rel.get("source", "N/A")
#         target = rel.get("target", "N/A")
#         note = rel.get("llm-guidance", "")
#         example = rel.get("example", "")
#         prompt.append(f"    {idx}. {source} {r_type} {target}")
#         prompt.append(f"    - Guidance given to the agent responsible for establishing relationships: {note}")
#         if example:
#             prompt.append(f"    - Examples: {example}")
#         prompt.append("")

#     return "\n".join(prompt)

# def get_ontology_for_text2cypher(ontology:dict)-> str:
#     prompt = []

#     prompt.append("  Entities:")
#     for idx, (class_name, class_info) in enumerate(ontology.get("classes", {}).items(), 1):
#         prompt.append(f"    {idx}. {str(class_name).upper()}")
#         prompt.append(f"    - Definition: {class_info.get('high-level definition', '')}")
#         prompt.append("")

#     prompt.append("  Relationships:")
#     relationships = ontology.get("axioms", {}).get("relationships", [])
#     for idx, rel in enumerate(relationships, 1):
#         r_type = rel.get("type", "N/A")
#         source = rel.get("source", "N/A")
#         target = rel.get("target", "N/A")
#         prompt.append(f"    {idx}. {str(source).upper()} {r_type} {str(target).upper()}")
#         prompt.append("")

#     return "\n".join(prompt)

# def get_ontology_with_only_entities(ontology:dict)-> str:
#     prompt = []

#     prompt.append("  Entities:")
#     for idx, (class_name, class_info) in enumerate(ontology.get("classes", {}).items(), 1):
#         prompt.append(f"    {idx}. {class_name}")
#         prompt.append(f"    - Definition: {class_info.get('high-level definition', '')}")
#         examples = class_info.get("examples", [])
#         if examples:
#             joined_examples = ", ".join(examples)
#             prompt.append(f"    - Examples: {joined_examples}")
#         prompt.append("")

#     return "\n".join(prompt)

def get_formatted_openai_response(response_obj):
    try:
        # Use model_dump() for Pydantic-based objects (OpenAI Python SDK >= 1.0.0)
        response_dict = response_obj.model_dump(exclude_unset=True)
    except AttributeError:
        # Fallback for older SDK versions or non-Pydantic objects
        response_dict = response_obj.to_dict() if hasattr(response_obj, 'to_dict') else vars(response_obj)

    return json.dumps(response_dict, indent=2, sort_keys=False)