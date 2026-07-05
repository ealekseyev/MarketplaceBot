#!/usr/bin/env python3
"""Tests for internal fb_marketplace listing SQLite cache."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fb_marketplace.listing_cache import ListingCache
from fb_marketplace.models import ListingDetail


def _sample_listing() -> ListingDetail:
    return ListingDetail(
        url="https://www.facebook.com/marketplace/item/257847537400459",
        title="1970 mopar bench seat",
        description="700 dollars firm",
        price="$700",
        condition="Used - Good",
        seller_name="Dennis Kolpakov",
        location_city="San Jose",
        location_state="CA",
    )


def test_put_and_get_within_ttl(db_path: Path) -> None:
    listing = _sample_listing()
    with ListingCache(db_path) as cache:
        cache.put("257847537400459", listing)
        got = cache.get("257847537400459")
    assert got is not None
    assert got.title == listing.title
    assert got.price == listing.price
    assert got.location_city == "San Jose"
    print("OK put + get within TTL")


def test_expired_entry_returns_none(db_path: Path) -> None:
    listing = _sample_listing()
    expired_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with ListingCache(db_path) as cache:
        cache.put("257847537400459", listing)
        cache._conn.execute(
            "UPDATE listings SET expires_at = ? WHERE listing_id = ?",
            (expired_at, "257847537400459"),
        )
        cache._conn.commit()
        assert cache.get("257847537400459") is None
    print("OK expired entry evicted")


def test_separate_listing_ids(db_path: Path) -> None:
    a = _sample_listing()
    b = ListingDetail(
        url="https://www.facebook.com/marketplace/item/548864263902627",
        title="Mercedes door panel",
        price="$50",
    )
    with ListingCache(db_path) as cache:
        cache.put("257847537400459", a)
        cache.put("548864263902627", b)
        got_a = cache.get("257847537400459")
        got_b = cache.get("548864263902627")
    assert got_a is not None and got_a.title == a.title
    assert got_b is not None and got_b.title == b.title
    print("OK separate listing ids")


def test_from_dict_round_trip() -> None:
    listing = _sample_listing()
    payload = listing.to_dict()
    restored = ListingDetail.from_dict(payload)
    assert restored.url == listing.url
    assert restored.title == listing.title
    assert restored.location_city == listing.location_city
    assert restored.location_state == listing.location_state
    print("OK ListingDetail.from_dict round-trip")


def test_from_dict_id_only() -> None:
    restored = ListingDetail.from_dict(
        {
            "id": "123456789",
            "title": "Test item",
            "price": "$10",
            "location": {"city": "Austin", "state": "TX"},
        }
    )
    assert restored.url == "https://www.facebook.com/marketplace/item/123456789"
    assert restored.title == "Test item"
    print("OK from_dict with id only")


def test_stored_json_shape(db_path: Path) -> None:
    listing = _sample_listing()
    with ListingCache(db_path) as cache:
        cache.put("257847537400459", listing)
        row = cache._conn.execute(
            "SELECT data FROM listings WHERE listing_id = ?",
            ("257847537400459",),
        ).fetchone()
    assert row is not None
    payload = json.loads(row["data"])
    assert payload["id"] == "257847537400459"
    assert payload["title"] == listing.title
    assert payload["location"]["city"] == "San Jose"
    print("OK stored JSON shape")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "listings.sqlite"
        test_from_dict_round_trip()
        test_from_dict_id_only()
        test_put_and_get_within_ttl(db_path)
        test_expired_entry_returns_none(db_path)
        test_separate_listing_ids(db_path)
        test_stored_json_shape(db_path)
    print("All listing cache tests passed.")


if __name__ == "__main__":
    main()
