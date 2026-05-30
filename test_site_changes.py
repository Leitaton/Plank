"""Unit tests for the site-checker changes (classifier + URL extraction)."""

import sys

from utils.checkers import classify_response
from handlers.admin import _normalize_site, _extract_sites_from_text


def test_classify():
    cases = {
        "CARD_DECLINED": (True, "declined"),
        "DO_NOT_HONOR": (True, "declined"),
        "INSUFFICIENT_FUNDS": (True, "declined"),
        "3DS_REQUIRED": (True, "3d"),
        "AUTHENTICATION_REQUIRED": (True, "3d"),
        "CHARGED": (True, "approved"),
        "THANK_YOU": (True, "approved"),
        "ORDER_PLACED": (True, "order_placed"),
        "EXPIRED_CARD": (False, ""),
        "NO_PRODUCT": (False, ""),
        "": (False, ""),
    }
    for resp, expected in cases.items():
        got = classify_response(resp)
        assert got == expected, f"classify({resp!r}) = {got}, expected {expected}"
    print(f"PASS: classify_response ({len(cases)} cases)")


def test_normalize():
    cases = {
        "https://example.com/products/cool-thing": "example.com",
        "http://shop.example.co.uk/": "shop.example.co.uk",
        "example.com | approved": "example.com",
        "www.Example.com": "example.com",
        "example.com:443/cart": "example.com",
        "user:pass@store.example.com": "store.example.com",
        "  KYLIEBABY.COM  ": "kyliebaby.com",
        "https://a.b.c.myshopify.com | 3d": "a.b.c.myshopify.com",
        "not a domain": None,
        "4111111111111111|12|2030|123": None,
        "": None,
    }
    for raw, expected in cases.items():
        got = _normalize_site(raw)
        assert got == expected, f"normalize({raw!r}) = {got!r}, expected {expected!r}"
    print(f"PASS: _normalize_site ({len(cases)} cases)")


def test_extract():
    text = (
        "https://shopone.com/products/x | approved\n"
        "shoptwo.com | declined\n"
        "garbage line with no domain\n"
        "www.shopone.com\n"            # dup of shopone.com after normalize
        "http://shop.three.io:443/cart\n"
        "4111111111111111|12|2030|123\n"
    )
    got = _extract_sites_from_text(text)
    assert got == ["shopone.com", "shoptwo.com", "shop.three.io"], got
    print(f"PASS: _extract_sites_from_text -> {got}")


if __name__ == "__main__":
    test_classify()
    test_normalize()
    test_extract()
    print("\nALL TESTS PASSED")
    sys.exit(0)
