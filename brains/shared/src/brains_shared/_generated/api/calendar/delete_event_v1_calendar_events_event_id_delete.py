from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.delete_event_v1_calendar_events_event_id_delete_response_delete_event_v1_calendar_events_event_id_delete import (
    DeleteEventV1CalendarEventsEventIdDeleteResponseDeleteEventV1CalendarEventsEventIdDelete,
)
from ...models.http_validation_error import HTTPValidationError
from ...types import Response


def _get_kwargs(
    event_id: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "delete",
        "url": "/v1/calendar/events/{event_id}".format(
            event_id=quote(str(event_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    DeleteEventV1CalendarEventsEventIdDeleteResponseDeleteEventV1CalendarEventsEventIdDelete
    | HTTPValidationError
    | None
):
    if response.status_code == 200:
        response_200 = DeleteEventV1CalendarEventsEventIdDeleteResponseDeleteEventV1CalendarEventsEventIdDelete.from_dict(
            response.json()
        )

        return response_200

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[
    DeleteEventV1CalendarEventsEventIdDeleteResponseDeleteEventV1CalendarEventsEventIdDelete
    | HTTPValidationError
]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    event_id: str,
    *,
    client: AuthenticatedClient | Client,
) -> Response[
    DeleteEventV1CalendarEventsEventIdDeleteResponseDeleteEventV1CalendarEventsEventIdDelete
    | HTTPValidationError
]:
    """Delete Event

    Args:
        event_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DeleteEventV1CalendarEventsEventIdDeleteResponseDeleteEventV1CalendarEventsEventIdDelete | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        event_id=event_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    event_id: str,
    *,
    client: AuthenticatedClient | Client,
) -> (
    DeleteEventV1CalendarEventsEventIdDeleteResponseDeleteEventV1CalendarEventsEventIdDelete
    | HTTPValidationError
    | None
):
    """Delete Event

    Args:
        event_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DeleteEventV1CalendarEventsEventIdDeleteResponseDeleteEventV1CalendarEventsEventIdDelete | HTTPValidationError
    """

    return sync_detailed(
        event_id=event_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    event_id: str,
    *,
    client: AuthenticatedClient | Client,
) -> Response[
    DeleteEventV1CalendarEventsEventIdDeleteResponseDeleteEventV1CalendarEventsEventIdDelete
    | HTTPValidationError
]:
    """Delete Event

    Args:
        event_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DeleteEventV1CalendarEventsEventIdDeleteResponseDeleteEventV1CalendarEventsEventIdDelete | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        event_id=event_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    event_id: str,
    *,
    client: AuthenticatedClient | Client,
) -> (
    DeleteEventV1CalendarEventsEventIdDeleteResponseDeleteEventV1CalendarEventsEventIdDelete
    | HTTPValidationError
    | None
):
    """Delete Event

    Args:
        event_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DeleteEventV1CalendarEventsEventIdDeleteResponseDeleteEventV1CalendarEventsEventIdDelete | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            event_id=event_id,
            client=client,
        )
    ).parsed
