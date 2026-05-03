from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="DraftOut")


@_attrs_define
class DraftOut:
    """
    Attributes:
        agent (str):
        body (str):
        channel (str):
        created_at (str):
        draft_id (str):
        last_modified_at (str):
        publisher (str):
        status (str):
        to_handle (str):
        approved_at (None | str | Unset):
        approved_by (None | str | Unset):
        dispatch_message_id (None | str | Unset):
        in_reply_to_event_id (None | str | Unset):
        last_send_error_code (None | str | Unset):
        last_send_error_message (None | str | Unset):
        preview (None | str | Unset):
        reject_reason (None | str | Unset):
        sent_at (None | str | Unset):
    """

    agent: str
    body: str
    channel: str
    created_at: str
    draft_id: str
    last_modified_at: str
    publisher: str
    status: str
    to_handle: str
    approved_at: None | str | Unset = UNSET
    approved_by: None | str | Unset = UNSET
    dispatch_message_id: None | str | Unset = UNSET
    in_reply_to_event_id: None | str | Unset = UNSET
    last_send_error_code: None | str | Unset = UNSET
    last_send_error_message: None | str | Unset = UNSET
    preview: None | str | Unset = UNSET
    reject_reason: None | str | Unset = UNSET
    sent_at: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        agent = self.agent

        body = self.body

        channel = self.channel

        created_at = self.created_at

        draft_id = self.draft_id

        last_modified_at = self.last_modified_at

        publisher = self.publisher

        status = self.status

        to_handle = self.to_handle

        approved_at: None | str | Unset
        if isinstance(self.approved_at, Unset):
            approved_at = UNSET
        else:
            approved_at = self.approved_at

        approved_by: None | str | Unset
        if isinstance(self.approved_by, Unset):
            approved_by = UNSET
        else:
            approved_by = self.approved_by

        dispatch_message_id: None | str | Unset
        if isinstance(self.dispatch_message_id, Unset):
            dispatch_message_id = UNSET
        else:
            dispatch_message_id = self.dispatch_message_id

        in_reply_to_event_id: None | str | Unset
        if isinstance(self.in_reply_to_event_id, Unset):
            in_reply_to_event_id = UNSET
        else:
            in_reply_to_event_id = self.in_reply_to_event_id

        last_send_error_code: None | str | Unset
        if isinstance(self.last_send_error_code, Unset):
            last_send_error_code = UNSET
        else:
            last_send_error_code = self.last_send_error_code

        last_send_error_message: None | str | Unset
        if isinstance(self.last_send_error_message, Unset):
            last_send_error_message = UNSET
        else:
            last_send_error_message = self.last_send_error_message

        preview: None | str | Unset
        if isinstance(self.preview, Unset):
            preview = UNSET
        else:
            preview = self.preview

        reject_reason: None | str | Unset
        if isinstance(self.reject_reason, Unset):
            reject_reason = UNSET
        else:
            reject_reason = self.reject_reason

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
                "channel": channel,
                "created_at": created_at,
                "draft_id": draft_id,
                "last_modified_at": last_modified_at,
                "publisher": publisher,
                "status": status,
                "to_handle": to_handle,
            }
        )
        if approved_at is not UNSET:
            field_dict["approved_at"] = approved_at
        if approved_by is not UNSET:
            field_dict["approved_by"] = approved_by
        if dispatch_message_id is not UNSET:
            field_dict["dispatch_message_id"] = dispatch_message_id
        if in_reply_to_event_id is not UNSET:
            field_dict["in_reply_to_event_id"] = in_reply_to_event_id
        if last_send_error_code is not UNSET:
            field_dict["last_send_error_code"] = last_send_error_code
        if last_send_error_message is not UNSET:
            field_dict["last_send_error_message"] = last_send_error_message
        if preview is not UNSET:
            field_dict["preview"] = preview
        if reject_reason is not UNSET:
            field_dict["reject_reason"] = reject_reason
        if sent_at is not UNSET:
            field_dict["sent_at"] = sent_at

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        agent = d.pop("agent")

        body = d.pop("body")

        channel = d.pop("channel")

        created_at = d.pop("created_at")

        draft_id = d.pop("draft_id")

        last_modified_at = d.pop("last_modified_at")

        publisher = d.pop("publisher")

        status = d.pop("status")

        to_handle = d.pop("to_handle")

        def _parse_approved_at(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        approved_at = _parse_approved_at(d.pop("approved_at", UNSET))

        def _parse_approved_by(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        approved_by = _parse_approved_by(d.pop("approved_by", UNSET))

        def _parse_dispatch_message_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        dispatch_message_id = _parse_dispatch_message_id(d.pop("dispatch_message_id", UNSET))

        def _parse_in_reply_to_event_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        in_reply_to_event_id = _parse_in_reply_to_event_id(d.pop("in_reply_to_event_id", UNSET))

        def _parse_last_send_error_code(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        last_send_error_code = _parse_last_send_error_code(d.pop("last_send_error_code", UNSET))

        def _parse_last_send_error_message(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        last_send_error_message = _parse_last_send_error_message(
            d.pop("last_send_error_message", UNSET)
        )

        def _parse_preview(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        preview = _parse_preview(d.pop("preview", UNSET))

        def _parse_reject_reason(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        reject_reason = _parse_reject_reason(d.pop("reject_reason", UNSET))

        def _parse_sent_at(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        sent_at = _parse_sent_at(d.pop("sent_at", UNSET))

        draft_out = cls(
            agent=agent,
            body=body,
            channel=channel,
            created_at=created_at,
            draft_id=draft_id,
            last_modified_at=last_modified_at,
            publisher=publisher,
            status=status,
            to_handle=to_handle,
            approved_at=approved_at,
            approved_by=approved_by,
            dispatch_message_id=dispatch_message_id,
            in_reply_to_event_id=in_reply_to_event_id,
            last_send_error_code=last_send_error_code,
            last_send_error_message=last_send_error_message,
            preview=preview,
            reject_reason=reject_reason,
            sent_at=sent_at,
        )

        draft_out.additional_properties = d
        return draft_out

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
