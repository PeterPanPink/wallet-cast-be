"""Translation service (sanitized demo).

In the original codebase, this module used an external LLM provider for translation.
For this public demo:
- When DEMO_MODE=true (default), we return deterministic stub translations.
- When DEMO_MODE=false, the real provider integration can be enabled (requires SDK + API key).
"""

import json

from loguru import logger
from pydantic import BaseModel, Field

from app.shared.config import config
from app.utils.app_errors import AppError, AppErrorCode, HttpStatusCode


class TranslationRequest(BaseModel):
    """Request parameters for translation."""

    text: str = Field(..., description="Text to translate")
    target_languages: list[str] = Field(..., description="Target languages for translation")


class TranslationResponse(BaseModel):
    """Response from translation service."""

    translations: dict[str, str] = Field(
        ..., description="Dictionary mapping target language to translated text"
    )


class TranslatorService:
    """Translation service using OpenAI GPT-4.1-nano.

    This service provides a simple interface for translating text to multiple languages
    using OpenAI's chat completion API with the gpt-4.1-nano model.

    Example:
        ```python
        translator = TranslatorService()
        response = await translator.translate(
            text="Hello, world!",
            target_languages=["Spanish", "French"]
        )
        print(response.translations["Spanish"])  # "¡Hola, mundo!"
        print(response.translations["French"])   # "Bonjour, monde!"
        ```
    """

    def __init__(self) -> None:
        """Initialize the translator service.

        Raises:
            AppError: If DEMO_MODE=false but required provider config is missing
        """
        self._demo_mode = str(config.get("DEMO_MODE", "true")).strip().lower() == "true"
        self._client = None

        if self._demo_mode:
            logger.info("TranslatorService initialized in DEMO_MODE (stubbed)")
            return

        api_key = config.get("OPENAI_API_KEY")
        if not api_key:
            logger.error("OPENAI_API_KEY not configured (DEMO_MODE=false)")
            raise AppError(
                errcode=AppErrorCode.E_INVALID_REQUEST,
                errmesg="OPENAI_API_KEY must be configured when DEMO_MODE=false.",
                status_code=HttpStatusCode.BAD_REQUEST,
            )

        try:
            from openai import AsyncOpenAI  # type: ignore
        except Exception as exc:
            raise AppError(
                errcode=AppErrorCode.E_INVALID_REQUEST,
                errmesg=f"OpenAI SDK is not installed: {exc}",
                status_code=HttpStatusCode.BAD_REQUEST,
            ) from exc

        self._client = AsyncOpenAI(api_key=api_key)
        logger.info("TranslatorService initialized (provider enabled)")

    async def translate(
        self,
        text: str,
        target_languages: list[str],
    ) -> TranslationResponse:
        """Translate text to multiple target languages.

        Args:
            text: Text to translate
            target_languages: List of target languages (e.g., ["Spanish", "French", "Japanese"])

        Returns:
            TranslationResponse with translations for each target language

        Raises:
            ValueError: If translation fails
            Exception: If API call fails
        """
        if not target_languages:
            raise AppError(
                errcode=AppErrorCode.E_INVALID_REQUEST,
                errmesg="target_languages must contain at least one language",
                status_code=HttpStatusCode.BAD_REQUEST,
            )

        logger.debug(f"Translating text: text_length={len(text)}, target_languages={target_languages}")

        # Demo-safe stub: deterministic output, no external calls.
        if self._demo_mode:
            translations = {lang: f"[{lang}] {text}" for lang in target_languages}
            return TranslationResponse(translations=translations)

        system_prompt = (
            "You are a professional translator. Translate the provided text into each "
            "requested target language. Use the exact language names that are supplied. "
            "Return a JSON object that matches the provided schema without any extra fields or narration."
        )
        user_prompt = (
            "Translate the text into every target language. "
            "Return fluent, natural translations and do not include transliterations unless explicitly requested.\n\n"
            "Target languages:\n"
            + "\n".join(f"- {language}" for language in target_languages)
            + "\n\nText:\n"
            + text
        )

        try:
            if self._client is None:
                raise AppError(
                    errcode=AppErrorCode.E_INTERNAL_ERROR,
                    errmesg="Translator client is not initialized",
                    status_code=HttpStatusCode.INTERNAL_SERVER_ERROR,
                )
            response = await self._client.chat.completions.create(
                model="gpt-4.1-nano",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "multi_translation_response",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "translations": {
                                    "type": "object",
                                    "additionalProperties": {"type": "string"},
                                }
                            },
                            "required": ["translations"],
                            "additionalProperties": False,
                        },
                    },
                },
                temperature=0.2,
                max_tokens=2000,
            )
        except Exception as exc:
            logger.exception(
                f"Translation request failed: text_length={len(text)}, target_languages={target_languages}, error={exc}"
            )
            raise

        message = response.choices[0].message

        # Check for refusal first (model declined to respond)
        if message.refusal:
            logger.error(f"Translation refused by model: refusal={message.refusal}")
            raise AppError(
                errcode=AppErrorCode.E_INTERNAL_ERROR,
                errmesg=f"Translation refused: {message.refusal}",
                status_code=HttpStatusCode.INTERNAL_SERVER_ERROR,
            )

        # With json_schema response_format, content is a JSON string
        if not message.content:
            logger.error("Translation response has no content")
            raise AppError(
                errcode=AppErrorCode.E_INTERNAL_ERROR,
                errmesg="Translation response did not return content",
                status_code=HttpStatusCode.INTERNAL_SERVER_ERROR,
            )

        # Parse the JSON content
        try:
            parsed_payload = json.loads(message.content)
        except json.JSONDecodeError as exc:
            logger.error(
                f"Failed to parse translation response as JSON: content={message.content}, error={exc}"
            )
            raise AppError(
                errcode=AppErrorCode.E_INTERNAL_ERROR,
                errmesg=f"Translation response is not valid JSON: {exc}",
                status_code=HttpStatusCode.INTERNAL_SERVER_ERROR,
            ) from exc

        translations_payload = parsed_payload.get("translations", {})
        if not translations_payload:
            logger.error(
                f"Translation response missing 'translations' key: parsed_payload={parsed_payload}"
            )
            raise AppError(
                errcode=AppErrorCode.E_INTERNAL_ERROR,
                errmesg="Translation response missing 'translations' field",
                status_code=HttpStatusCode.INTERNAL_SERVER_ERROR,
            )

        translations: dict[str, str] = {}

        for language in target_languages:
            translated_text = translations_payload.get(language)
            if not translated_text:
                logger.error(
                    f"Translation missing for language: target_language={language}, available_keys={list(translations_payload.keys())}"
                )
                raise AppError(
                    errcode=AppErrorCode.E_INTERNAL_ERROR,
                    errmesg=f"Translation to {language} returned empty or missing response",
                    status_code=HttpStatusCode.INTERNAL_SERVER_ERROR,
                )
            translations[language] = translated_text.strip()

        logger.info(
            f"Translation completed: target_languages={target_languages}, original_length={len(text)}"
        )

        return TranslationResponse(translations=translations)
