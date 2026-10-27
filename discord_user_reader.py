"""Read allowlisted guild channels via REST with DISCORD_USER_TOKEN.

This transport only performs GET requests. It uses the account's existing
channel access and is not an officially supported Discord integration.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any

import aiohttp

from discord_reader import ROOT, emit_record, parse_channel_ids

log = logging.getLogger("discord-reader")
API = "https://discord.com/api/v10"


class AuthenticationError(RuntimeError):
    pass


class ChannelUnavailable(RuntimeError):
    pass


class ReadFailed(RuntimeError):
    pass


class RestReader:
    def __init__(self, session: Any, channel_ids: frozenset[int]):
        self.session = session
        self.channel_ids = channel_ids
        # A Discord snowflake boundary excludes history before this process
        # starts while retaining messages received during authentication.
        boundary = max(0, (int(time.time() * 1000) - 1420070400000) << 22)
        self.cursors = {channel_id: boundary for channel_id in channel_ids}

    async def get(self, path: str, params: dict | None = None) -> Any:
        for attempt in range(4):
            async with self.session.get(API + path, params=params) as response:
                if response.status == 401:
                    raise AuthenticationError("Discord rejected DISCORD_USER_TOKEN (401).")
                if response.status in (403, 404):
                    raise ChannelUnavailable("Channel unavailable or account has no access.")
                if response.status == 429:
                    data = await response.json()
                    delay = max(0.1, float(data.get("retry_after", 1)))
                    log.warning("Discord rate limit; waiting %.1f seconds", delay)
                    await asyncio.sleep(delay)
                    continue
                if response.status >= 500:
                    await asyncio.sleep(2 ** attempt)
                    continue
                if response.status != 200:
                    # Do not print response bodies, which may include content.
                    raise ReadFailed(f"Discord returned HTTP {response.status}.")
                return await response.json()
        raise ReadFailed("Discord request still unavailable after retries.")

    async def messages(self, channel_id: int, **params: Any) -> list[dict]:
        if channel_id not in self.channel_ids:
            raise ValueError("Channel is outside DISCORD_CHANNEL_IDS.")
        data = await self.get(f"/channels/{channel_id}/messages", params)
        if not isinstance(data, list):
            raise ReadFailed("Discord returned an invalid message page.")
        return data

    async def poll_channel(self, channel_id: int, consume: Any) -> None:
        cursor = self.cursors[channel_id]
        # Fetch backwards from the newest page to avoid losing intermediate
        # messages when more than 100 arrive between polls. No cursor advances
        # until all pages are fetched and each message is delivered.
        pending: dict[int, dict] = {}
        before = None
        while True:
            params = {"limit": 100}
            if before is not None:
                params["before"] = str(before)
            page = await self.messages(channel_id, **params)
            if not page:
                break
            for message in page:
                message_id = int(message["id"])
                if message_id > cursor:
                    pending[message_id] = message
            oldest = min(int(message["id"]) for message in page)
            if oldest <= cursor or len(page) < 100:
                break
            if before is not None and oldest >= before:
                raise ReadFailed("Discord pagination did not advance.")
            before = oldest
        for message_id in sorted(pending):
            consume(pending[message_id])
            self.cursors[channel_id] = message_id


def rest_record(message: dict, channel: dict) -> dict:
    author = message.get("author") or {}
    guild_id = str(channel["guild_id"])
    channel_id = str(channel["id"])
    message_id = str(message["id"])
    return {
        "id": message_id,
        "guild_id": guild_id,
        "channel_id": channel_id,
        "channel_name": channel.get("name"),
        "author_id": str(author.get("id", "")),
        "author_name": author.get("global_name") or author.get("username", ""),
        "created_at": message.get("timestamp"),
        "content": message.get("content", ""),
        "attachments": [item.get("url", "") for item in message.get("attachments", [])],
        "message_url": f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}",
    }


async def run_user_reader(read_history: bool = False, once: bool = False) -> None:
    token = os.getenv("DISCORD_USER_TOKEN", "").strip()
    if not token:
        raise SystemExit("Set DISCORD_USER_TOKEN in .env to use user mode.")
    try:
        channel_ids = parse_channel_ids(os.getenv("DISCORD_CHANNEL_IDS"))
        interval = float(os.getenv("DISCORD_POLL_SECONDS", "15"))
        history_limit = int(os.getenv("DISCORD_HISTORY_LIMIT", "0"))
        if interval < 10 or not 0 <= history_limit <= 100:
            raise ValueError("Poll interval must be at least 10s; history limit must be 0–100.")
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if not channel_ids:
        raise SystemExit("DISCORD_CHANNEL_IDS must contain at least one channel ID.")
    raw_path = os.getenv("DISCORD_MESSAGE_LOG", "").strip()
    log_path: Path | None = (ROOT / raw_path).resolve() if raw_path else None
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(
        headers={"Authorization": token}, timeout=timeout
    ) as session:
        reader = RestReader(session, channel_ids)
        account = await reader.get("/users/@me")
        if account.get("bot"):
            raise SystemExit("This is a bot account; use --auth bot with DISCORD_BOT_TOKEN.")
        log.info("Authenticated user account; checking %d configured channels", len(channel_ids))
        channels = {}
        for channel_id in sorted(channel_ids):
            try:
                channel = await reader.get(f"/channels/{channel_id}")
                if not channel.get("guild_id"):
                    log.warning("Skipping channel %s: only guild channels are supported", channel_id)
                    continue
                # Prove message access even if history is disabled.
                page = await reader.messages(channel_id, limit=history_limit if read_history and history_limit else 1)
                channels[channel_id] = channel
                log.info("Channel %s: readable", channel_id)
                if read_history and history_limit and not once:
                    for message in sorted(page, key=lambda item: int(item["id"])):
                        if not (message.get("author") or {}).get("bot"):
                            emit_record(rest_record(message, channel), log_path)
                        reader.cursors[channel_id] = max(reader.cursors[channel_id], int(message["id"]))
            except ChannelUnavailable:
                log.warning("Channel %s: unavailable or no access", channel_id)
        if not channels:
            raise SystemExit("No configured guild channels could be read.")
        if once:
            log.info("Access check complete: %d/%d channels readable", len(channels), len(channel_ids))
            return
        log.info("Reading %d channels every %.0fs", len(channels), interval)
        while True:
            for channel_id, channel in list(channels.items()):
                def consume(message: dict) -> None:
                    if not (message.get("author") or {}).get("bot"):
                        emit_record(rest_record(message, channel), log_path)
                try:
                    await reader.poll_channel(channel_id, consume)
                except ChannelUnavailable:
                    log.warning("Channel %s became unavailable; removing from poll loop", channel_id)
                    channels.pop(channel_id)
                except (ReadFailed, aiohttp.ClientError, asyncio.TimeoutError):
                    log.warning("Channel %s: transient read failure; retrying next poll", channel_id)
            if not channels:
                raise SystemExit("All configured channels became unavailable.")
            await asyncio.sleep(interval)


def run(read_history: bool = False, once: bool = False) -> None:
    try:
        asyncio.run(run_user_reader(read_history, once))
    except (AuthenticationError, ChannelUnavailable, ReadFailed) as exc:
        raise SystemExit(str(exc)) from None
    except (aiohttp.ClientError, asyncio.TimeoutError):
        raise SystemExit("Could not reach Discord. Check network access and retry.") from None
    except KeyboardInterrupt:
        log.info("Reader stopped")
