import json


def get_formatted_decomposed_request(data: dict) -> str:
    output = ["Decomposed Request:"]
    for i, req in enumerate(data.get("requests", []), start=1):
        output.append(f"  Sub-request {i}: {req['sub_request']}")
        output.append(f"  Validated entities:")
        for j, entity in enumerate(req.get("validated_entities", []), start=1):
            output.append(f"    {j}. {entity}")
        output.append("")
    return "\n".join(output).strip()


def get_formatted_validated_entities(validated_entities: list[str]):
    output = ["Validated Entities:"]
    for i, entity in enumerate(validated_entities, start=1):
        output.append(f"  {i}. {entity}")
    return "\n".join(output)


def get_formatted_cypher(query: str, params: dict) -> str:
    formatted = query
    for key, value in params.items():
        if isinstance(value, str):
            value_repr = f"'{value}'"
        else:
            value_repr = str(value)
        formatted = formatted.replace(f"${key}", value_repr)
    return formatted


def get_formatted_cypher_retrieval_result(data: list[dict]):

    return "\n".join(
        (json.dumps(item, ensure_ascii=False) if isinstance(item, dict) else str(item))
        for item in data
    )


def get_formatted_input_for_query_agent(type: str, payload: dict):
    output = []
    if type == "QUERY_GENERATION":
        output.append(f"User request: {payload['user_request']}")
        output.append(get_formatted_validated_entities(payload["validated_entities"]))
    elif type == "RETRIEVAL_RESULT_EVALUATION":
        output.append(f"Retrieval result: {payload['retrieval_result']}")
        output.append(f"Cypher query used: {payload['cypher_query']}")
        output.append(f"Note from Text2CypherAgent: {payload['note']}")
    elif type == "REPORT_GENERATION":
        output.append(
            f"Regardless of the retrieval result below, you must generate a final response; you are not allowed to perform any evaluations anymore."
        )
        output.append(f"Retrieval result: {payload['retrieval_result']}")
        output.append(f"Cypher query used: {payload['cypher_query']}")
        output.append(f"Note from Text2CypherAgent: {payload['note']}")
    return "\n".join(output)
