from __future__ import annotations

import logging

from typing import TypedDict
from pymongo import MongoClient

from ..prompts import PROMPT
from ..llm import fetch_responses_openai
from ..util import get_formatted_ontology, get_formatted_openai_response, get_clean_json
from ..storage import MongoDBStorage
from ..base import BaseAgent, BaseMultiAgentSystem, MongoStorageConfig
from .ontology_construction_util import (
    get_new_version,
    get_formatted_ontology_for_db,
)

ontology_construction_logger = logging.getLogger("ontology_construction")


class OntologyConstructionAgent(BaseAgent):
    """
    An agent responsible for constructing ontology based on source text.
    """

    async def handle_task(self, **kwargs) -> str:
        """
        Parameters:
           source_text (str): The source text to parse.
           ontology (dict): The existing ontology.
        """

        system_prompt = PROMPT["ONTOLOGY_CONSTRUCTION"].format(
            current_ontology=get_formatted_ontology(
                data=kwargs.get("ontology", {}) or {}
            ),
            ontology_purpose=self.agent_system.ontology_purpose,
        )
        user_prompt = kwargs.get("source_text", "NA") or "NA"

        ontology_construction_logger.info(f"OntologyConstructionAgent is called")
        #   ontology_construction_logger.debug(f"System Prompt:\n\n{system_prompt}")

        try:
            response = await fetch_responses_openai(
                model="o4-mini",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                text={"format": {"type": "text"}},
                reasoning={"effort": "medium"},
                max_output_tokens=100000,
                tools=[],
            )
            ontology_construction_logger.info(
                f"OntologyConstructionAgent\nOntology construction response details:\n{get_formatted_openai_response(response)}"
            )
            ontology_construction_logger.info(
                f"OntologyConstructionAgent\nOntology construction output text:\n{get_formatted_ontology(get_clean_json(response.output_text))}"
            )
            return response.output_text

        except Exception as e:
            ontology_construction_logger.error(
                f"OntologyConstructionAgent\nOntology construction failed: {str(e)}"
            )
            return ""


class OntologySimplificationAgent(BaseAgent):
    """
    An agent responsible for simplifying the ontology.
    """

    async def handle_task(self, **kwargs) -> str:
        """
        Parameters:
          ontology (dict): The existing ontology.
        """

        system_prompt = PROMPT["ONTOLOGY_SIMPLIFICATION"].format(
            ontology_purpose=self.agent_system.ontology_purpose
        )
        user_prompt = get_formatted_ontology(data=kwargs.get("ontology", {}) or {})

        ontology_construction_logger.info(f"OntologySimplificationAgent is called")
        #   ontology_construction_logger.debug(f"System Prompt:\n\n{system_prompt}")

        try:
            response = await fetch_responses_openai(
                model="o4-mini",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                text={"format": {"type": "text"}},
                reasoning={"effort": "medium"},
                max_output_tokens=100000,
                tools=[],
            )
            ontology_construction_logger.info(
                f"OntologySimplificationAgent\nOntology simplification response details:\n{get_formatted_openai_response(response)}"
            )

            return response.output_text
        except Exception as e:
            ontology_construction_logger.error(
                f"OntologySimplificationAgent\nOntology simplification failed: {str(e)}"
            )
            return ""


class OntologyClarityEnhancementAgent(BaseAgent):
    """
    An agent responsible for enhancing the clarity of the ontology.
    """

    async def handle_task(self, **kwargs) -> str:
        """
        Parameters:
          ontology (dict): The existing ontology.
        """

        system_prompt = PROMPT["ONTOLOGY_CLARITY_ENHANCEMENT"].format(
            ontology_purpose=self.agent_system.ontology_purpose
        )
        user_prompt = get_formatted_ontology(data=kwargs.get("ontology", {}) or {})

        ontology_construction_logger.info(f"OntologyClarityEnhancementAgent is called")
        #   ontology_construction_logger.debug(f"System Prompt:\n\n{system_prompt}")

        try:
            response = await fetch_responses_openai(
                model="o4-mini",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                text={"format": {"type": "text"}},
                reasoning={"effort": "medium"},
                max_output_tokens=100000,
                tools=[],
            )

            ontology_construction_logger.info(
                f"OntologyClarityEnhancementAgent\nOntology clarity enhancement response details:\n{get_formatted_openai_response(response)}"
            )

            return response.output_text
        except Exception as e:
            ontology_construction_logger.error(
                f"OntologyClarityEnhancementAgent\nOntology clarity enhancement failed: {str(e)}"
            )
            return ""


class OntologyConstructionSystem(BaseMultiAgentSystem):
    def __init__(
        self,
        mongo_client: MongoClient,
        ontology_purpose: str,
        ontology_config: MongoStorageConfig,
    ):
        super().__init__(
            {
                "OntologyConstructionAgent": OntologyConstructionAgent(
                    "OntologyConstructionAgent"
                ),
                "OntologySimplificationAgent": OntologySimplificationAgent(
                    "OntologySimplificationAgent"
                ),
                "OntologyClarityEnhancementAgent": OntologyClarityEnhancementAgent(
                    "OntologyClarityEnhancementAgent"
                ),
            }
        )
        try:            
            self.ontology_config=ontology_config
            self.mongo_storage = MongoDBStorage(mongo_client)

            self.ontology_purpose = ontology_purpose
        except Exception as e:
            ontology_construction_logger.error(f"OntologyConstructionSystem: {e}")
            raise ValueError(f"Failed to initialize OntologyConstructionSystem: {e}")

    async def handle_request(self, **kwargs) -> None:
        """
        Parameters:
          source_text (str): Source text to parse.
        """
        source_text = kwargs.get("source_text", "NA") or "NA"

        await self.extend_ontology(source_text=source_text)
        await self.simplify_ontology()
        await self.enhance_ontology_clarity()

    async def extend_ontology(self, source_text: str):
        current_onto = self.get_current_onto()
        current_onto_version = self.get_current_onto_version()

        # Step 1: Call construction agent
        try:
            raw_response = await self.agents["OntologyConstructionAgent"].handle_task(
                source_text=source_text,
                ontology=current_onto,
            )
            if not raw_response:
                raise ValueError("Ontology construction returned no output.")
        except Exception as e:
            raise ValueError(f"Error while constructing ontology: {e}")

        # Step 2: Format response into json
        try:
            response = get_clean_json(raw_response)
            new_entities = response.pop("entities", {})
            new_relationships = response.pop("relationships", {})

        except Exception as e:
            raise ValueError(f"Error while converting ontology to json: {e}")

        # Step 3: Prepare the ontology to be uploaded
        if "entities" not in current_onto:
            current_onto["entities"] = {}

        if "relationships" not in current_onto:
            current_onto["relationships"] = {}

        current_onto["entities"].update(new_entities)
        current_onto["relationships"].update(new_relationships)

        # Step 3.5: Track modifications made
        modification_made = []

        for entity_name in new_entities:
            modification_made.append(f"Added {entity_name}")

        for rel_name in new_relationships:
            modification_made.append(f"Added {rel_name}")

        # Step 4: Upload constructed ontology to db
        try:
            self.mongo_storage.get_database(self.ontology_config["database_name"]).get_collection(self.ontology_config["collection_name"]).update_document({"is_latest": True}, {"is_latest": False})
            self.mongo_storage.get_database(self.ontology_config["database_name"]).get_collection(self.ontology_config["collection_name"]).create_document(
                get_formatted_ontology_for_db(
                    ontology=current_onto,
                    model="o4-mini",
                    purpose=self.ontology_purpose,
                    version=get_new_version(
                        current_version=current_onto_version, update_type="PATCH"
                    ),
                    modification_type="EXTENSION",
                    modification_made=modification_made,
                    modification_rationale=[],
                )
            )
            ontology_construction_logger.info(
                f"OntologyConstructionSystem\nOntology is updated, current version: {self.get_current_onto_version()}"
            )
        except Exception as e:
            raise ValueError(f"Error while uploading ontology: {e}")

    async def simplify_ontology(self):
        current_onto = self.get_current_onto()
        current_onto_version = self.get_current_onto_version()

        # Step 1: Call simplification agent
        try:
            raw_response = await self.agents["OntologySimplificationAgent"].handle_task(
                ontology=current_onto
            )
            if not raw_response:
                raise ValueError("Ontology simplification returned no output.")
        except Exception as e:
            raise ValueError(f"Error while simplifying ontology: {e}")

        # Step 2: Format response into json
        try:
            response = get_clean_json(raw_response)

            updated_ontology = response.get("updated_ontology", {})
            modification_made = response.pop("modification_made", [])
            modification_rationale = response.pop("modification_rationale", [])
            entities = updated_ontology.pop("entities", {})
            relationships = updated_ontology.pop("relationships", {})

        except Exception as e:
            raise ValueError(f"Error while converting ontology to json: {e}")

        # Step 3: Upload simplified ontology to db
        try:
            self.mongo_storage.get_database(self.ontology_config["database_name"]).get_collection(self.ontology_config["collection_name"]).update_document({"is_latest": True}, {"is_latest": False})
            self.mongo_storage.get_database(self.ontology_config["database_name"]).get_collection(self.ontology_config["collection_name"]).create_document(
                get_formatted_ontology_for_db(
                    ontology={"entities": entities, "relationships": relationships},
                    model="o4-mini",
                    purpose=self.ontology_purpose,
                    version=get_new_version(
                        current_version=current_onto_version, update_type="PATCH"
                    ),
                    modification_type="SIMPLIFICATION",
                    modification_made=modification_made,
                    modification_rationale=modification_rationale,
                )
            )
            ontology_construction_logger.info(
                f"OntologyConstructionSystem\nOntology is updated, current version: {self.get_current_onto_version()}"
            )
        except Exception as e:
            raise ValueError(f"Error while uploading ontology: {e}")

    async def enhance_ontology_clarity(self) -> None:
        current_onto = self.get_current_onto()
        current_onto_version = self.get_current_onto_version()

        # Step 1: Call clarity enhancement agent
        try:
            raw_response = await self.agents[
                "OntologyClarityEnhancementAgent"
            ].handle_task(ontology=current_onto)
            if not raw_response:
                raise ValueError("Ontology clarity enhancement returned no output.")
        except Exception as e:
            raise ValueError(f"Error while enhancing ontology: {e}")

        # Step 2: Format response into json
        try:
            response = get_clean_json(raw_response)

            updated_ontology = response.get("updated_ontology", {})
            modification_made = response.pop("modification_made", [])
            modification_rationale = response.pop("modification_rationale", [])
            entities = updated_ontology.pop("entities", {})
            relationships = updated_ontology.pop("relationships", {})

        except Exception as e:
            raise ValueError(f"Error while converting ontology to json: {e}")

        # Step 3: Upload enhanced ontology to db
        try:
            self.mongo_storage.get_database(self.ontology_config["database_name"]).get_collection(self.ontology_config["collection_name"]).update_document({"is_latest": True}, {"is_latest": False})
            self.mongo_storage.get_database(self.ontology_config["database_name"]).get_collection(self.ontology_config["collection_name"]).create_document(
                get_formatted_ontology_for_db(
                    ontology={"entities": entities, "relationships": relationships},
                    model="o4-mini",
                    purpose=self.ontology_purpose,
                    version=get_new_version(
                        current_version=current_onto_version, update_type="PATCH"
                    ),
                    modification_type="CLARITY_ENHANCEMENT",
                    modification_made=modification_made,
                    modification_rationale=modification_rationale,
                )
            )
            ontology_construction_logger.info(
                f"OntologyConstructionSystem\nOntology is updated, current version: {self.get_current_onto_version()}"
            )
        except Exception as e:
            raise ValueError(f"Error while uploading ontology: {e}")

    def get_current_onto(self) -> dict:
        try:
            current_latest_onto = self.mongo_storage.get_database(self.ontology_config["database_name"]).get_collection(self.ontology_config["collection_name"]).read_documents({"is_latest": True})
            return (
                current_latest_onto[0].get("ontology", "")
                if current_latest_onto
                else {}
            )
        except Exception as e:
            ontology_construction_logger.error(
                f"OntologyConstructionSystem\nError getting ontology: {e}"
            )
            return {}

    def get_current_onto_version(self) -> str:
        try:
            current_latest_onto = self.mongo_storage.get_database(self.ontology_config["database_name"]).get_collection(self.ontology_config["collection_name"]).read_documents({"is_latest": True})
            return (
                current_latest_onto[0].get("version", "1.0.0")
                if current_latest_onto
                else "1.0.0"
            )
        except Exception as e:
            ontology_construction_logger.error(
                f"OntologyConstructionSystem\nError getting ontology version: {e}"
            )
            return "1.0.0"
