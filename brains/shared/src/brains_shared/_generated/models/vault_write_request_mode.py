from enum import Enum


class VaultWriteRequestMode(str, Enum):
    APPEND = "append"
    CREATE = "create"
    REPLACE = "replace"

    def __str__(self) -> str:
        return str(self.value)
