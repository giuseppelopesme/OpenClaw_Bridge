from enum import Enum


class LLMCompleteRequestResponseFormat(str, Enum):
    JSON = "json"
    TEXT = "text"

    def __str__(self) -> str:
        return str(self.value)
