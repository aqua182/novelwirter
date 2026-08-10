from abc import ABC, abstractmethod
from dataclasses import dataclass

from sqlalchemy.orm import Session

from .. import models


@dataclass(frozen=True)
class AgentInstruction:
    """The complete, auditable instruction passed to one controlled agent task."""

    context: str
    prompt: str
    expects_json: bool


class NovelAgent(ABC):
    """A bounded role; agents only prepare instructions and never write user content."""

    name: str
    task_types: frozenset[str]

    def supports(self, task_type: str) -> bool:
        return task_type in self.task_types

    @abstractmethod
    def build_instruction(
        self, db: Session, novel: models.Novel, run: models.AgentRun
    ) -> AgentInstruction:
        raise NotImplementedError


class AgentRegistry:
    """Explicit allow-list for agent roles; it prevents arbitrary task dispatch."""

    def __init__(self, agents: list[NovelAgent]):
        self._agents = agents

    def resolve(self, task_type: str) -> NovelAgent | None:
        return next((agent for agent in self._agents if agent.supports(task_type)), None)
