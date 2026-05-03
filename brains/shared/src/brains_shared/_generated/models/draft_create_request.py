from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.draft_create_request_agent import DraftCreateRequestAgent
from ..models.draft_create_request_channel import DraftCreateRequestChannel
from ..types import UNSET, Unset

T = TypeVar("T", bound="DraftCreateRequest")


@_attrs_define
class DraftCreateRequest:
    """
    Attributes:
        agent (DraftCreateRequestAgent):
        body (str):
        to_handle (str):
        channel (DraftCreateRequestChannel | Unset):  Default: DraftCreateRequestChannel.IMESSAGE.
        in_reply_to_event_id (None | str | Unset):
        preview (None | str | Unset):
    """

    agent: DraftCreateRequestAgent
    body: str
    to_handle: str
    channel: DraftCreateRequestChannel | Unset = DraftCreateRequestChannel.IMESSAGE
    in_reply_to_event_id: None | str | Unset = UNSET
    preview: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        agent = self.agent.value

        body = self.body

        to_handle = self.to_handle

        channel: str | Unset = UNSET
        if not isinstance(self.channel, Unset):
            channel = self.channel.value

        in_reply_to_event_id: None | str | Unset
        if isinstance(self.in_reply_to_event_id, Unset):
            in_reply_to_event_id = UNSET
        else:
            in_reply_to_event_id = self.in_reply_to_event_id

        preview: None | str | Unset
        if isinstance(self.preview, Unset):
            preview = UNSET
        else:
            preview = self.preview

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "agent": agent,
                "body": body,
                "to_handle": to_handle,
            }
        )
        if channel is not UNSET:
            field_dict["channel"] = channel
        if in_reply_to_event_id is not UNSET:
            field_dict["in_reply_to_event_id"] = in_reply_to_event_id
        if preview is not UNSET:
            field_dict["preview"] = preview

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        agent = DraftCreateRequestAgent(d.pop("agent"))

        body = d.pop("body")

        to_handle = d.pop("to_handle")

        _channel = d.pop("channel", UNSET)
        channel: DraftCreateRequestChannel | Unset
        if isinstance(_channel, Unset):
            channel = UNSET
        else:
            channel = DraftCreateRequestChannel(_channel)

        def _parse_in_reply_to_event_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        in_reply_to_event_id = _parse_in_reply_to_event_id(d.pop("in_reply_to_event_id", UNSET))

        def _parse_preview(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        preview = _parse_preview(d.pop("preview", UNSET))

        draft_create_request = cls(
            agent=agent,
            body=body,
            to_handle=to_handle,
            channel=channel,
            in_reply_to_event_id=in_reply_to_event_id,
            preview=preview,
        )

        draft_create_request.additional_properties = d
        return draft_create_request

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
