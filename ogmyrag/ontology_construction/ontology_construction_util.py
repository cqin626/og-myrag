from typing import Any
from ..util import get_current_datetime


def get_new_version(current_version: str, update_type: str) -> str:
    major, minor, patch = map(int, current_version.split("."))

    if update_type == "PATCH":
        patch += 1
    elif update_type == "MINOR":
        minor += 1
        patch = 0
    elif update_type == "MAJOR":
        major += 1
        minor = 0
        patch = 0
    else:
        raise ValueError(f"Unknown update_type: {update_type}")

    return f"{major}.{minor}.{patch}"


def get_formatted_cq_for_db(
    cq: dict,
    model: str,
    purpose: str,
    version: str,
    timezone: str = "Asia/Kuala_Lumpur",
) -> dict[str, Any]:
    return {
        "competency_questions": cq,
        "created_at": get_current_datetime(timezone),
        "model_used": model,
        "onto_purpose": purpose,
        "is_latest": True,
        "version": version,
    }


def get_formatted_ontology_entry_for_db(
    ontology: dict,
    model: str,
    purpose: str,
    version: str,
    modification_type: str,
    note: str,
    modifications: list[dict] = [],
    timezone: str = "Asia/Kuala_Lumpur",
) -> dict[str, Any]:
    return {
        "ontology": ontology,
        "onto_purpose": purpose,
        "modifications": {
            "type": modification_type,
            "changes": modifications,
            "note": note,
        },
        "model_used": model,
        "created_at": get_current_datetime(timezone),
        "is_latest": True,
        "version": version,
    }


def get_formatted_ontology_evaluation_report_entry_for_db(
    evaluation_result: list[dict],
    model: str,
    purpose: str,
    version: str,
    note: str,
    timezone: str = "Asia/Kuala_Lumpur",
) -> dict[str, Any]:
    return {
        "evaluation_result": evaluation_result,
        "note": note,
        "onto_purpose": purpose,
        "onto_version": version,
        "model_used": model,
        "created_at": get_current_datetime(timezone),
        "is_latest": True,
    }


def get_formatted_ontology_evaluation_report(data: dict):
    output = []
    output.append("Evaluation Result:")
    if data["evaluation_result"]:
        for i, result in enumerate(data["evaluation_result"], start=1):
            output.append(f"Feedback {i}:")
            output.append(f"  Issue: {result['issue']}")
            output.append(f"  Impact: {result['impact']}")
            output.append(f"  Suggestion: {result['suggestion']}")
            output.append("\n")
    else:
        output.append("NA")
    output.append(f"Note: {data['note']}")
    return "\n".join(output)
