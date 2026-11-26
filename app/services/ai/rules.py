"""Deterministic fallback: no AI, no network. Ports the frontend's cvParser.js."""

from pydantic import BaseModel

from app.services import cv_rules, interview_rules
from app.services.ai.base import LLMProvider


class RuleBasedProvider(LLMProvider):
    name = "rules"

    def generate_json(self, prompt: str, schema: type[BaseModel], **context) -> dict:
        task = context["task"]
        if task == "evaluate":
            return interview_rules.evaluate(
                context["answer"], context["question"], context.get("aliases") or [], context.get("follow_up_below", 55)
            )
        if task == "follow_up":
            return {"question": interview_rules.GENERIC_FOLLOW_UP}
        text, skills = context["text"], context.get("skills") or []
        if task == "cv":
            return cv_rules.parse_cv(text, skills)
        if task == "jd":
            return cv_rules.parse_jd(text, skills, context.get("role_skills"))
        raise ValueError(f"Unknown task: {task}")
