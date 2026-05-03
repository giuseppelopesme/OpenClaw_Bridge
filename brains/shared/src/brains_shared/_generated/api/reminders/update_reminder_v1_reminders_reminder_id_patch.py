from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.reminders_update_request import RemindersUpdateRequest
from ...models.update_reminder_v1_reminders_reminder_id_patch_response_update_reminder_v1_reminders_reminder_id_patch import (
    UpdateReminderV1RemindersReminderIdPatchResponseUpdateReminderV1RemindersReminderIdPatch,
)
from ...types import Response


def _get_kwargs(
    reminder_id: str,
    *,
    body: RemindersUpdateRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "patch",
        "url": "/v1/reminders/{reminder_id}".format(
            reminder_id=quote(str(reminder_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    HTTPValidationError
    | UpdateReminderV1RemindersReminderIdPatchResponseUpdateReminderV1RemindersReminderIdPatch
    | None
):
    if response.status_code == 200:
        response_200 = UpdateReminderV1RemindersReminderIdPatchResponseUpdateReminderV1RemindersReminderIdPatch.from_dict(
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
    HTTPValidationError
    | UpdateReminderV1RemindersReminderIdPatchResponseUpdateReminderV1RemindersReminderIdPatch
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
    body: RemindersUpdateRequest,
) -> Response[
    HTTPValidationError
    | UpdateReminderV1RemindersReminderIdPatchResponseUpdateReminderV1RemindersReminderIdPatch
]:
    """Update Reminder

    Args:
        reminder_id (str):
        body (RemindersUpdateRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | UpdateReminderV1RemindersReminderIdPatchResponseUpdateReminderV1RemindersReminderIdPatch]
    """

    kwargs = _get_kwargs(
        reminder_id=reminder_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    reminder_id: str,
    *,
    client: AuthenticatedClient | Client,
    body: RemindersUpdateRequest,
) -> (
    HTTPValidationError
    | UpdateReminderV1RemindersReminderIdPatchResponseUpdateReminderV1RemindersReminderIdPatch
    | None
):
    """Update Reminder

    Args:
        reminder_id (str):
        body (RemindersUpdateRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | UpdateReminderV1RemindersReminderIdPatchResponseUpdateReminderV1RemindersReminderIdPatch
    """

    return sync_detailed(
        reminder_id=reminder_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    reminder_id: str,
    *,
    client: AuthenticatedClient | Client,
    body: RemindersUpdateRequest,
) -> Response[
    HTTPValidationError
    | UpdateReminderV1RemindersReminderIdPatchResponseUpdateReminderV1RemindersReminderIdPatch
]:
    """Update Reminder

    Args:
        reminder_id (str):
        body (RemindersUpdateRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | UpdateReminderV1RemindersReminderIdPatchResponseUpdateReminderV1RemindersReminderIdPatch]
    """

    kwargs = _get_kwargs(
        reminder_id=reminder_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    reminder_id: str,
    *,
    client: AuthenticatedClient | Client,
    body: RemindersUpdateRequest,
) -> (
    HTTPValidationError
    | UpdateReminderV1RemindersReminderIdPatchResponseUpdateReminderV1RemindersReminderIdPatch
    | None
):
    """Update Reminder

    Args:
        reminder_id (str):
        body (RemindersUpdateRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | UpdateReminderV1RemindersReminderIdPatchResponseUpdateReminderV1RemindersReminderIdPatch
    """

    return (
        await asyncio_detailed(
            reminder_id=reminder_id,
            client=client,
            body=body,
        )
    ).parsed
