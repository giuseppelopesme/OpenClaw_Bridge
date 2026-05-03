from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.reminder_out import ReminderOut


T = TypeVar("T", bound="RemindersListResponse")


@_attrs_define
class RemindersListResponse:
    """
    Attributes:
        reminders (list[ReminderOut]):
    """

    reminders: list[ReminderOut]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        reminders = []
        for reminders_item_data in self.reminders:
            reminders_item = reminders_item_data.to_dict()
            reminders.append(reminders_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "reminders": reminders,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.reminder_out import ReminderOut

        d = dict(src_dict)
        reminders = []
        _reminders = d.pop("reminders")
        for reminders_item_data in _reminders:
            reminders_item = ReminderOut.from_dict(reminders_item_data)

            reminders.append(reminders_item)

        reminders_list_response = cls(
            reminders=reminders,
        )

        reminders_list_response.additional_properties = d
        return reminders_list_response

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
