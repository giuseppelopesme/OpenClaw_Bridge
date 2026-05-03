from enum import Enum


class EmailSendRequestAccount(str, Enum):
    GLYSK = "glysk"
    LOPES = "lopes"
    WHILESUM = "whilesum"

    def __str__(self) -> str:
        return str(self.value)
