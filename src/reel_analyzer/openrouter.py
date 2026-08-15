"""Shared OpenRouter HTTP plumbing: auth headers, timeouts, retry-with-backoff."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

import httpx

from .config import OPENROUTER_BASE_URL, Config

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class OpenRouterError(RuntimeError):
    """A call to OpenRouter failed in a way the caller should see in plain language."""


def build_headers(config: Config) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.api_key}",
        "HTTP-Referer": config.referer,
        "X-Title": config.app_title,
    }


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def _backoff(attempt: int, retry_after: float | None) -> float:
    """Exponential backoff with jitter, honouring Retry-After when the server sends one."""
    if retry_after is not None:
        return min(retry_after, 30.0)
    return min(2.0**attempt, 30.0) * (0.5 + random.random() / 2)


def _describe_failure(response: httpx.Response) -> str:
    """Pull the human-readable bit out of an OpenRouter error body."""
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text[:300] or f"HTTP {response.status_code}"

    error = payload.get("error")
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    if isinstance(error, str):
        return error
    return f"HTTP {response.status_code}"


async def request_json(
    client: httpx.AsyncClient,
    config: Config,
    method: str,
    path: str,
    *,
    timeout: float,
    **kwargs: Any,
) -> dict[str, Any]:
    """Send one OpenRouter request, retrying transient failures, and return parsed JSON."""
    url = f"{OPENROUTER_BASE_URL}{path}"
    last_error = "unknown error"

    for attempt in range(config.max_retries):
        try:
            response = await client.request(
                method,
                url,
                headers=build_headers(config),
                timeout=timeout,
                **kwargs,
            )
        except httpx.TimeoutException:
            last_error = f"request timed out after {timeout:.0f}s"
        except httpx.HTTPError as exc:
            last_error = f"network error: {exc}"
        else:
            if response.status_code < 400:
                try:
                    return response.json()
                except ValueError as exc:
                    raise OpenRouterError(
                        f"OpenRouter returned a non-JSON response ({response.status_code})"
                    ) from exc

            last_error = _describe_failure(response)
            if response.status_code not in RETRYABLE_STATUS:
                raise OpenRouterError(last_error)

            delay = _backoff(attempt, _retry_after_seconds(response))
            log.warning(
                "OpenRouter %s %s -> %s; retrying in %.1fs (attempt %d/%d)",
                method,
                path,
                response.status_code,
                delay,
                attempt + 1,
                config.max_retries,
            )
            if attempt + 1 < config.max_retries:
                await asyncio.sleep(delay)
            continue

        # Timeout / network error path.
        if attempt + 1 < config.max_retries:
            delay = _backoff(attempt, None)
            log.warning("OpenRouter %s %s failed (%s); retrying in %.1fs", method, path, last_error, delay)
            await asyncio.sleep(delay)

    raise OpenRouterError(f"{last_error} (after {config.max_retries} attempts)")
