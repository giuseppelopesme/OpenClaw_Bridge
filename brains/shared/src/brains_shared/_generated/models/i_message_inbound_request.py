from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="IMessageInboundRequest")


@_attrs_define
class IMessageInboundRequest:
    """
    Attributes:
        agent (str):
        body (str):
        chat_guid (str):
        from_ (str):
        received_at (str):
    """

    agent: str
    body: str
    chat_guid: str
    from_: str
    received_at: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        agent = self.agent

        body = self.body

        chat_guid = self.chat_guid

        from_ = self.from_

        received_at = self.received_at

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "agent": agent,
                "body": body,
                "chat_guid": chat_guid,
                "from": from_,
                "received_at": received_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        agent = d.pop("agent")

        body = d.pop("body")

        chat_guid = d.pop("chat_guid")

        from_ = d.pop("from")

        received_at = d.pop("received_at")

        i_message_inbound_request = cls(
            agent=agent,
            body=body,
            chat_guid=chat_guid,
            from_=from_,
            received_at=received_at,
        )

        i_message_inbound_request.additional_properties = d
        return i_message_inbound_request

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
