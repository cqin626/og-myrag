def get_formatted_query_formulation_message(response: dict):
    output = []
    output.append(f"Response type: {response.get('response_type', '')}")

    if response.get("response_type") == "QUERY_FORMULATION":
        for idx, item in enumerate(response.get("response", []), start=1):
            query = item.get("query", "")
            entities = ", ".join(item.get("entities_to_validate", []))
            note = item.get("note", "")
            output.append(
                f"Response {idx}:\n  - Query: {query}\n  - Entities to validate: [{entities}]\n  - Note: {note or 'NA'}"
            )
    elif response.get("response_type") == "FINAL_REPORT":
        for idx, item in enumerate(response.get("response", []), start=1):
            output.append(f"Response {idx}:\n  - {item}")
        output.append(f"Note: {response.get('note', 'NA')}")

    return "\n".join(output)


def get_formatted_text2cypher_message(response: dict):
    output = []
    output.append(f"Response type: {response.get('response_type', '')}")

    for idx, item in enumerate(response.get("response", []), start=1):
        original_query = item.get("original_query", "")
        cypher_query = item.get("cypher_query", "")
        parameters = item.get("parameters", {})
        obtained_data = item.get("obtained_data", [])
        note = item.get("note", "")

        output.append(f"Response {idx}:\n")
        output.append(f"  - Original query: {original_query}")
        output.append(f"  - Cypher query: {cypher_query}")

        if parameters:
            output.append(f"  - Parameters:")
            for i, (key, value) in enumerate(parameters.items(), start=1):
                output.append(f"    {i}. {key}: {value}")
        else:
            output.append(f"  - Parameters: NA")

        if obtained_data:
            output.append(f"  - Obtained data:")
            for i, data in enumerate(obtained_data, start=1):
                output.append(f"    {i}. {data}")
        else:
            output.append(f"  - Obtained data: []")

        output.append(f"  - Note: {note or 'NA'}")

    return "\n".join(output)


def get_formatted_decomposed_request(data: dict) -> str:
    output = ["Decomposed Request:"]
    for i, req in enumerate(data.get("requests", []), start=1):
        output.append(f"  Sub-request {i}: {req['sub_request']}")
        output.append(f"  Validated entities:")
        for j, entity in enumerate(req.get("validated_entities", []), start=1):
            output.append(f"    {j}. {entity}")
        output.append("")
    return "\n".join(output).strip()
