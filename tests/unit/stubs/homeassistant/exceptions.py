"""Stub of homeassistant.exceptions."""


class HomeAssistantError(Exception):
    def __init__(
        self,
        *args,
        translation_domain=None,
        translation_key=None,
        translation_placeholders=None,
    ):
        if not args and translation_key and translation_domain:
            args = (translation_key,)
        super().__init__(*args)
        self.translation_domain = translation_domain
        self.translation_key = translation_key
        self.translation_placeholders = translation_placeholders


class ServiceValidationError(HomeAssistantError):
    pass


class ConfigEntryNotReady(HomeAssistantError):
    pass
