from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.event_publish_request_payload import EventPublishRequestPayload


T = TypeVar("T", bound="EventPublishRequest")


@_attrs_define
class EventPublishRequest:
    """
    Attributes:
        topic (str):
        payload (EventPublishRequestPayload | Unset):
        ttl_s (int | None | Unset):
    """

    topic: str
    payload: EventPublishRequestPayload | Unset = UNSET
    ttl_s: int | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        topic = self.topic

        payload: dict[str, Any] | Unset = UNSET
        if not isinstance(self.payload, Unset):
            payload = self.payload.to_dict()

        ttl_s: int | None | Unset
        if isinstance(self.ttl_s, Unset):
            ttl_s = UNSET
        else:
            ttl_s = self.ttl_s

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "topic": topic,
            }
        )
        if payload is not UNSET:
            field_dict["payload"] = payload
        if ttl_s is not UNSET:
            field_dict["ttl_s"] = ttl_s

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.event_publish_request_payload import EventPublishRequestPayload

        d = dict(src_dict)
        topic = d.pop("topic")

        _payload = d.pop("payload", UNSET)
        payload: EventPublishRequestPayload | Unset
        if isinstance(_payload, Unset):
            payload = UNSET
        else:
            payload = EventPublishRequestPayload.from_dict(_payload)

        def _parse_ttl_s(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        ttl_s = _parse_ttl_s(d.pop("ttl_s", UNSET))

        event_publish_request = cls(
            topic=topic,
            payload=payload,
            ttl_s=ttl_s,
        )

        event_publish_request.additional_properties = d
        return event_publish_request

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
