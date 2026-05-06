from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.draft_list_response import DraftListResponse
from ...models.http_validation_error import HTTPValidationError
from ...models.list_drafts_v1_agent_drafts_get_status_type_0 import (
    ListDraftsV1AgentDraftsGetStatusType0,
)
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    agent: None | str | Unset = UNSET,
    status: ListDraftsV1AgentDraftsGetStatusType0 | None | Unset = UNSET,
    limit: int | Unset = 50,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_agent: None | str | Unset
    if isinstance(agent, Unset):
        json_agent = UNSET
    else:
        json_agent = agent
    params["agent"] = json_agent

    json_status: None | str | Unset
    if isinstance(status, Unset):
        json_status = UNSET
    elif isinstance(status, ListDraftsV1AgentDraftsGetStatusType0):
        json_status = status.value
    else:
        json_status = status
    params["status"] = json_status

    params["limit"] = limit

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/v1/agent/drafts",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> DraftListResponse | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = DraftListResponse.from_dict(response.json())

        return response_200

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[DraftListResponse | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    agent: None | str | Unset = UNSET,
    status: ListDraftsV1AgentDraftsGetStatusType0 | None | Unset = UNSET,
    limit: int | Unset = 50,
) -> Response[DraftListResponse | HTTPValidationError]:
    """List Drafts

    Args:
        agent (None | str | Unset):
        status (ListDraftsV1AgentDraftsGetStatusType0 | None | Unset):
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DraftListResponse | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        agent=agent,
        status=status,
        limit=limit,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    agent: None | str | Unset = UNSET,
    status: ListDraftsV1AgentDraftsGetStatusType0 | None | Unset = UNSET,
    limit: int | Unset = 50,
) -> DraftListResponse | HTTPValidationError | None:
    """List Drafts

    Args:
        agent (None | str | Unset):
        status (ListDraftsV1AgentDraftsGetStatusType0 | None | Unset):
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DraftListResponse | HTTPValidationError
    """

    return sync_detailed(
        client=client,
        agent=agent,
        status=status,
        limit=limit,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    agent: None | str | Unset = UNSET,
    status: ListDraftsV1AgentDraftsGetStatusType0 | None | Unset = UNSET,
    limit: int | Unset = 50,
) -> Response[DraftListResponse | HTTPValidationError]:
    """List Drafts

    Args:
        agent (None | str | Unset):
        status (ListDraftsV1AgentDraftsGetStatusType0 | None | Unset):
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DraftListResponse | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        agent=agent,
        status=status,
        limit=limit,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    agent: None | str | Unset = UNSET,
    status: ListDraftsV1AgentDraftsGetStatusType0 | None | Unset = UNSET,
    limit: int | Unset = 50,
) -> DraftListResponse | HTTPValidationError | None:
    """List Drafts

    Args:
        agent (None | str | Unset):
        status (ListDraftsV1AgentDraftsGetStatusType0 | None | Unset):
        limit (int | Unset):  Default: 50.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DraftListResponse | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            client=client,
            agent=agent,
            status=status,
            limit=limit,
        )
    ).parsed
