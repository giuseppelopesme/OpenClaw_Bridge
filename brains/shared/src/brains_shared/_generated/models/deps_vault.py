from enum import Enum


class DepsVault(str, Enum):
    DEGRADED = "degraded"
    DOWN = "down"
    OK = "ok"

    def __str__(self) -> str:
        return str(self.value)
