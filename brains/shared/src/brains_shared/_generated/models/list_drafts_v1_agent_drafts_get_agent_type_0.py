from enum import Enum


class ListDraftsV1AgentDraftsGetAgentType0(str, Enum):
    CLU = "clu"
    FLYNN = "flynn"
    TRON = "tron"

    def __str__(self) -> str:
        return str(self.value)
