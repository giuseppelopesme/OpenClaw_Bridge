from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.message_out import MessageOut


T = TypeVar("T", bound="EmailThreadDetailResponse")


@_attrs_define
class EmailThreadDetailResponse:
    """
    Attributes:
        id (str):
        messages (list[MessageOut]):
        subject (str):
    """

    id: str
    messages: list[MessageOut]
    subject: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        messages = []
        for messages_item_data in self.messages:
            messages_item = messages_item_data.to_dict()
            messages.append(messages_item)

        subject = self.subject

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "messages": messages,
                "subject": subject,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.message_out import MessageOut

        d = dict(src_dict)
        id = d.pop("id")

        messages = []
        _messages = d.pop("messages")
        for messages_item_data in _messages:
            messages_item = MessageOut.from_dict(messages_item_data)

            messages.append(messages_item)

        subject = d.pop("subject")

        email_thread_detail_response = cls(
            id=id,
            messages=messages,
            subject=subject,
        )

        email_thread_detail_response.additional_properties = d
        return email_thread_detail_response

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
