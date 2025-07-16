from typing import Any
from ..util import get_formatted_current_datetime


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


def get_formatted_cq_for_display(data: dict):
    output_lines = []

    for personality, tasks in data.items():
        output_lines.append(f"Personality: {personality}")
        for idx, (task, difficulties) in enumerate(tasks.items(), start=1):
            output_lines.append(f"  Task {idx}: {task}")
            for questions in difficulties.values():
                if isinstance(questions, list):
                    for question in questions:
                        output_lines.append(f"    - {question}")
                else:
                    output_lines.append(f"    - {questions}")
        output_lines.append("")

    return "\n".join(output_lines) if output_lines else ""


def get_formatted_feedback_for_display(data: dict):
    output_lines = ["Feedback 1 - Ontology competency evaluation result"]

    competency_eval = data.get("competency_evaluation", {})
    for personality, tasks in competency_eval.items():
        output_lines.append(f"  Personality: {personality}")
        for task, questions in tasks.items():
            output_lines.append(f"    Task: {task}")
            for idx, q in enumerate(questions, 1):
                question = q.get("question", "")
                difficulty = q.get("difficulty", "")
                support = q.get("support", "")
                justification = q.get("justification", "")
                output_lines.append(f"      {idx}. {question}")
                output_lines.append(f'      - Difficulty: "{difficulty}"')
                output_lines.append(f'      - Ontology support: "{support}"')
                output_lines.append(f'      - Justification: "{justification}"')
        output_lines.append("")

    summary = data.get("summary", "")
    output_lines.append(f"Feedback 2 - Ontology structure summary")
    output_lines.append(f"  {summary}")

    return "\n".join(output_lines)


def get_formatted_cq_for_db(
    cq: dict,
    model: str,
    purpose: str,
    version: str,
    timezone: str = "Asia/Kuala_Lumpur",
) -> dict[str, Any]:
    return {
        "competency_questions": cq,
        "created_at": get_formatted_current_datetime(timezone),
        "model_used": model,
        "onto_purpose": purpose,
        "is_latest": True,
        "version": version,
    }


def get_formatted_ontology_for_db(
    ontology: dict,
    model: str,
    purpose: str,
    version: str,
    modification_type: str,
    modification_made: list[str] = [],
    modification_rationale: list[str] = [],
    timezone: str = "Asia/Kuala_Lumpur",
) -> dict[str, Any]:
    return {
        "ontology": ontology,
        "created_at": get_formatted_current_datetime(timezone),
        "model_used": model,
        "onto_purpose": purpose,
        "modification_type": modification_type,
        "modification_made": modification_made,
        "modification_rationale": modification_rationale,
        "is_latest": True,
        "version": version,
    }


def get_formatted_feedback_for_db(
    feedback: dict,
    model: str,
    purpose: str,
    is_handled: bool,
    cq_version: str,
    onto_version: str,
    timezone: str = "Asia/Kuala_Lumpur",
) -> dict[str, Any]:
    return {
        "feedback": feedback,
        "created_at": get_formatted_current_datetime(timezone),
        "model_used": model,
        "onto_purpose": purpose,
        "is_handled": is_handled,
        "evaluated_with_cq_version": cq_version,
        "feedback_for_onto_version": onto_version,
    }
