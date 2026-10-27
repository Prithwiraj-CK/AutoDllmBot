"""Read messages from explicitly allowlisted Discord channels.

Bot mode uses discord.py and the Gateway. User mode uses read-only REST
polling through discord_user_reader.py. Select the mode with --auth or
DISCORD_AUTH; bot is the default.

Configuration is supplied through environment variables (or a local .env):

    DISCORD_BOT_TOKEN=...
    DISCORD_CHANNEL_IDS=123456789012345678,234567890123456789
    DISCORD_HISTORY_LIMIT=0
    DISCORD_MESSAGE_LOG=out/discord_messages.jsonl   # optional
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from dotenv import load_dotenv
except ImportError:  # Keep config helpers usable before dependencies are installed.
    def load_dotenv(*_args: Any, **_kwargs: Any) -> bool:
        return False


ROOT = Path(__file__).resolve().parent
log = logging.getLogger("discord-reader")


def parse_channel_ids(raw: str | None) -> frozenset[int]:
    """Parse a comma-separated channel allowlist, rejecting malformed IDs."""
    channel_ids: set[int] = set()
    for value in (raw or "").split(","):
        value = value.strip()
        if not value:
            continue
        if not value.isdigit():
            raise ValueError(f"Invalid Discord channel ID: {value!r}")
        channel_ids.add(int(value))
    return frozenset(channel_ids)


def message_allowed(message: Any, allowed_channel_ids: Iterable[int]) -> bool:
    """Return True only for non-bot messages in configured guild channels."""
    channel_id = getattr(getattr(message, "channel", None), "id", None)
    guild = getattr(message, "guild", None)
    author = getattr(message, "author", None)
    return (
        guild is not None
        and channel_id in set(allowed_channel_ids)
        and not bool(getattr(author, "bot", False))
    )


def message_record(message: Any) -> dict[str, Any]:
    """Convert a Discord message into a JSON-safe record without a token."""
    created_at = getattr(message, "created_at", None)
    if created_at is not None:
        created_at = created_at.astimezone(timezone.utc).isoformat()

    author = getattr(message, "author", None)
    channel = getattr(message, "channel", None)
    guild = getattr(message, "guild", None)
    return {
        "id": str(getattr(message, "id", "")),
        "guild_id": str(getattr(guild, "id", "")),
        "channel_id": str(getattr(channel, "id", "")),
        "channel_name": getattr(channel, "name", None),
        "author_id": str(getattr(author, "id", "")),
        "author_name": str(getattr(author, "display_name", getattr(author, "name", ""))),
        "created_at": created_at,
        "content": str(getattr(message, "content", "")),
        "attachments": [str(getattr(item, "url", "")) for item in (getattr(message, "attachments", None) or [])],
        "message_url": str(getattr(message, "jump_url", "")),
    }


def emit_record(record: dict[str, Any], log_path: Path | None = None) -> None:
    """Print one record and optionally append it to a local JSONL file."""
    print(json.dumps(record, ensure_ascii=False), flush=True)
    if log_path is None:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auth", choices=("bot", "user"), default=os.getenv("DISCORD_AUTH", "bot"))
    parser.add_argument("--check", action="store_true", help="In user mode, check channel access and exit without printing messages.")
    parser.add_argument(
        "--history",
        action="store_true",
        help="Read up to DISCORD_HISTORY_LIMIT existing messages on startup.",
    )
    return parser


def run_bot(read_history: bool = False) -> None:
    # Import only when the bot is actually run, so the pure config helpers can
    # be tested without installing the Discord client package.
    import discord

    load_dotenv(ROOT / ".env")
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("DISCORD_BOT_TOKEN is required; user tokens are not supported.")

    try:
        allowed_channel_ids = parse_channel_ids(os.getenv("DISCORD_CHANNEL_IDS"))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if not allowed_channel_ids:
        raise SystemExit("DISCORD_CHANNEL_IDS must contain at least one channel ID.")

    try:
        history_limit = max(0, int(os.getenv("DISCORD_HISTORY_LIMIT", "0")))
    except ValueError as exc:
        raise SystemExit("DISCORD_HISTORY_LIMIT must be a non-negative integer.") from exc

    raw_log_path = os.getenv("DISCORD_MESSAGE_LOG", "").strip()
    log_path = (ROOT / raw_log_path).resolve() if raw_log_path else None

    intents = discord.Intents.none()
    intents.guilds = True
    intents.messages = True
    intents.message_content = True
    client = discord.Client(intents=intents)
    history_loaded = False

    @client.event
    async def on_ready() -> None:
        nonlocal history_loaded
        log.info("Connected as %s", client.user)
        log.info("Reading %d allowlisted channel(s)", len(allowed_channel_ids))
        if not read_history or history_loaded or history_limit == 0:
            return

        history_loaded = True
        for channel_id in sorted(allowed_channel_ids):
            channel = client.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await client.fetch_channel(channel_id)
                except discord.DiscordException as exc:
                    log.warning("Could not access channel %s: %s", channel_id, exc)
                    continue
            if not hasattr(channel, "history"):
                log.warning("Configured channel %s is not a readable text channel", channel_id)
                continue
            try:
                messages = [
                    message async for message in channel.history(
                        limit=history_limit, oldest_first=True
                    )
                ]
            except discord.DiscordException as exc:
                log.warning("Could not read history for channel %s: %s", channel_id, exc)
                continue
            for message in messages:
                if message_allowed(message, allowed_channel_ids):
                    emit_record(message_record(message), log_path)

    @client.event
    async def on_message(message: Any) -> None:
        if message_allowed(message, allowed_channel_ids):
            emit_record(message_record(message), log_path)

    try:
        client.run(token, log_handler=None)
    except discord.LoginFailure as exc:
        raise SystemExit(
            "Discord rejected DISCORD_BOT_TOKEN. Copy a fresh bot token from "
            "Developer Portal → Application → Bot; do not use a user token, "
            "webhook token, client secret, or include the 'Bot ' prefix."
        ) from exc


def main() -> None:
    load_dotenv(ROOT / ".env")
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
    args = build_parser().parse_args()
    if args.auth not in ("bot", "user"):
        raise SystemExit("DISCORD_AUTH must be bot or user.")
    if args.auth == "user":
        from discord_user_reader import run
        run(read_history=args.history, once=args.check)
        return
    if args.check:
        raise SystemExit("--check is available with --auth user.")
    run_bot(read_history=args.history)


if __name__ == "__main__":
    main()
