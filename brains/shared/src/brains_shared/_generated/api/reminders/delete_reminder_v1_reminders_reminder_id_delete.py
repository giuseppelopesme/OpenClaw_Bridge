from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.delete_reminder_v1_reminders_reminder_id_delete_response_delete_reminder_v1_reminders_reminder_id_delete import (
    DeleteReminderV1RemindersReminderIdDeleteResponseDeleteReminderV1RemindersReminderIdDelete,
)
from ...models.http_validation_error import HTTPValidationError
from ...types import Response


def _get_kwargs(
    reminder_id: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "delete",
        "url": "/v1/reminders/{reminder_id}".format(
            reminder_id=quote(str(reminder_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    DeleteReminderV1RemindersReminderIdDeleteResponseDeleteReminderV1RemindersReminderIdDelete
    | HTTPValidationError
    | None
):
    if response.status_code == 200:
        response_200 = DeleteReminderV1RemindersReminderIdDeleteResponseDeleteReminderV1RemindersReminderIdDelete.from_dict(
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
    DeleteReminderV1RemindersReminderIdDeleteResponseDeleteReminderV1RemindersReminderIdDelete
    | HTTPValidationError
]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    reminder_id: str,
    *,
    client: AuthenticatedClient | Client,
) -> Response[
    DeleteReminderV1RemindersReminderIdDeleteResponseDeleteReminderV1RemindersReminderIdDelete
    | HTTPValidationError
]:
    """Delete Reminder

    Args:
        reminder_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DeleteReminderV1RemindersReminderIdDeleteResponseDeleteReminderV1RemindersReminderIdDelete | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        reminder_id=reminder_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    reminder_id: str,
    *,
    client: AuthenticatedClient | Client,
) -> (
    DeleteReminderV1RemindersReminderIdDeleteResponseDeleteReminderV1RemindersReminderIdDelete
    | HTTPValidationError
    | None
):
    """Delete Reminder

    Args:
        reminder_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DeleteReminderV1RemindersReminderIdDeleteResponseDeleteReminderV1RemindersReminderIdDelete | HTTPValidationError
    """

    return sync_detailed(
        reminder_id=reminder_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    reminder_id: str,
    *,
    client: AuthenticatedClient | Client,
) -> Response[
    DeleteReminderV1RemindersReminderIdDeleteResponseDeleteReminderV1RemindersReminderIdDelete
    | HTTPValidationError
]:
    """Delete Reminder

    Args:
        reminder_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DeleteReminderV1RemindersReminderIdDeleteResponseDeleteReminderV1RemindersReminderIdDelete | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        reminder_id=reminder_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    reminder_id: str,
    *,
    client: AuthenticatedClient | Client,
) -> (
    DeleteReminderV1RemindersReminderIdDeleteResponseDeleteReminderV1RemindersReminderIdDelete
    | HTTPValidationError
    | None
):
    """Delete Reminder

    Args:
        reminder_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DeleteReminderV1RemindersReminderIdDeleteResponseDeleteReminderV1RemindersReminderIdDelete | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            reminder_id=reminder_id,
            client=client,
        )
    ).parsed
