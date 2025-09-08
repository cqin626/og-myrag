import asyncio
import json
import re
from functools import wraps
from ..storage import AsyncMongoDBStorage
from ..base import MongoStorageConfig


def limit_concurrency(max_concurrent_tasks: int):
    semaphore = asyncio.Semaphore(max_concurrent_tasks)

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            async with semaphore:
                return await func(*args, **kwargs)

        return wrapper

    return decorator


def get_clean_json(text: str) -> dict:
    # Step 1: Trim whitespace
    text = text.strip()

    # Step 2: Remove markdown code block if present (```json ... ```)
    if text.startswith("```json") or text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    # Step 3: Try to extract valid JSON between first '{' and last '}'
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        json_str = text[start:end]
        return json.loads(json_str)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"[Error] JSON parsing failed: {e}")
        return {}


async def fetch_reports_along_with_constraints(
    async_mongo_storage_reports: AsyncMongoDBStorage,
    company_disclosures_config: MongoStorageConfig,
    constraints_config: MongoStorageConfig,
    from_company: str,
    type: str,
    published_at: str,
):
    """
    Hard-coded due to the repository structure and lack of time.
    Only the file names, the constraint name, and published_at will be fetched (not the actual content)
    """
    to_process = {"files": {}, "constraints": "", "published_at": ""}
    if type == "PROSPECTUS":

        files = (
            await async_mongo_storage_reports.get_database(
                company_disclosures_config["database_name"]
            )
            .get_collection(company_disclosures_config["collection_name"])
            .read_documents(query={"from_company": from_company, "type": "PROSPECTUS"})
        )
        constraints = (
            await async_mongo_storage_reports.get_database(
                constraints_config["database_name"]
            )
            .get_collection(constraints_config["collection_name"])
            .read_documents(query={"from_company": from_company})
        )
        for file in files:
            to_process["files"][file["name"]] = file["content"]

        to_process["constraints"] = (
            "The following key-value pairs aid in interpreting the source text. Apply these mappings when extracting and storing entities and relationships to maintain consistency and accuracy. This means that if your extraction involves translating a key into its representative value—for example, if the key is `CYT` and the value is `Choo Yan Tiee, the Promoter, Specified Shareholder, major shareholder, Executive Director and Managing Director of our Company`—then instead of extracting `CYT` as the entity name, you should extract `Choo Yan Tiee` as the entity name.\n"
            + constraints[0]["content"]
        )

        to_process["published_at"] = files[0]["published_at"]

    elif type == "ANNUAL_REPORT":
        files = (
            await async_mongo_storage_reports.get_database(
                company_disclosures_config["database_name"]
            )
            .get_collection(company_disclosures_config["collection_name"])
            .read_documents(
                query={
                    "from_company": from_company,
                    "type": "ANNUAL_REPORT",
                    "published_at": {"$regex": published_at + "$"},
                }
            )
        )
        for file in files:
            to_process["files"][file["name"]] = file["content"]

        to_process["published_at"] = files[0]["published_at"]

    return to_process
