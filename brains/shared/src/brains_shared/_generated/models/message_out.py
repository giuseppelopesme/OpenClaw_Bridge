from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="MessageOut")


@_attrs_define
class MessageOut:
    """
    Attributes:
        cc (list[str]):
        date (str):
        from_ (str):
        id (str):
        message_id (str):
        subject (str):
        to (list[str]):
        body_html (None | str | Unset):
        body_text (None | str | Unset):
        in_reply_to (None | str | Unset):
        references (list[str] | Unset):
    """

    cc: list[str]
    date: str
    from_: str
    id: str
    message_id: str
    subject: str
    to: list[str]
    body_html: None | str | Unset = UNSET
    body_text: None | str | Unset = UNSET
    in_reply_to: None | str | Unset = UNSET
    references: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        cc = self.cc

        date = self.date

        from_ = self.from_

        id = self.id

        message_id = self.message_id

        subject = self.subject

        to = self.to

        body_html: None | str | Unset
        if isinstance(self.body_html, Unset):
            body_html = UNSET
        else:
            body_html = self.body_html

        body_text: None | str | Unset
        if isinstance(self.body_text, Unset):
            body_text = UNSET
        else:
            body_text = self.body_text

        in_reply_to: None | str | Unset
        if isinstance(self.in_reply_to, Unset):
            in_reply_to = UNSET
        else:
            in_reply_to = self.in_reply_to

        references: list[str] | Unset = UNSET
        if not isinstance(self.references, Unset):
            references = self.references

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "cc": cc,
                "date": date,
                "from": from_,
                "id": id,
                "message_id": message_id,
                "subject": subject,
                "to": to,
            }
        )
        if body_html is not UNSET:
            field_dict["body_html"] = body_html
        if body_text is not UNSET:
            field_dict["body_text"] = body_text
        if in_reply_to is not UNSET:
            field_dict["in_reply_to"] = in_reply_to
        if references is not UNSET:
            field_dict["references"] = references

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        cc = cast(list[str], d.pop("cc"))

        date = d.pop("date")

        from_ = d.pop("from")

        id = d.pop("id")

        message_id = d.pop("message_id")

        subject = d.pop("subject")

        to = cast(list[str], d.pop("to"))

        def _parse_body_html(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        body_html = _parse_body_html(d.pop("body_html", UNSET))

        def _parse_body_text(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        body_text = _parse_body_text(d.pop("body_text", UNSET))

        def _parse_in_reply_to(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        in_reply_to = _parse_in_reply_to(d.pop("in_reply_to", UNSET))

        references = cast(list[str], d.pop("references", UNSET))

        message_out = cls(
            cc=cc,
            date=date,
            from_=from_,
            id=id,
            message_id=message_id,
            subject=subject,
            to=to,
            body_html=body_html,
            body_text=body_text,
            in_reply_to=in_reply_to,
            references=references,
        )

        message_out.additional_properties = d
        return message_out

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
