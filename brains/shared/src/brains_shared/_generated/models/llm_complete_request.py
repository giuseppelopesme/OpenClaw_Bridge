from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.llm_complete_request_provider_hint import LLMCompleteRequestProviderHint
from ..models.llm_complete_request_response_format import LLMCompleteRequestResponseFormat
from ..models.llm_complete_request_task_class import LLMCompleteRequestTaskClass
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.message import Message


T = TypeVar("T", bound="LLMCompleteRequest")


@_attrs_define
class LLMCompleteRequest:
    """
    Attributes:
        messages (list[Message]):
        task_class (LLMCompleteRequestTaskClass):
        max_tokens (int | Unset):  Default: 1024.
        model_hint (None | str | Unset):
        provider_hint (LLMCompleteRequestProviderHint | Unset):  Default: LLMCompleteRequestProviderHint.AUTO.
        response_format (LLMCompleteRequestResponseFormat | Unset):  Default: LLMCompleteRequestResponseFormat.TEXT.
        temperature (float | Unset):  Default: 0.2.
    """

    messages: list[Message]
    task_class: LLMCompleteRequestTaskClass
    max_tokens: int | Unset = 1024
    model_hint: None | str | Unset = UNSET
    provider_hint: LLMCompleteRequestProviderHint | Unset = LLMCompleteRequestProviderHint.AUTO
    response_format: LLMCompleteRequestResponseFormat | Unset = (
        LLMCompleteRequestResponseFormat.TEXT
    )
    temperature: float | Unset = 0.2
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        messages = []
        for messages_item_data in self.messages:
            messages_item = messages_item_data.to_dict()
            messages.append(messages_item)

        task_class = self.task_class.value

        max_tokens = self.max_tokens

        model_hint: None | str | Unset
        if isinstance(self.model_hint, Unset):
            model_hint = UNSET
        else:
            model_hint = self.model_hint

        provider_hint: str | Unset = UNSET
        if not isinstance(self.provider_hint, Unset):
            provider_hint = self.provider_hint.value

        response_format: str | Unset = UNSET
        if not isinstance(self.response_format, Unset):
            response_format = self.response_format.value

        temperature = self.temperature

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "messages": messages,
                "task_class": task_class,
            }
        )
        if max_tokens is not UNSET:
            field_dict["max_tokens"] = max_tokens
        if model_hint is not UNSET:
            field_dict["model_hint"] = model_hint
        if provider_hint is not UNSET:
            field_dict["provider_hint"] = provider_hint
        if response_format is not UNSET:
            field_dict["response_format"] = response_format
        if temperature is not UNSET:
            field_dict["temperature"] = temperature

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.message import Message

        d = dict(src_dict)
        messages = []
        _messages = d.pop("messages")
        for messages_item_data in _messages:
            messages_item = Message.from_dict(messages_item_data)

            messages.append(messages_item)

        task_class = LLMCompleteRequestTaskClass(d.pop("task_class"))

        max_tokens = d.pop("max_tokens", UNSET)

        def _parse_model_hint(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        model_hint = _parse_model_hint(d.pop("model_hint", UNSET))

        _provider_hint = d.pop("provider_hint", UNSET)
        provider_hint: LLMCompleteRequestProviderHint | Unset
        if isinstance(_provider_hint, Unset):
            provider_hint = UNSET
        else:
            provider_hint = LLMCompleteRequestProviderHint(_provider_hint)

        _response_format = d.pop("response_format", UNSET)
        response_format: LLMCompleteRequestResponseFormat | Unset
        if isinstance(_response_format, Unset):
            response_format = UNSET
        else:
            response_format = LLMCompleteRequestResponseFormat(_response_format)

        temperature = d.pop("temperature", UNSET)

        llm_complete_request = cls(
            messages=messages,
            task_class=task_class,
            max_tokens=max_tokens,
            model_hint=model_hint,
            provider_hint=provider_hint,
            response_format=response_format,
            temperature=temperature,
        )

        llm_complete_request.additional_properties = d
        return llm_complete_request

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
