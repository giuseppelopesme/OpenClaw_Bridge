from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.draft_out import DraftOut
from ...models.draft_patch_request import DraftPatchRequest
from ...models.http_validation_error import HTTPValidationError
from ...types import Response


def _get_kwargs(
    draft_id: str,
    *,
    body: DraftPatchRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "patch",
        "url": "/v1/agent/drafts/{draft_id}".format(
            draft_id=quote(str(draft_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> DraftOut | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = DraftOut.from_dict(response.json())

        return response_200

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[DraftOut | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    draft_id: str,
    *,
    client: AuthenticatedClient | Client,
    body: DraftPatchRequest,
) -> Response[DraftOut | HTTPValidationError]:
    """Patch Draft

    Args:
        draft_id (str):
        body (DraftPatchRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DraftOut | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        draft_id=draft_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    draft_id: str,
    *,
    client: AuthenticatedClient | Client,
    body: DraftPatchRequest,
) -> DraftOut | HTTPValidationError | None:
    """Patch Draft

    Args:
        draft_id (str):
        body (DraftPatchRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DraftOut | HTTPValidationError
    """

    return sync_detailed(
        draft_id=draft_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    draft_id: str,
    *,
    client: AuthenticatedClient | Client,
    body: DraftPatchRequest,
) -> Response[DraftOut | HTTPValidationError]:
    """Patch Draft

    Args:
        draft_id (str):
        body (DraftPatchRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DraftOut | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        draft_id=draft_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    draft_id: str,
    *,
    client: AuthenticatedClient | Client,
    body: DraftPatchRequest,
) -> DraftOut | HTTPValidationError | None:
    """Patch Draft

    Args:
        draft_id (str):
        body (DraftPatchRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DraftOut | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            draft_id=draft_id,
            client=client,
            body=body,
        )
    ).parsed
