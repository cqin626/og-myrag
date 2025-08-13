from __future__ import annotations
import os
import inspect
import openai
from typing import Any, TypedDict


class MongoStorageConfig(TypedDict):
    database_name: str
    collection_name: str | None


class PineconeStorageConfig(TypedDict):
    index_name: str
    pinecone_api_key: str
    pinecone_environment: str
    pinecone_cloud: str
    pinecone_metric: str
    pinecone_dimensions: str
    openai_api_key: str

class Neo4jStorageConfig(TypedDict):
    uri: str
    user: str
    password: str


class BaseAgent:
    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.agent_system: BaseMultiAgentSystem = None

        try:
            self.openai_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        except Exception as e:
            raise ValueError(f"Error initializing OpenAI client: {str(e)}")

    def handle_task(self, **kwargs):
        raise NotImplementedError("Agent musk implement handle_task")

    async def call_agent(self, agent_to_call: str, task_data: Any):
        agent = self.agent_system.get_agent(agent_to_call)
        handler = agent.handle_task

        if inspect.iscoroutinefunction(handler):
            return await handler(task_data)
        else:
            return handler(task_data)


class BaseMultiAgentSystem:
    def __init__(self, agents: dict[str, BaseAgent]):
        self.agents = agents

        for agent in self.agents.values():
            agent.agent_system = self

    def get_agent(self, agent_name: str) -> BaseAgent:
        return self.agents.get(agent_name)

    def handle_request(self, **kwargs):
        raise NotImplementedError("Agent system musk implement handle_request")
