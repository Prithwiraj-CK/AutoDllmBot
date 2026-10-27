import unittest
from unittest.mock import AsyncMock, patch

from discord_user_reader import AuthenticationError, RestReader


class Response:
    def __init__(self, status, data):
        self.status, self.data = status, data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        return self.data


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, params=None):
        self.calls.append((url, params))
        return next(self.responses)


class RestReaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_catchup_paginates_delivers_chronologically_without_duplicates(self):
        session = Session([
            Response(200, [{"id": str(i)} for i in range(250, 150, -1)]),
            Response(200, [{"id": str(i)} for i in range(150, 50, -1)]),
            Response(200, [{"id": "250"}]),
        ])
        reader = RestReader(session, frozenset({123}))
        reader.cursors[123] = 100
        output = []
        await reader.poll_channel(123, lambda msg: output.append(int(msg["id"])))
        self.assertEqual(output, list(range(101, 251)))
        self.assertEqual(session.calls[1][1]["before"], "151")
        await reader.poll_channel(123, lambda msg: output.append(int(msg["id"])))
        self.assertEqual(len(output), 150)

    async def test_output_failure_preserves_unconsumed_cursor_for_retry(self):
        session = Session([Response(200, [{"id": "103"}, {"id": "102"}])])
        reader = RestReader(session, frozenset({123}))
        reader.cursors[123] = 100

        def consume(message):
            if message["id"] == "103":
                raise OSError("disk full")

        with self.assertRaises(OSError):
            await reader.poll_channel(123, consume)
        self.assertEqual(reader.cursors[123], 102)

    async def test_rate_limit_waits_full_retry_after(self):
        session = Session([
            Response(429, {"retry_after": 62}),
            Response(200, {"id": "123"}),
        ])
        reader = RestReader(session, frozenset({123}))
        with patch("discord_user_reader.asyncio.sleep", new_callable=AsyncMock) as sleep:
            result = await reader.get("/users/@me")
            sleep.assert_awaited_once_with(62.0)
        self.assertEqual(result["id"], "123")

    async def test_bad_auth_stops_without_retrying(self):
        session = Session([Response(401, {})])
        reader = RestReader(session, frozenset({123}))
        with self.assertRaises(AuthenticationError):
            await reader.get("/users/@me")
        self.assertEqual(len(session.calls), 1)

    async def test_outside_allowlist_never_sends_request(self):
        session = Session([])
        reader = RestReader(session, frozenset({123}))
        with self.assertRaises(ValueError):
            await reader.messages(456, limit=1)
        self.assertEqual(session.calls, [])


if __name__ == "__main__":
    unittest.main()
