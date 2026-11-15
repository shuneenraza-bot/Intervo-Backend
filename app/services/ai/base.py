"""The provider interface. Providers return plain dicts; the caller validates them."""

from abc import ABC, abstractmethod

from pydantic import BaseModel


class AIUnavailable(Exception):
    """The provider can't answer right now (no key, quota, timeout, network). Retrying won't help."""


class InvalidAIResponse(Exception):
    """The provider answered, but not with usable JSON. One retry is worth trying."""


class LLMProvider(ABC):
    name: str

    @abstractmethod
    def generate_json(self, prompt: str, schema: type[BaseModel], **context) -> dict:
        """Returns a dict that should validate against `schema`.

        `context` carries what a non-AI provider needs instead of a prompt: task="cv"|"jd",
        text (the full text), skills (the skill library), role_skills.
        """
