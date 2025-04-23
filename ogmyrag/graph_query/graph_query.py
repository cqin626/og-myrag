import logging
import os
import openai
from typing import Any

from ..prompts import PROMPT

from ..util import get_formatted_openai_response

front_agent_logger = logging.getLogger("front-agent")

class GraphQuerySystem:
    def __init__(self, ontology: str):
        """
        Initialize the GraphQuerySystem with ontology.
        """
        try:
            self.ontology = ontology
            self.openai_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        except Exception as e:
            raise ValueError(f"Failed to initialize GraphQuerySystem: {str(e)}")
       
    def front_agent(self, query:str):
        """
        An agent responsible for validating queries.
        """
        system_prompt = PROMPT["QUERY_VALIDATION"].format(ontology=self.ontology)
        
        # front_agent_logger.debug(f"System prompt: {system_prompt}")

        try:
            response = self.openai_client.responses.create(
                model="o4-mini",
                input=[
                    {"role": "developer", "content": system_prompt},
                    {"role": "user", "content": query},
                ],
                text={
                    "format": {
                        "type": "text"
                    }
                },
                reasoning={
                    "effort": "medium"
                },
                tools=[],
                store=True
            )
            
            front_agent_logger.debug(get_formatted_openai_response(response))
            return response.output_text
                    
        except Exception as e:
            return f"Error: {str(e)}"

    