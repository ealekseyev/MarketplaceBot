from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from fb_marketplace.timeparse import age_seconds, first_timestamp_in_text, parse_relative_timestamp


class TimeParseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 6, 29, 12, 0, 0).astimezone()

    def test_relative_minutes(self) -> None:
        parsed = parse_relative_timestamp("5m", now=self.now)
        self.assertEqual(parsed, self.now - timedelta(minutes=5))

    def test_yesterday_with_time(self) -> None:
        parsed = parse_relative_timestamp("Yesterday at 3:15 PM", now=self.now)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.date().isoformat(), "2026-06-28")
        self.assertEqual(parsed.hour, 15)
        self.assertEqual(parsed.minute, 15)

    def test_first_timestamp_in_text(self) -> None:
        label, parsed = first_timestamp_in_text("John Doe\nCan you do $40?\n2h", now=self.now)
        self.assertEqual(label, "2h")
        self.assertEqual(parsed, self.now - timedelta(hours=2))

    def test_age_seconds(self) -> None:
        timestamp = self.now - timedelta(seconds=75)
        self.assertEqual(age_seconds(timestamp, now=self.now), 75)


if __name__ == "__main__":
    unittest.main()
