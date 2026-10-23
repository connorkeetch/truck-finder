"""Fixing a wrong seller link: your own links are corrected in place; a provider's link is overridden for good."""
import pytest
from conftest import listing, vin

from rivian_finder import pipeline, queries, services


def _row(conn, settings, v):
    inv = queries.inventory_frame(conn, settings)
    return inv[inv["vin"] == v].iloc[0]


def test_fix_my_own_link_in_place(conn, settings):
    v = vin(951)
    pipeline.import_listings(conn, [listing("autodev", vin=v, url=f"https://www.autolist.com/rivian-r1t#vin={v}")], "run")
    pipeline.import_listings(conn, [listing("dealer", import_method="manual", vin=v, url="https://wrong-dealer.example/vdp/1")],
                             "manual_entry")
    row = _row(conn, settings, v)
    assert row["seller_url"] == "https://wrong-dealer.example/vdp/1"
    assert services.set_seller_link(conn, int(row["vehicle_id"]), int(row["seller_listing_id"]),
                                    "https://right-dealer.example/used/2024-rivian-r1t") == "fixed"
    row = _row(conn, settings, v)
    assert row["seller_url"] == "https://right-dealer.example/used/2024-rivian-r1t" and not row["seller_link_fixed"]
    assert conn.execute("SELECT COUNT(*) FROM listings WHERE url LIKE '%wrong-dealer%'").fetchone()[0] == 0


def test_provider_link_override_survives_the_next_search(conn, settings):
    v = vin(952)
    nl = listing("autodev", vin=v, url="https://some-dealer.example/vdp/9")
    pipeline.import_listings(conn, [nl], "run")
    row = _row(conn, settings, v)
    assert services.set_seller_link(conn, int(row["vehicle_id"]), int(row["seller_listing_id"]),
                                    "https://real-dealer.example/vdp/9") == "overridden"
    pipeline.import_listings(conn, [listing("autodev", vin=v, url="https://some-dealer.example/vdp/9")], "run")   # next search
    row = _row(conn, settings, v)
    assert row["seller_url"] == "https://real-dealer.example/vdp/9" and row["seller_link_fixed"]


def test_remove_wrong_provider_link_brings_back_find_seller(conn, settings):
    v = vin(953)
    pipeline.import_listings(conn, [listing("autodev", vin=v, url="https://some-dealer.example/vdp/10")], "run")
    row = _row(conn, settings, v)
    assert services.set_seller_link(conn, int(row["vehicle_id"]), int(row["seller_listing_id"]), "") == "hidden"
    row = _row(conn, settings, v)
    assert row["seller_url"] == "" and row["find_seller_url"]


def test_guards(conn, settings):
    a, b = vin(954), vin(955)
    pipeline.import_listings(conn, [listing("dealer", import_method="manual", vin=a, url="https://a.example/vdp/1"),
                                    listing("dealer", import_method="manual", vin=b, url="https://b.example/vdp/2")],
                             "manual_entry")
    ra = _row(conn, settings, a)
    with pytest.raises(ValueError, match="different truck"):
        services.set_seller_link(conn, int(ra["vehicle_id"]), int(ra["seller_listing_id"]), "https://b.example/vdp/2")
    with pytest.raises(ValueError, match="only listing"):
        services.set_seller_link(conn, int(ra["vehicle_id"]), int(ra["seller_listing_id"]), "")
    with pytest.raises(ValueError, match="http"):
        services.set_seller_link(conn, int(ra["vehicle_id"]), int(ra["seller_listing_id"]), "dealer.example/vdp")
