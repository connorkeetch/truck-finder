from datetime import datetime, timezone

from conftest import FakeAdapter, listing, vin

from rivian_finder import negotiation, pipeline, queries
from rivian_finder.models import FetchResult

NOW = datetime(2026, 10, 20, tzinfo=timezone.utc)


def test_price_moves_counts_drops_not_increases():
    m = negotiation.price_moves([("t1", 60000), ("t2", 60000), ("t3", 58500), ("t4", 59000), ("t5", 57000)])
    assert (m["drops"], m["dropped"], m["last_drop_at"]) == (2, 3500, "t5")
    assert m["total_change"] == -3000 and m["peak"] == 60000


def test_days_listed_takes_longest_evidence():
    ls = [{"listed_at": "2026-09-20T00:00:00Z", "first_seen_at": "2026-10-18T00:00:00Z", "days_on_market": None},
          {"listed_at": None, "first_seen_at": "2026-10-19T00:00:00Z", "days_on_market": 75}]
    assert negotiation.days_listed(ls, NOW) == (75, None, "MarketCheck days-on-market")
    days, since, src = negotiation.days_listed(ls[:1], NOW)
    assert (days, since, src) == (30, "2026-09-20", "provider's first-seen date")
    assert negotiation.days_listed([{"first_seen_at": "2026-10-10T00:00:00Z"}], NOW)[2] == "first seen by Truck Finder"


def test_leverage_levels():
    assert negotiation.leverage(75, 0, 0)[0] == "High"
    assert negotiation.leverage(10, 2, 3000)[0] == "High"
    assert negotiation.leverage(35, 0, 0)[0] == "Medium"
    assert negotiation.leverage(5, 1, 1000) == ("Medium", "listed 5 days, 1 price drop (−$1,000)")
    assert negotiation.leverage(5, 0, 0)[0] == "Low"
    assert negotiation.leverage(None, 0, 0)[0] == "Unknown"


def test_inventory_has_negotiation_columns(conn, settings):
    a = FakeAdapter("marketcheck", [
        FetchResult([listing("marketcheck", sid="m1", vin=vin(1), price=60000, days_on_market=80,
                             seller_phone="(801) 555-0100")], True, "s"),
        FetchResult([listing("marketcheck", sid="m1", vin=vin(1), price=58000, days_on_market=81)], True, "s")])
    pipeline.run_search(conn, [a], {})
    pipeline.run_search(conn, [a], {})
    row = queries.inventory_frame(conn, settings).iloc[0]
    assert row["days_listed"] == 81 and row["price_drops"] == 1 and row["dropped_total"] == 2000
    assert row["leverage"] == "High" and row["seller_phone"] == "(801) 555-0100"
