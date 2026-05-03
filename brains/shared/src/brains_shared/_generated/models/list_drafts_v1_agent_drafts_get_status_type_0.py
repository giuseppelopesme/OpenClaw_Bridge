from enum import Enum


class ListDraftsV1AgentDraftsGetStatusType0(str, Enum):
    APPROVED = "approved"
    PENDING = "pending"
    REJECTED = "rejected"
    SEND_FAILED = "send_failed"
    SENT = "sent"

    def __str__(self) -> str:
        return str(self.value)
