from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.email_threads_list_response import EmailThreadsListResponse
from ...models.http_validation_error import HTTPValidationError
from ...models.list_threads_v1_email_threads_get_account import ListThreadsV1EmailThreadsGetAccount
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    account: ListThreadsV1EmailThreadsGetAccount,
    query: None | str | Unset = UNSET,
    limit: int | Unset = 20,
    before: None | str | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_account = account.value
    params["account"] = json_account

    json_query: None | str | Unset
    if isinstance(query, Unset):
        json_query = UNSET
    else:
        json_query = query
    params["query"] = json_query

    params["limit"] = limit

    json_before: None | str | Unset
    if isinstance(before, Unset):
        json_before = UNSET
    else:
        json_before = before
    params["before"] = json_before

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/v1/email/threads",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> EmailThreadsListResponse | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = EmailThreadsListResponse.from_dict(response.json())

        return response_200

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[EmailThreadsListResponse | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    account: ListThreadsV1EmailThreadsGetAccount,
    query: None | str | Unset = UNSET,
    limit: int | Unset = 20,
    before: None | str | Unset = UNSET,
) -> Response[EmailThreadsListResponse | HTTPValidationError]:
    """List Threads

    Args:
        account (ListThreadsV1EmailThreadsGetAccount):
        query (None | str | Unset):
        limit (int | Unset):  Default: 20.
        before (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EmailThreadsListResponse | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        account=account,
        query=query,
        limit=limit,
        before=before,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    account: ListThreadsV1EmailThreadsGetAccount,
    query: None | str | Unset = UNSET,
    limit: int | Unset = 20,
    before: None | str | Unset = UNSET,
) -> EmailThreadsListResponse | HTTPValidationError | None:
    """List Threads

    Args:
        account (ListThreadsV1EmailThreadsGetAccount):
        query (None | str | Unset):
        limit (int | Unset):  Default: 20.
        before (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EmailThreadsListResponse | HTTPValidationError
    """

    return sync_detailed(
        client=client,
        account=account,
        query=query,
        limit=limit,
        before=before,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    account: ListThreadsV1EmailThreadsGetAccount,
    query: None | str | Unset = UNSET,
    limit: int | Unset = 20,
    before: None | str | Unset = UNSET,
) -> Response[EmailThreadsListResponse | HTTPValidationError]:
    """List Threads

    Args:
        account (ListThreadsV1EmailThreadsGetAccount):
        query (None | str | Unset):
        limit (int | Unset):  Default: 20.
        before (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EmailThreadsListResponse | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        account=account,
        query=query,
        limit=limit,
        before=before,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    account: ListThreadsV1EmailThreadsGetAccount,
    query: None | str | Unset = UNSET,
    limit: int | Unset = 20,
    before: None | str | Unset = UNSET,
) -> EmailThreadsListResponse | HTTPValidationError | None:
    """List Threads

    Args:
        account (ListThreadsV1EmailThreadsGetAccount):
        query (None | str | Unset):
        limit (int | Unset):  Default: 20.
        before (None | str | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EmailThreadsListResponse | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            client=client,
            account=account,
            query=query,
            limit=limit,
            before=before,
        )
    ).parsed
