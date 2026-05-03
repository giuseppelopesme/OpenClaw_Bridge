from enum import Enum


class IMessageSendRequestService(str, Enum):
    IMESSAGE = "iMessage"
    SMS = "SMS"

    def __str__(self) -> str:
        return str(self.value)
