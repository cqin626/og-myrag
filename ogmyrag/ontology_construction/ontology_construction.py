from __future__ import annotations

import logging
from ..prompts import PROMPT
from ..llm import OpenAIAsyncClient
from ..util import get_formatted_ontology, get_formatted_openai_response, get_clean_json
from ..storage import AsyncMongoDBStorage
from motor.motor_asyncio import AsyncIOMotorClient

from ..base import BaseAgent, BaseMultiAgentSystem, MongoStorageConfig, BaseLLMClient
from .ontology_construction_util import (
    get_new_version,
    get_formatted_ontology_entry_for_db,
    get_formatted_ontology_evaluation_report_entry_for_db,
    get_formatted_ontology_evaluation_report,
)

ontology_construction_logger = logging.getLogger("ontology_construction")


class OntologyConstructionAgent(BaseAgent):
    """
    An agent responsible for constructing ontology based on source text.
    """

    def __init__(self, agent_name: str, agent_config: dict):
        super().__init__(agent_name=agent_name, agent_config=agent_config)

    async def handle_task(self, **kwargs) -> str:
        """
        Parameters:
           source_text (str): The source text to parse.
           source_text_constraints (str): The constraints while parsing source text.
           ontology (dict): The existing ontology.
        """
        ontology_construction_logger.info(f"OntologyConstructionAgent is called")

        system_prompt = PROMPT["ONTOLOGY_CONSTRUCTION"].format(
            ontology=get_formatted_ontology(data=kwargs.get("ontology", {}) or {}),
            ontology_purpose=self.agent_system.ontology_purpose,
        )
        ontology_construction_logger.debug(f"System Prompt:\n\n{system_prompt}")

        source_text = "Source text:\n" + kwargs.get("source_text", "NA") or "NA"
        source_text_constraints = kwargs.get("source_text_constraints", "") or ""
        user_prompt = source_text_constraints + "\n\n" + source_text
        ontology_construction_logger.debug(f"User Prompt:\n\n{user_prompt}")

        ontology_construction_logger.debug(
            f"OntologyConstructionAgent\nAgent configuration used:\n{str(self.agent_config)}"
        )

        response = await self.agent_system.llm_client.fetch_response(
            system_prompt=system_prompt, user_prompt=user_prompt, **self.agent_config
        )
        ontology_construction_logger.info(
            f"OntologyConstructionAgent\nOntology construction response details:\n{get_formatted_openai_response(response)}"
        )
        ontology_construction_logger.info(
            f"OntologyConstructionAgent\nOntology construction output text:\n{get_formatted_ontology(get_clean_json(response.output_text))}"
        )
        return get_clean_json(response.output_text)


class OntologyEvaluationAgent(BaseAgent):
    """
    An agent responsible for evaluating the ontology.
    """

    def __init__(self, agent_name: str, agent_config: dict):
        super().__init__(agent_name=agent_name, agent_config=agent_config)

    async def handle_task(self, **kwargs) -> str:
        """
        Parameters:
          ontology (dict): The existing ontology.
        """
        ontology_construction_logger.info(f"OntologyEvaluationAgent is called")

        system_prompt = PROMPT["ONTOLOGY_EVALUATION"].format(
            ontology_purpose=self.agent_system.ontology_purpose
        )
        ontology_construction_logger.debug(f"System Prompt:\n\n{system_prompt}")

        user_prompt = get_formatted_ontology(data=kwargs.get("ontology", {}) or {})
        ontology_construction_logger.debug(f"User Prompt:\n\n{user_prompt}")

        ontology_construction_logger.debug(
            f"OntologyEvaluationAgent\nAgent configuration used:\n{str(self.agent_config)}"
        )

        response = await self.agent_system.llm_client.fetch_response(
            system_prompt=system_prompt, user_prompt=user_prompt, **self.agent_config
        )
        ontology_construction_logger.info(
            f"OntologyEvaluationAgent\nOntology evaluation response details:\n{get_formatted_openai_response(response)}"
        )

        return get_clean_json(response.output_text)


class OntologyEnhancementAgent(BaseAgent):
    """
    An agent responsible for enhancing the ontology.
    """

    def __init__(self, agent_name: str, agent_config: dict):
        super().__init__(agent_name=agent_name, agent_config=agent_config)

    async def handle_task(self, **kwargs) -> str:
        """
        Parameters:
          ontology (dict): The existing ontology.
          evaluation_feedback (str): The evaluation feedback on the ontology
        """
        ontology_construction_logger.info(f"OntologyEnhancementAgent is called")

        system_prompt = PROMPT["ONTOLOGY_ENHANCEMENET"].format(
            ontology_purpose=self.agent_system.ontology_purpose
        )
        ontology_construction_logger.debug(f"System Prompt:\n\n{system_prompt}")

        evaluation_feedback = kwargs.get("evaluation_feedback", "")
        formatted_ontology = "Current ontology:\n" + get_formatted_ontology(
            data=kwargs.get("ontology", {}) or {}
        )
        user_prompt = evaluation_feedback + "\n" + formatted_ontology
        ontology_construction_logger.debug(f"User Prompt:\n\n{user_prompt}")

        ontology_construction_logger.debug(
            f"OntologyEnhancementAgent\nAgent configuration used:\n{str(self.agent_config)}"
        )

        response = await self.agent_system.llm_client.fetch_response(
            system_prompt=system_prompt, user_prompt=user_prompt, **self.agent_config
        )

        ontology_construction_logger.info(
            f"OntologyEnhancementAgent\nOntology enhancement response details:\n{get_formatted_openai_response(response)}"
        )

        return get_clean_json(response.output_text)


class OntologyConstructionSystem(BaseMultiAgentSystem):
    def __init__(
        self,
        mongo_client: AsyncIOMotorClient,
        ontology_purpose: str,
        ontology_config: MongoStorageConfig,
        ontology_evaluation_config: MongoStorageConfig,
        llm_client: BaseLLMClient,
        agent_configs: dict[str, dict],
    ):
        super().__init__(
            {
                "OntologyConstructionAgent": OntologyConstructionAgent(
                    agent_name="OntologyConstructionAgent",
                    agent_config=agent_configs["OntologyConstructionAgent"],
                ),
                "OntologyEvaluationAgent": OntologyEvaluationAgent(
                    agent_name="OntologyEvaluationAgent",
                    agent_config=agent_configs["OntologyEvaluationAgent"],
                ),
                "OntologyEnhancementAgent": OntologyEnhancementAgent(
                    agent_name="OntologyEnhancementAgent",
                    agent_config=agent_configs["OntologyEnhancementAgent"],
                ),
            }
        )
        try:
            self.ontology_config = ontology_config
            self.ontology_evaluation_config = ontology_evaluation_config
            self.mongo_storage = AsyncMongoDBStorage(mongo_client)
            self.ontology_purpose = ontology_purpose
            self.llm_client = llm_client
            self.agent_configs = agent_configs
        except Exception as e:
            ontology_construction_logger.error(f"OntologyConstructionSystem: {e}")
            raise

    async def extend_ontology(
        self,
        source_text: str,
        source_text_constraints: str,
    ):
        # Step 1: Fetch the latest ontology and its version
        current_onto = await self.get_current_onto()
        current_onto_version = await self.get_current_onto_version()

        # Step 2: Call construction agent
        construction_response = await self.agents[
            "OntologyConstructionAgent"
        ].handle_task(
            source_text=source_text,
            source_text_constraints=source_text_constraints,
            ontology=current_onto,
        )
        if not construction_response:
            ontology_construction_logger.error(
                "Ontology construction returned no output."
            )
            return

        # Step 3: Upload changes to mongodb
        async with self.mongo_storage.with_transaction() as session:

            # Step 3.1 Mark the 'is_latest' of current ontology to false
            await self.mongo_storage.get_database(
                self.ontology_config["database_name"]
            ).get_collection(self.ontology_config["collection_name"]).update_document(
                query={"is_latest": True},
                update_data={"is_latest": False},
                session=session,
            )

            # Step 3.2 Prepare the ontology entry to be uploaded
            modifications = []

            new_entities = construction_response.pop("entities", {})
            new_relationships = construction_response.pop("relationships", {})

            current_onto["entities"].update(new_entities)
            current_onto["relationships"].update(new_relationships)

            for entity_name in new_entities:
                modifications.append(
                    {
                        "modification_made": f"Added {entity_name}",
                    }
                )
            for rel_name in new_relationships:
                modifications.append(
                    {
                        "modification_made": f"Added {rel_name}",
                    }
                )

            new_version = get_new_version(
                current_version=current_onto_version, update_type="PATCH"
            )
            new_ontology_entry = get_formatted_ontology_entry_for_db(
                ontology=current_onto,
                model=self.agent_configs["OntologyConstructionAgent"]["model"],
                purpose=self.ontology_purpose,
                version=new_version,
                modification_type="EXTENSION",
                modifications=modifications,
                note=construction_response["note"],
            )

            # Step 3.3 Upload the newly constructed ontology entry
            await self.mongo_storage.get_database(
                self.ontology_config["database_name"]
            ).get_collection(self.ontology_config["collection_name"]).create_document(
                data=new_ontology_entry, session=session
            )

            ontology_construction_logger.info(
                f"OntologyConstructionSystem\nOntology is updated, current version: {new_version}"
            )

    async def enhance_ontology_via_loop(self):
        """
        Iteration loop that runs up to 5 times.
        - Iteration 1: always run (if problems exist).
        - Iteration 2: always run (if problems exist).
        - Iteration 3: run only if at least 2 problems remain.
        - Iteration 4: run only if at least 3 problems remain.
        - Iteration 5: run only if at least 4 problems remain.
        - Iteration 6: run only if at least 5 problems remain.
        - Iteration 7: run only if at least 6 problems remain (last iteration).
        """
        iteration = 0
        while True:
            ontology_construction_logger.info(
                f"OntologyConstructionSystem:\nEnhancing ontology via loop. Current iteration {iteration + 1}"
            )
            evaluation_report = await self.get_ontology_evaluation_report()
            num_of_issues = len(evaluation_report["evaluation_result"])

            if (
                (iteration <= 1 and num_of_issues >= 0)
                or (iteration == 2 and num_of_issues >= 2)
                or (iteration == 3 and num_of_issues >= 3)
                or (iteration == 4 and num_of_issues >= 4)
                or (iteration == 5 and num_of_issues >= 5)
                or (iteration == 6 and num_of_issues >= 6)
            ):
                await self.enhance_ontology(evaluation_feedback=evaluation_report)
                iteration += 1
            else:
                ontology_construction_logger.info(
                    f"OntologyConstructionSystem:\nStop enhanching ontology via loop. Current iteration {iteration + 1}"
                )
                break

    async def get_ontology_evaluation_report(
        self,
    ):
        """
        Evaluates the latest ontology, stores the evaluation report in MongoDB, and returns the report.
        """
        # Step 1: Fetch the latest ontology and its version
        current_onto = await self.get_current_onto()
        current_onto_version = await self.get_current_onto_version()

        # Step 2: Call construction agent
        evaluation_response = await self.agents["OntologyEvaluationAgent"].handle_task(
            ontology=current_onto,
        )
        if not evaluation_response:
            ontology_construction_logger.error(
                "Ontology evaluation returned no output."
            )
            return

        # Step 3: Upload the evaluation report to mongodb
        async with self.mongo_storage.with_transaction() as session:

            # Step 3.1 Mark the 'is_latest' of current evaluation report entry to false
            await self.mongo_storage.get_database(
                self.ontology_evaluation_config["database_name"]
            ).get_collection(
                self.ontology_evaluation_config["collection_name"]
            ).update_document(
                query={"is_latest": True},
                update_data={"is_latest": False},
                session=session,
            )

            # Step 3.2 Prepare the evaluation report entry to be uploaded
            new_report_entry = get_formatted_ontology_evaluation_report_entry_for_db(
                evaluation_result=evaluation_response["evaluation_result"],
                model=self.agent_configs["OntologyEvaluationAgent"]["model"],
                version=current_onto_version,
                purpose=self.ontology_purpose,
                note=evaluation_response["note"],
            )

            # Step 3.3 Upload the new evaluation report entry
            await self.mongo_storage.get_database(
                self.ontology_evaluation_config["database_name"]
            ).get_collection(
                self.ontology_evaluation_config["collection_name"]
            ).create_document(
                data=new_report_entry, session=session
            )

            ontology_construction_logger.info(
                f"OntologyConstructionSystem\nOntology evaluation report entry is uploaded"
            )

        return evaluation_response

    async def enhance_ontology(self, evaluation_feedback: dict):
        # Step 1: Fetch the latest ontology and its version
        current_onto = await self.get_current_onto()
        current_onto_version = await self.get_current_onto_version()

        # Step 2: Call construction agent
        enhancement_response = await self.agents[
            "OntologyEnhancementAgent"
        ].handle_task(
            evaluation_feedback=get_formatted_ontology_evaluation_report(
                evaluation_feedback
            ),
            ontology=current_onto,
        )
        if not enhancement_response:
            ontology_construction_logger.error(
                "Ontology evaluation returned no output."
            )
            return

        # Step 3: Upload changes to mongodb
        async with self.mongo_storage.with_transaction() as session:

            # Step 3.1 Mark the 'is_latest' of current ontology to false
            await self.mongo_storage.get_database(
                self.ontology_config["database_name"]
            ).get_collection(self.ontology_config["collection_name"]).update_document(
                query={"is_latest": True},
                update_data={"is_latest": False},
                session=session,
            )

            # Step 3.2 Prepare the ontology entry to be uploaded
            new_version = get_new_version(
                current_version=current_onto_version, update_type="PATCH"
            )
            new_ontology_entry = get_formatted_ontology_entry_for_db(
                ontology=enhancement_response["updated_ontology"],
                model=self.agent_configs["OntologyEnhancementAgent"]["model"],
                purpose=self.ontology_purpose,
                version=new_version,
                modification_type="ENHANCEMENT",
                modifications=enhancement_response["modifications"],
                note=enhancement_response["note"],
            )

            # Step 3.3 Upload the newly constructed ontology entry
            await self.mongo_storage.get_database(
                self.ontology_config["database_name"]
            ).get_collection(self.ontology_config["collection_name"]).create_document(
                data=new_ontology_entry, session=session
            )

            ontology_construction_logger.info(
                f"OntologyConstructionSystem\nOntology is updated, current version: {new_version}"
            )

    async def get_current_onto(self) -> dict:
        current_latest_onto = await (
            self.mongo_storage.get_database(self.ontology_config["database_name"])
            .get_collection(self.ontology_config["collection_name"])
            .read_documents({"is_latest": True})
        )
        return (
            current_latest_onto[0].get("ontology", "")
            if current_latest_onto
            else {"entities": {}, "relationships": {}}
        )

    async def get_current_onto_version(self) -> str:
        current_latest_onto = await (
            self.mongo_storage.get_database(self.ontology_config["database_name"])
            .get_collection(self.ontology_config["collection_name"])
            .read_documents({"is_latest": True})
        )
        return (
            current_latest_onto[0].get("version", "1.0.0")
            if current_latest_onto
            else "1.0.0"
        )
