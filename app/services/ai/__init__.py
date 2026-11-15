"""AI provider layer: pick a provider, validate its output, fall back to rules, never raise."""

import logging
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.config import settings
from app.services.ai.base import AIUnavailable, InvalidAIResponse, LLMProvider
from app.services.ai.rules import RuleBasedProvider

log = logging.getLogger("intervo.ai")
T = TypeVar("T", bound=BaseModel)

__all__ = ["AIUnavailable", "InvalidAIResponse", "LLMProvider", "RuleBasedProvider", "get_provider", "run_json_task"]


def get_provider() -> LLMProvider:
    """The provider chosen by AI_PROVIDER. Anything that can't be set up becomes the rules provider."""
    if settings.ai_provider.strip().lower() == "gemini":
        try:
            from app.services.ai.gemini import GeminiProvider

            return GeminiProvider(settings.gemini_api_key or "", settings.gemini_model, settings.ai_timeout_seconds)
        except AIUnavailable as e:
            log.warning("Gemini unavailable (%s); using the rule-based parser", e)
        except Exception as e:
            log.warning("Gemini could not be set up (%s); using the rule-based parser", type(e).__name__)
    return RuleBasedProvider()


def run_json_task(prompt: str, schema: type[T], **context) -> tuple[T, str]:
    """Runs a task and returns (validated result, provider name).

    Gemini output is validated with `schema`; invalid JSON is retried once. Any failure
    (no key, quota, timeout, invalid output) falls back to the rule-based provider, so
    this never raises because of the AI.
    """
    provider = get_provider()
    if provider.name != "rules":
        for attempt in (1, 2):
            try:
                return schema.model_validate(provider.generate_json(prompt, schema, **context)), provider.name
            except (InvalidAIResponse, ValidationError) as e:
                log.warning("%s returned an invalid response (attempt %d: %s)", provider.name, attempt, type(e).__name__)
            except AIUnavailable as e:
                log.warning("%s unavailable (%s); falling back to rules", provider.name, e)
                break
            except Exception as e:
                log.warning("%s failed (%s); falling back to rules", provider.name, type(e).__name__)
                break
        else:
            log.warning("%s gave invalid output twice; falling back to rules", provider.name)
    return schema.model_validate(RuleBasedProvider().generate_json(prompt, schema, **context)), "rules"
