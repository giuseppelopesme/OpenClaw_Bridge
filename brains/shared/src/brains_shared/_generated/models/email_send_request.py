from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.email_send_request_account import EmailSendRequestAccount
from ..types import UNSET, Unset

T = TypeVar("T", bound="EmailSendRequest")


@_attrs_define
class EmailSendRequest:
    """
    Attributes:
        account (EmailSendRequestAccount):
        subject (str):
        to (list[str]):
        bcc (list[str] | Unset):
        body_html (None | str | Unset):
        body_text (None | str | Unset):
        cc (list[str] | Unset):
        in_reply_to (None | str | Unset):
    """

    account: EmailSendRequestAccount
    subject: str
    to: list[str]
    bcc: list[str] | Unset = UNSET
    body_html: None | str | Unset = UNSET
    body_text: None | str | Unset = UNSET
    cc: list[str] | Unset = UNSET
    in_reply_to: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        account = self.account.value

        subject = self.subject

        to = self.to

        bcc: list[str] | Unset = UNSET
        if not isinstance(self.bcc, Unset):
            bcc = self.bcc

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

        cc: list[str] | Unset = UNSET
        if not isinstance(self.cc, Unset):
            cc = self.cc

        in_reply_to: None | str | Unset
        if isinstance(self.in_reply_to, Unset):
            in_reply_to = UNSET
        else:
            in_reply_to = self.in_reply_to

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "account": account,
                "subject": subject,
                "to": to,
            }
        )
        if bcc is not UNSET:
            field_dict["bcc"] = bcc
        if body_html is not UNSET:
            field_dict["body_html"] = body_html
        if body_text is not UNSET:
            field_dict["body_text"] = body_text
        if cc is not UNSET:
            field_dict["cc"] = cc
        if in_reply_to is not UNSET:
            field_dict["in_reply_to"] = in_reply_to

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        account = EmailSendRequestAccount(d.pop("account"))

        subject = d.pop("subject")

        to = cast(list[str], d.pop("to"))

        bcc = cast(list[str], d.pop("bcc", UNSET))

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

        cc = cast(list[str], d.pop("cc", UNSET))

        def _parse_in_reply_to(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        in_reply_to = _parse_in_reply_to(d.pop("in_reply_to", UNSET))

        email_send_request = cls(
            account=account,
            subject=subject,
            to=to,
            bcc=bcc,
            body_html=body_html,
            body_text=body_text,
            cc=cc,
            in_reply_to=in_reply_to,
        )

        email_send_request.additional_properties = d
        return email_send_request

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
