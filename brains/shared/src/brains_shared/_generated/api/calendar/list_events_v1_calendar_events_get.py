from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.calendar_list_response import CalendarListResponse
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    from_: str,
    to: str,
    calendar: None | str | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["from"] = from_

    params["to"] = to

    json_calendar: None | str | Unset
    if isinstance(calendar, Unset):
        json_calendar = UNSET
    else:
        json_calendar = calendar
    params["calendar"] = json_calendar

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/v1/calendar/events",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> CalendarListResponse | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = CalendarListResponse.from_dict(response.json())

        return response_200

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[CalendarListResponse | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    from_: str,
    to: str,
    calendar: None | str | Unset = UNSET,
) -> Response[CalendarListResponse | HTTPValidationError]:
    """List Events

    Args:
        from_ (str):
        to (str):
        calendar (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CalendarListResponse | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        from_=from_,
        to=to,
        calendar=calendar,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    from_: str,
    to: str,
    calendar: None | str | Unset = UNSET,
) -> CalendarListResponse | HTTPValidationError | None:
    """List Events

    Args:
        from_ (str):
        to (str):
        calendar (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CalendarListResponse | HTTPValidationError
    """

    return sync_detailed(
        client=client,
        from_=from_,
        to=to,
        calendar=calendar,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    from_: str,
    to: str,
    calendar: None | str | Unset = UNSET,
) -> Response[CalendarListResponse | HTTPValidationError]:
    """List Events

    Args:
        from_ (str):
        to (str):
        calendar (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CalendarListResponse | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        from_=from_,
        to=to,
        calendar=calendar,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    from_: str,
    to: str,
    calendar: None | str | Unset = UNSET,
) -> CalendarListResponse | HTTPValidationError | None:
    """List Events

    Args:
        from_ (str):
        to (str):
        calendar (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CalendarListResponse | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            client=client,
            from_=from_,
            to=to,
            calendar=calendar,
        )
    ).parsed
