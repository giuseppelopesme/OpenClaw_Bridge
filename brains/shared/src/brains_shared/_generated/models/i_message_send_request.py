from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.i_message_send_request_service import IMessageSendRequestService
from ..types import UNSET, Unset

T = TypeVar("T", bound="IMessageSendRequest")


@_attrs_define
class IMessageSendRequest:
    """
    Attributes:
        body (str):
        from_ (str):
        to (str):
        service (IMessageSendRequestService | Unset):  Default: IMessageSendRequestService.IMESSAGE.
    """

    body: str
    from_: str
    to: str
    service: IMessageSendRequestService | Unset = IMessageSendRequestService.IMESSAGE
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        body = self.body

        from_ = self.from_

        to = self.to

        service: str | Unset = UNSET
        if not isinstance(self.service, Unset):
            service = self.service.value

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "body": body,
                "from": from_,
                "to": to,
            }
        )
        if service is not UNSET:
            field_dict["service"] = service

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        body = d.pop("body")

        from_ = d.pop("from")

        to = d.pop("to")

        _service = d.pop("service", UNSET)
        service: IMessageSendRequestService | Unset
        if isinstance(_service, Unset):
            service = UNSET
        else:
            service = IMessageSendRequestService(_service)

        i_message_send_request = cls(
            body=body,
            from_=from_,
            to=to,
            service=service,
        )

        i_message_send_request.additional_properties = d
        return i_message_send_request

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
