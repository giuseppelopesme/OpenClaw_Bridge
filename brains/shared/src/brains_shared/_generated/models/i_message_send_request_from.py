from enum import Enum


class IMessageSendRequestFrom(str, Enum):
    CLU = "clu"
    FLYNN = "flynn"
    MAIN = "main"
    TRON = "tron"

    def __str__(self) -> str:
        return str(self.value)
