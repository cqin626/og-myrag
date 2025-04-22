import logging
import os
import openai
from typing import Any

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
       
    def front_agent(self, message: str, history: list[dict[str, Any]]):
        """
        An agent responsible for validating queries.
        """
        messages = [{"role": "system", "content": "You are a helpful AI assistant."}] + history
        messages.append({"role": "user", "content": message})
        
        front_agent_logger.debug(f"Conversation history of front agent: {messages}")

        try:
            stream = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=1.0,
                max_tokens=500,
                stream=True
            )
            
            for chunk in stream:
              if chunk.choices[0].delta.content is not None:
                yield chunk.choices[0].delta.content
                    
        except Exception as e:
            yield f"Error: {str(e)}"

    