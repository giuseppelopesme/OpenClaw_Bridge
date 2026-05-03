from enum import Enum


class LLMCompleteRequestProviderHint(str, Enum):
    AUTO = "auto"
    LOCAL = "local"
    OPENROUTER = "openrouter"

    def __str__(self) -> str:
        return str(self.value)
