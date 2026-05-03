from enum import Enum


class IMessageSentRequestStatus(str, Enum):
    FAILED = "failed"
    SUCCESS = "success"

    def __str__(self) -> str:
        return str(self.value)
