from enum import Enum


class IMessageSentRequestAgent(str, Enum):
    CLU = "clu"
    FLYNN = "flynn"
    TRON = "tron"

    def __str__(self) -> str:
        return str(self.value)
