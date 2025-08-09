def get_formatted_similar_entities(
    query_texts: str | list[str], results: list[dict]
) -> str:
    if isinstance(query_texts, str):
        query_texts = [query_texts]

    output_lines = []

    for query, result_set in zip(query_texts, results):
        output_lines.append(f"Target: {query}")
        output_lines.append("Found:")
        for i, match in enumerate(result_set.get("matches", []), start=1):
            entity_name = match["metadata"].get("entity_name", "Unknown")
            entity_type = match["metadata"].get("entity_type", "Unknown Type")
            score = match.get("score", 0.0)
            output_lines.append(
                f"{i}. {entity_name} ({entity_type}; {score:.9f} similarity score)"
            )
        output_lines.append("")

    return "\n".join(output_lines)
