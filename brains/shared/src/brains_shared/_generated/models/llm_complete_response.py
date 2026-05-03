from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.usage_out import UsageOut


T = TypeVar("T", bound="LLMCompleteResponse")


@_attrs_define
class LLMCompleteResponse:
    """
    Attributes:
        content (str):
        latency_ms (int):
        model (str):
        provider (str):
        usage (UsageOut):
    """

    content: str
    latency_ms: int
    model: str
    provider: str
    usage: UsageOut
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        content = self.content

        latency_ms = self.latency_ms

        model = self.model

        provider = self.provider

        usage = self.usage.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "content": content,
                "latency_ms": latency_ms,
                "model": model,
                "provider": provider,
                "usage": usage,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.usage_out import UsageOut

        d = dict(src_dict)
        content = d.pop("content")

        latency_ms = d.pop("latency_ms")

        model = d.pop("model")

        provider = d.pop("provider")

        usage = UsageOut.from_dict(d.pop("usage"))

        llm_complete_response = cls(
            content=content,
            latency_ms=latency_ms,
            model=model,
            provider=provider,
            usage=usage,
        )

        llm_complete_response.additional_properties = d
        return llm_complete_response

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
