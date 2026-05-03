from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.health_response_status import HealthResponseStatus

if TYPE_CHECKING:
    from ..models.deps import Deps


T = TypeVar("T", bound="HealthResponse")


@_attrs_define
class HealthResponse:
    """
    Attributes:
        deps (Deps):
        status (HealthResponseStatus):
        uptime_s (int):
        version (str):
    """

    deps: Deps
    status: HealthResponseStatus
    uptime_s: int
    version: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        deps = self.deps.to_dict()

        status = self.status.value

        uptime_s = self.uptime_s

        version = self.version

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "deps": deps,
                "status": status,
                "uptime_s": uptime_s,
                "version": version,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.deps import Deps

        d = dict(src_dict)
        deps = Deps.from_dict(d.pop("deps"))

        status = HealthResponseStatus(d.pop("status"))

        uptime_s = d.pop("uptime_s")

        version = d.pop("version")

        health_response = cls(
            deps=deps,
            status=status,
            uptime_s=uptime_s,
            version=version,
        )

        health_response.additional_properties = d
        return health_response

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
