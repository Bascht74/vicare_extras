"""Errors of the ViCare Extras integration.

Kept free of Home Assistant imports so the logic modules can be tested alone.
The action layer converts these into translated Home Assistant errors.
"""

from __future__ import annotations


class ViCareExtrasError(Exception):
    """An error with a translation key and placeholders.

    ``validation`` marks errors caused by the caller's input (they become a
    ``ServiceValidationError``); everything else becomes a ``HomeAssistantError``.
    """

    def __init__(
        self,
        translation_key: str,
        placeholders: dict[str, str] | None = None,
        *,
        validation: bool = False,
    ) -> None:
        """Initialize the error."""
        self.translation_key = translation_key
        self.placeholders = {
            key: str(value) for key, value in (placeholders or {}).items()
        }
        self.validation = validation
        detail = ", ".join(f"{k}={v}" for k, v in self.placeholders.items())
        super().__init__(f"{translation_key} ({detail})" if detail else translation_key)
