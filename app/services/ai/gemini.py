"""Google Gemini through the official google-genai SDK."""

import json
import logging

from pydantic import BaseModel

from app.services.ai.base import AIUnavailable, InvalidAIResponse, LLMProvider

log = logging.getLogger("intervo.ai")


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout_seconds: int = 20):
        if not api_key:
            raise AIUnavailable("GEMINI_API_KEY is not set")
        from google import genai
        from google.genai import types

        self._types = types
        self._model = model
        # The SDK's timeout is in milliseconds.
        self._client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=timeout_seconds * 1000))

    def generate_json(self, prompt: str, schema: type[BaseModel], **context) -> dict:
        from google.genai import errors

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
                config=self._types.GenerateContentConfig(
                    response_mime_type="application/json", max_output_tokens=8192,
                    # extraction and scoring must be repeatable; a new question must vary
                    temperature=0.9 if context.get("task") == "question" else 0,
                ),
            )
        except errors.APIError as e:
            # Log the status only: never the key, never the request.
            raise AIUnavailable(f"Gemini API error {getattr(e, 'code', '?')}") from None
        except Exception as e:  # timeout, DNS, TLS ...
            raise AIUnavailable(f"Gemini call failed ({type(e).__name__})") from None

        text = (response.text or "").strip() if response is not None else ""
        if text.startswith("```"):  # some models still fence JSON
            text = text.strip("`")
            text = text[4:] if text.lower().startswith("json") else text
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            raise InvalidAIResponse("Gemini returned text that is not JSON") from None
        if not isinstance(data, dict):
            raise InvalidAIResponse("Gemini returned JSON that is not an object")
        return data
