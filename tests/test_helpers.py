from __future__ import annotations

import unittest

from fb_marketplace.helpers import extract_listing_id, normalize_listing_url


class NormalizeListingUrlTests(unittest.TestCase):
    def test_strips_tracking_query_params(self) -> None:
        raw = (
            "https://www.facebook.com/marketplace/item/1345087446953812/"
            "?notif_id=1783029655287526&notif_t=marketplace_seller_insights&ref=notif"
        )
        self.assertEqual(
            normalize_listing_url(raw),
            "https://www.facebook.com/marketplace/item/1345087446953812",
        )

    def test_accepts_bare_item_id(self) -> None:
        self.assertEqual(
            normalize_listing_url("1345087446953812"),
            "https://www.facebook.com/marketplace/item/1345087446953812",
        )

    def test_extract_listing_id_matches_canonical_url(self) -> None:
        canonical = "https://www.facebook.com/marketplace/item/1345087446953812"
        self.assertEqual(extract_listing_id(canonical), "1345087446953812")
        self.assertEqual(normalize_listing_url(canonical), canonical)


if __name__ == "__main__":
    unittest.main()
