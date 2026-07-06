from __future__ import annotations

from .store import MockStore

_DEFAULT_LISTINGS: list[dict[str, str]] = [
    {
        "listing_id": "723456789012345",
        "title": "1970 Mopar bench seat",
        "description": "Driver-quality bench seat from a 1970 Plymouth. Vinyl has wear but no tears. $700 firm.",
        "price": "$700",
        "condition": "Used - Good",
        "seller_name": "Evan",
        "location_city": "San Jose",
        "location_state": "CA",
    },
    {
        "listing_id": "834567890123456",
        "title": "Vintage Craftsman tool chest",
        "description": "9-drawer rolling chest, red, locks work. Some surface rust on handles.",
        "price": "$250",
        "condition": "Used - Fair",
        "seller_name": "Evan",
        "location_city": "Campbell",
        "location_state": "CA",
    },
    {
        "listing_id": "945678901234567",
        "title": "IKEA Kallax 4x4 shelf unit",
        "description": "White, assembled. Pick up only. Minor scuffs on one corner.",
        "price": "$60",
        "condition": "Used - Good",
        "seller_name": "Evan",
        "location_city": "Sunnyvale",
        "location_state": "CA",
    },
    {
        "listing_id": "156789012345678",
        "title": "DeWalt 20V drill/driver kit",
        "description": "Includes two batteries, charger, and soft case. Works great.",
        "price": "$120",
        "condition": "Used - Like new",
        "seller_name": "Evan",
        "location_city": "Mountain View",
        "location_state": "CA",
    },
]


def seed_default_listings(store: MockStore | None = None) -> int:
    """Insert default sample listings if they are not already present."""
    owned = store is None
    active = store or MockStore()
    try:
        return active.seed(_DEFAULT_LISTINGS)
    finally:
        if owned:
            active.close()
