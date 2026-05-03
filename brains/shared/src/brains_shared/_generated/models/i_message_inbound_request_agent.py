from enum import Enum


class IMessageInboundRequestAgent(str, Enum):
    CLU = "clu"
    FLYNN = "flynn"
    TRON = "tron"

    def __str__(self) -> str:
        return str(self.value)
