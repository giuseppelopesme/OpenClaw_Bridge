from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.reminders_list_response import RemindersListResponse
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    list_: None | str | Unset = UNSET,
    completed: bool | Unset = False,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_list_: None | str | Unset
    if isinstance(list_, Unset):
        json_list_ = UNSET
    else:
        json_list_ = list_
    params["list"] = json_list_

    params["completed"] = completed

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/v1/reminders",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | RemindersListResponse | None:
    if response.status_code == 200:
        response_200 = RemindersListResponse.from_dict(response.json())

        return response_200

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[HTTPValidationError | RemindersListResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    list_: None | str | Unset = UNSET,
    completed: bool | Unset = False,
) -> Response[HTTPValidationError | RemindersListResponse]:
    """List Reminders

    Args:
        list_ (None | str | Unset):
        completed (bool | Unset):  Default: False.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | RemindersListResponse]
    """

    kwargs = _get_kwargs(
        list_=list_,
        completed=completed,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    list_: None | str | Unset = UNSET,
    completed: bool | Unset = False,
) -> HTTPValidationError | RemindersListResponse | None:
    """List Reminders

    Args:
        list_ (None | str | Unset):
        completed (bool | Unset):  Default: False.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | RemindersListResponse
    """

    return sync_detailed(
        client=client,
        list_=list_,
        completed=completed,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    list_: None | str | Unset = UNSET,
    completed: bool | Unset = False,
) -> Response[HTTPValidationError | RemindersListResponse]:
    """List Reminders

    Args:
        list_ (None | str | Unset):
        completed (bool | Unset):  Default: False.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | RemindersListResponse]
    """

    kwargs = _get_kwargs(
        list_=list_,
        completed=completed,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    list_: None | str | Unset = UNSET,
    completed: bool | Unset = False,
) -> HTTPValidationError | RemindersListResponse | None:
    """List Reminders

    Args:
        list_ (None | str | Unset):
        completed (bool | Unset):  Default: False.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | RemindersListResponse
    """

    return (
        await asyncio_detailed(
            client=client,
            list_=list_,
            completed=completed,
        )
    ).parsed
