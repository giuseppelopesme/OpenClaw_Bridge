from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.vault_read_response_frontmatter import VaultReadResponseFrontmatter


T = TypeVar("T", bound="VaultReadResponse")


@_attrs_define
class VaultReadResponse:
    """
    Attributes:
        content (str):
        frontmatter (VaultReadResponseFrontmatter):
        modified_at (str):
        path (str):
        size (int):
    """

    content: str
    frontmatter: VaultReadResponseFrontmatter
    modified_at: str
    path: str
    size: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        content = self.content

        frontmatter = self.frontmatter.to_dict()

        modified_at = self.modified_at

        path = self.path

        size = self.size

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "content": content,
                "frontmatter": frontmatter,
                "modified_at": modified_at,
                "path": path,
                "size": size,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.vault_read_response_frontmatter import VaultReadResponseFrontmatter

        d = dict(src_dict)
        content = d.pop("content")

        frontmatter = VaultReadResponseFrontmatter.from_dict(d.pop("frontmatter"))

        modified_at = d.pop("modified_at")

        path = d.pop("path")

        size = d.pop("size")

        vault_read_response = cls(
            content=content,
            frontmatter=frontmatter,
            modified_at=modified_at,
            path=path,
            size=size,
        )

        vault_read_response.additional_properties = d
        return vault_read_response

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
