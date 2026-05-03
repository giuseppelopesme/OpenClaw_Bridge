from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="ThreadOut")


@_attrs_define
class ThreadOut:
    """
    Attributes:
        id (str):
        latest_at (str):
        message_count (int):
        participants (list[str]):
        snippet (str):
        subject (str):
    """

    id: str
    latest_at: str
    message_count: int
    participants: list[str]
    snippet: str
    subject: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        latest_at = self.latest_at

        message_count = self.message_count

        participants = self.participants

        snippet = self.snippet

        subject = self.subject

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "latest_at": latest_at,
                "message_count": message_count,
                "participants": participants,
                "snippet": snippet,
                "subject": subject,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = d.pop("id")

        latest_at = d.pop("latest_at")

        message_count = d.pop("message_count")

        participants = cast(list[str], d.pop("participants"))

        snippet = d.pop("snippet")

        subject = d.pop("subject")

        thread_out = cls(
            id=id,
            latest_at=latest_at,
            message_count=message_count,
            participants=participants,
            snippet=snippet,
            subject=subject,
        )

        thread_out.additional_properties = d
        return thread_out

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
