  
def get_normalized_string(data: str) -> str:
   return data.strip().upper() if data else ""

def get_formatted_report_definitions(definitions: dict) -> str:
    prompt = []

    for i, (key, value) in enumerate(definitions.items(), start=1):
        prompt.append(f"  {i}. {key}: {value}")
        
    return "\n".join(prompt)

def get_formatted_ontology(ontology: dict) -> str:
    prompt = []

    prompt.append("  Entity Classes:")
    for idx, (class_name, class_info) in enumerate(ontology.get("classes", {}).items(), 1):
        prompt.append(f"    {idx}. {class_name}")
        prompt.append(f"    - Definition: {class_info.get('high-level definition', '')}")
        prompt.append(f"    - Note: {class_info.get('llm-guidance', '')}")
        examples = class_info.get("examples", [])
        if examples:
            joined_examples = ", ".join(examples)
            prompt.append(f"    - Examples: {joined_examples}")
        prompt.append("")

    prompt.append("  Relationships:")
    relationships = ontology.get("axioms", {}).get("relationships", [])
    for idx, rel in enumerate(relationships, 1):
        r_type = rel.get("type", "N/A")
        source = rel.get("source", "N/A")
        target = rel.get("target", "N/A")
        note = rel.get("llm-guidance", "")
        example = rel.get("example", "")
        prompt.append(f"    {idx}. {source} {r_type} {target}")
        prompt.append(f"    - Note: {note}")
        if example:
            prompt.append(f"    - Examples: {example}")
        prompt.append("")

    return "\n".join(prompt)