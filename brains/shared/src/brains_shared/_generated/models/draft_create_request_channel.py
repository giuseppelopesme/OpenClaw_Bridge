from enum import Enum


class DraftCreateRequestChannel(str, Enum):
    EMAIL = "email"
    IMESSAGE = "imessage"

    def __str__(self) -> str:
        return str(self.value)
