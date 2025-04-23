import logging

from ..prompts import PROMPT

from ..util import get_formatted_openai_response, get_ontology_for_query

from ..base import BaseAgent, BaseMultiAgentSystem

front_agent_logger = logging.getLogger("front-agent")
        
class FrontAgent(BaseAgent):
    """
    An agent responsible for validating queries.
    """
    def handle_task(self, task_data: str):
        formatted_ontology = get_ontology_for_query(self.agent_system.ontology)
        system_prompt = PROMPT["QUERY_VALIDATION"].format(ontology=formatted_ontology)
        
        front_agent_logger.debug(f"System prompt: {system_prompt}")

        try:
            response = self.openai_client.responses.create(
                model="o4-mini",
                input=[
                    {"role": "developer", "content": system_prompt},
                    {"role": "user", "content": task_data},
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

class GraphQuerySystem(BaseMultiAgentSystem):
    def __init__(self, ontology: dict):
        super().__init__(
            {
                "FrontAgent": FrontAgent("FrontAgent")
            }
        )
        self.ontology = ontology
    
    def handle_request(self, request_data: str):
        # Start with the first agent (FrontAgent)
        return self.agents["FrontAgent"].handle_task(request_data)



        