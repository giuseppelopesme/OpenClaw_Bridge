from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="UsageOut")


@_attrs_define
class UsageOut:
    """
    Attributes:
        completion_tokens (int):
        cost_usd (float):
        prompt_tokens (int):
    """

    completion_tokens: int
    cost_usd: float
    prompt_tokens: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        completion_tokens = self.completion_tokens

        cost_usd = self.cost_usd

        prompt_tokens = self.prompt_tokens

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "completion_tokens": completion_tokens,
                "cost_usd": cost_usd,
                "prompt_tokens": prompt_tokens,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        completion_tokens = d.pop("completion_tokens")

        cost_usd = d.pop("cost_usd")

        prompt_tokens = d.pop("prompt_tokens")

        usage_out = cls(
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            prompt_tokens=prompt_tokens,
        )

        usage_out.additional_properties = d
        return usage_out

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
