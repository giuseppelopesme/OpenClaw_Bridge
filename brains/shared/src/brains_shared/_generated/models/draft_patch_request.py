from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.draft_patch_request_status_type_0 import DraftPatchRequestStatusType0
from ..types import UNSET, Unset

T = TypeVar("T", bound="DraftPatchRequest")


@_attrs_define
class DraftPatchRequest:
    """
    Attributes:
        approved_by (None | str | Unset):
        body (None | str | Unset):
        reject_reason (None | str | Unset):
        status (DraftPatchRequestStatusType0 | None | Unset):
    """

    approved_by: None | str | Unset = UNSET
    body: None | str | Unset = UNSET
    reject_reason: None | str | Unset = UNSET
    status: DraftPatchRequestStatusType0 | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        approved_by: None | str | Unset
        if isinstance(self.approved_by, Unset):
            approved_by = UNSET
        else:
            approved_by = self.approved_by

        body: None | str | Unset
        if isinstance(self.body, Unset):
            body = UNSET
        else:
            body = self.body

        reject_reason: None | str | Unset
        if isinstance(self.reject_reason, Unset):
            reject_reason = UNSET
        else:
            reject_reason = self.reject_reason

        status: None | str | Unset
        if isinstance(self.status, Unset):
            status = UNSET
        elif isinstance(self.status, DraftPatchRequestStatusType0):
            status = self.status.value
        else:
            status = self.status

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if approved_by is not UNSET:
            field_dict["approved_by"] = approved_by
        if body is not UNSET:
            field_dict["body"] = body
        if reject_reason is not UNSET:
            field_dict["reject_reason"] = reject_reason
        if status is not UNSET:
            field_dict["status"] = status

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_approved_by(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        approved_by = _parse_approved_by(d.pop("approved_by", UNSET))

        def _parse_body(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        body = _parse_body(d.pop("body", UNSET))

        def _parse_reject_reason(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        reject_reason = _parse_reject_reason(d.pop("reject_reason", UNSET))

        def _parse_status(data: object) -> DraftPatchRequestStatusType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                status_type_0 = DraftPatchRequestStatusType0(data)

                return status_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(DraftPatchRequestStatusType0 | None | Unset, data)

        status = _parse_status(d.pop("status", UNSET))

        draft_patch_request = cls(
            approved_by=approved_by,
            body=body,
            reject_reason=reject_reason,
            status=status,
        )

        draft_patch_request.additional_properties = d
        return draft_patch_request

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
