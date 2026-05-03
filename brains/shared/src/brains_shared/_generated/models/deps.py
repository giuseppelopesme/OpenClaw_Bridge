from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.deps_agent_db import DepsAgentDb
from ..models.deps_apple_bridge import DepsAppleBridge
from ..models.deps_idempotency_db import DepsIdempotencyDb
from ..models.deps_imap_glysk import DepsImapGlysk
from ..models.deps_imap_lopes import DepsImapLopes
from ..models.deps_imap_whilesum import DepsImapWhilesum
from ..models.deps_keychain import DepsKeychain
from ..models.deps_openrouter import DepsOpenrouter
from ..models.deps_redis import DepsRedis
from ..models.deps_telemetry_db import DepsTelemetryDb
from ..models.deps_vault import DepsVault

T = TypeVar("T", bound="Deps")


@_attrs_define
class Deps:
    """
    Attributes:
        agent_db (DepsAgentDb):
        apple_bridge (DepsAppleBridge):
        idempotency_db (DepsIdempotencyDb):
        imap_glysk (DepsImapGlysk):
        imap_lopes (DepsImapLopes):
        imap_whilesum (DepsImapWhilesum):
        keychain (DepsKeychain):
        openrouter (DepsOpenrouter):
        redis (DepsRedis):
        telemetry_db (DepsTelemetryDb):
        vault (DepsVault):
    """

    agent_db: DepsAgentDb
    apple_bridge: DepsAppleBridge
    idempotency_db: DepsIdempotencyDb
    imap_glysk: DepsImapGlysk
    imap_lopes: DepsImapLopes
    imap_whilesum: DepsImapWhilesum
    keychain: DepsKeychain
    openrouter: DepsOpenrouter
    redis: DepsRedis
    telemetry_db: DepsTelemetryDb
    vault: DepsVault
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        agent_db = self.agent_db.value

        apple_bridge = self.apple_bridge.value

        idempotency_db = self.idempotency_db.value

        imap_glysk = self.imap_glysk.value

        imap_lopes = self.imap_lopes.value

        imap_whilesum = self.imap_whilesum.value

        keychain = self.keychain.value

        openrouter = self.openrouter.value

        redis = self.redis.value

        telemetry_db = self.telemetry_db.value

        vault = self.vault.value

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "agent_db": agent_db,
                "apple_bridge": apple_bridge,
                "idempotency_db": idempotency_db,
                "imap_glysk": imap_glysk,
                "imap_lopes": imap_lopes,
                "imap_whilesum": imap_whilesum,
                "keychain": keychain,
                "openrouter": openrouter,
                "redis": redis,
                "telemetry_db": telemetry_db,
                "vault": vault,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        agent_db = DepsAgentDb(d.pop("agent_db"))

        apple_bridge = DepsAppleBridge(d.pop("apple_bridge"))

        idempotency_db = DepsIdempotencyDb(d.pop("idempotency_db"))

        imap_glysk = DepsImapGlysk(d.pop("imap_glysk"))

        imap_lopes = DepsImapLopes(d.pop("imap_lopes"))

        imap_whilesum = DepsImapWhilesum(d.pop("imap_whilesum"))

        keychain = DepsKeychain(d.pop("keychain"))

        openrouter = DepsOpenrouter(d.pop("openrouter"))

        redis = DepsRedis(d.pop("redis"))

        telemetry_db = DepsTelemetryDb(d.pop("telemetry_db"))

        vault = DepsVault(d.pop("vault"))

        deps = cls(
            agent_db=agent_db,
            apple_bridge=apple_bridge,
            idempotency_db=idempotency_db,
            imap_glysk=imap_glysk,
            imap_lopes=imap_lopes,
            imap_whilesum=imap_whilesum,
            keychain=keychain,
            openrouter=openrouter,
            redis=redis,
            telemetry_db=telemetry_db,
            vault=vault,
        )

        deps.additional_properties = d
        return deps

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
