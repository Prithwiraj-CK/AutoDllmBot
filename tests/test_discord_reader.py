import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from discord_reader import emit_record, message_allowed, message_record, parse_channel_ids


class DiscordReaderTests(unittest.TestCase):
    def test_parse_channel_ids(self):
        self.assertEqual(
            parse_channel_ids("123, 456,123"),
            frozenset({123, 456}),
        )

    def test_parse_channel_ids_rejects_non_numeric_values(self):
        with self.assertRaises(ValueError):
            parse_channel_ids("123,not-an-id")

    def test_message_allowed_requires_allowlisted_guild_channel_and_non_bot(self):
        message = SimpleNamespace(
            channel=SimpleNamespace(id=123),
            guild=SimpleNamespace(id=999),
            author=SimpleNamespace(bot=False),
        )
        self.assertTrue(message_allowed(message, {123}))
        self.assertFalse(message_allowed(message, {456}))

        message.author.bot = True
        self.assertFalse(message_allowed(message, {123}))

    def test_message_record_is_json_safe(self):
        message = SimpleNamespace(
            id=42,
            guild=SimpleNamespace(id=999),
            channel=SimpleNamespace(id=123, name="support"),
            author=SimpleNamespace(id=7, display_name="Alice", name="alice"),
            created_at=__import__("datetime").datetime(2026, 1, 1),
            content="hello",
            attachments=[],
            jump_url="https://discord.com/channels/999/123/42",
        )
        record = message_record(message)
        json.dumps(record)
        self.assertEqual(record["channel_id"], "123")
        self.assertEqual(record["content"], "hello")

    def test_emit_record_can_append_jsonl(self):
        record = {"content": "hello"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "messages.jsonl"
            emit_record(record, path)
            self.assertEqual(json.loads(path.read_text()), record)


if __name__ == "__main__":
    unittest.main()
