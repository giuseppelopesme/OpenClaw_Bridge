from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.draft_out import DraftOut


T = TypeVar("T", bound="DraftListResponse")


@_attrs_define
class DraftListResponse:
    """
    Attributes:
        drafts (list[DraftOut]):
    """

    drafts: list[DraftOut]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        drafts = []
        for drafts_item_data in self.drafts:
            drafts_item = drafts_item_data.to_dict()
            drafts.append(drafts_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "drafts": drafts,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.draft_out import DraftOut

        d = dict(src_dict)
        drafts = []
        _drafts = d.pop("drafts")
        for drafts_item_data in _drafts:
            drafts_item = DraftOut.from_dict(drafts_item_data)

            drafts.append(drafts_item)

        draft_list_response = cls(
            drafts=drafts,
        )

        draft_list_response.additional_properties = d
        return draft_list_response

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
