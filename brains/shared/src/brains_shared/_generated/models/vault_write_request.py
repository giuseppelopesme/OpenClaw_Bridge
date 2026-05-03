from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.vault_write_request_mode import VaultWriteRequestMode
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.vault_write_request_frontmatter_type_0 import VaultWriteRequestFrontmatterType0


T = TypeVar("T", bound="VaultWriteRequest")


@_attrs_define
class VaultWriteRequest:
    """
    Attributes:
        mode (VaultWriteRequestMode):
        path (str):
        content (str | Unset):  Default: ''.
        frontmatter (None | Unset | VaultWriteRequestFrontmatterType0):
    """

    mode: VaultWriteRequestMode
    path: str
    content: str | Unset = ""
    frontmatter: None | Unset | VaultWriteRequestFrontmatterType0 = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.vault_write_request_frontmatter_type_0 import (
            VaultWriteRequestFrontmatterType0,
        )

        mode = self.mode.value

        path = self.path

        content = self.content

        frontmatter: dict[str, Any] | None | Unset
        if isinstance(self.frontmatter, Unset):
            frontmatter = UNSET
        elif isinstance(self.frontmatter, VaultWriteRequestFrontmatterType0):
            frontmatter = self.frontmatter.to_dict()
        else:
            frontmatter = self.frontmatter

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "mode": mode,
                "path": path,
            }
        )
        if content is not UNSET:
            field_dict["content"] = content
        if frontmatter is not UNSET:
            field_dict["frontmatter"] = frontmatter

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.vault_write_request_frontmatter_type_0 import (
            VaultWriteRequestFrontmatterType0,
        )

        d = dict(src_dict)
        mode = VaultWriteRequestMode(d.pop("mode"))

        path = d.pop("path")

        content = d.pop("content", UNSET)

        def _parse_frontmatter(data: object) -> None | Unset | VaultWriteRequestFrontmatterType0:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                frontmatter_type_0 = VaultWriteRequestFrontmatterType0.from_dict(data)

                return frontmatter_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | VaultWriteRequestFrontmatterType0, data)

        frontmatter = _parse_frontmatter(d.pop("frontmatter", UNSET))

        vault_write_request = cls(
            mode=mode,
            path=path,
            content=content,
            frontmatter=frontmatter,
        )

        vault_write_request.additional_properties = d
        return vault_write_request

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
