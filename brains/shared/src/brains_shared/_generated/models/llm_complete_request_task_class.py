from enum import Enum


class LLMCompleteRequestTaskClass(str, Enum):
    CLASSIFY = "classify"
    DRAFT = "draft"
    REASON = "reason"
    SUMMARISE = "summarise"
    TRIAGE = "triage"

    def __str__(self) -> str:
        return str(self.value)
