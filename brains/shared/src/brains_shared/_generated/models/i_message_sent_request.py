from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.i_message_sent_request_agent import IMessageSentRequestAgent
from ..models.i_message_sent_request_status import IMessageSentRequestStatus
from ..types import UNSET, Unset

T = TypeVar("T", bound="IMessageSentRequest")


@_attrs_define
class IMessageSentRequest:
    """
    Attributes:
        agent (IMessageSentRequestAgent):
        body (str):
        message_id (str):
        status (IMessageSentRequestStatus):
        to (str):
        error_code (None | str | Unset):
        error_message (None | str | Unset):
        sent_at (None | str | Unset):
    """

    agent: IMessageSentRequestAgent
    body: str
    message_id: str
    status: IMessageSentRequestStatus
    to: str
    error_code: None | str | Unset = UNSET
    error_message: None | str | Unset = UNSET
    sent_at: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        agent = self.agent.value

        body = self.body

        message_id = self.message_id

        status = self.status.value

        to = self.to

        error_code: None | str | Unset
        if isinstance(self.error_code, Unset):
            error_code = UNSET
        else:
            error_code = self.error_code

        error_message: None | str | Unset
        if isinstance(self.error_message, Unset):
            error_message = UNSET
        else:
            error_message = self.error_message

        sent_at: None | str | Unset
        if isinstance(self.sent_at, Unset):
            sent_at = UNSET
        else:
            sent_at = self.sent_at

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "agent": agent,
                "body": body,
                "message_id": message_id,
                "status": status,
                "to": to,
            }
        )
        if error_code is not UNSET:
            field_dict["error_code"] = error_code
        if error_message is not UNSET:
            field_dict["error_message"] = error_message
        if sent_at is not UNSET:
            field_dict["sent_at"] = sent_at

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        agent = IMessageSentRequestAgent(d.pop("agent"))

        body = d.pop("body")

        message_id = d.pop("message_id")

        status = IMessageSentRequestStatus(d.pop("status"))

        to = d.pop("to")

        def _parse_error_code(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        error_code = _parse_error_code(d.pop("error_code", UNSET))

        def _parse_error_message(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        error_message = _parse_error_message(d.pop("error_message", UNSET))

        def _parse_sent_at(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        sent_at = _parse_sent_at(d.pop("sent_at", UNSET))

        i_message_sent_request = cls(
            agent=agent,
            body=body,
            message_id=message_id,
            status=status,
            to=to,
            error_code=error_code,
            error_message=error_message,
            sent_at=sent_at,
        )

        i_message_sent_request.additional_properties = d
        return i_message_sent_request

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
