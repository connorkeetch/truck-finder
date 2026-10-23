"""Link checks use synthetic VINs, listing IDs, and stubbed HTTP responses."""
import pytest
import requests
from conftest import listing, vin

from rivian_finder import linkcheck, pipeline, queries

VIN = vin(804)


class Resp:
    def __init__(self, status=200, url="", text="", encoding="utf-8"):
        self.status_code, self.url, self.text, self.encoding = status, url, text, encoding

    def iter_content(self, chunk_size=65536):
        yield self.text.encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeSession:
    """Maps URL -> Resp (or exception); records every request."""

    def __init__(self, pages, robots="User-agent: *\nAllow: /\n"):
        self.pages, self.robots, self.calls = pages, robots, []

    def get(self, url, **kw):
        self.calls.append(url)
        if url.endswith("/robots.txt"):
            return Resp(200, url, self.robots) if isinstance(self.robots, str) else self.robots
        page = self.pages[url]
        if isinstance(page, Exception):
            raise page
        return page


def page(title="", h1="", body=""):
    return f"<html><head><title>{title}</title></head><body><h1>{h1}</h1>{body}</body></html>"


@pytest.mark.parametrize("url,status,final,html,expected", [
    (f"https://dealer.example/used-2024-Rivian-R1T-{VIN}", 200, f"https://dealer.example/used-2024-Rivian-R1T-{VIN}",
     page(f"2024 Rivian R1T | {VIN}"), ("ok", "page shows this VIN")),
    ("https://dealer.example/used/Rivian/2025-R1T-baa639d2ac18150404e3bc89", 200, "https://www.dealer.example/rivian/r1t",
     page("2 used Rivian R1T trucks for sale"), ("moved", "redirects to www.dealer.example/rivian/r1t")),
    ("https://dealer.example/vdp/123456", 404, "https://dealer.example/vdp/123456", page("Not Found"), ("gone", "HTTP 404")),
    ("https://dealer.example/vdp/123456", 410, "https://dealer.example/vdp/123456", "", ("gone", "HTTP 410")),
    ("https://dealer.example/vdp/123456", 200, "https://dealer.example/vdp/123456",
     page("Used Rivian", "This vehicle is no longer available"), ("maybe_gone", None)),
    ("https://www.carvana.com/vehicle/9000001", 403, "https://www.carvana.com/vehicle/9000001", page("Just a moment..."),
     ("blocked", None)),
    ("https://dealer.example/vdp/123456", 200, "https://dealer.example/vdp/123456", page("Access Denied"), ("blocked", None)),
    ("https://dealer.example/vdp/123456", 502, "https://dealer.example/vdp/123456", "", ("error", "HTTP 502")),
])
def test_classify(url, status, final, html, expected):
    result, note = linkcheck.classify(url, status, final, html)
    assert result == expected[0]
    if expected[1]:
        assert note == expected[1]


def test_redirect_that_keeps_the_listing_id_is_fine():
    url = "https://rivian.com/configurations/inventory/pre-owned/00000000000000000000000000000001"
    assert linkcheck.classify(url, 200, url + "/build", page("Configurations | Rivian"))[0] == "ok"


def test_ordinary_vdp_text_mentioning_sold_elsewhere_is_not_flagged():
    url = f"https://dealer.example/vdp/{VIN}"
    html = page(f"2024 Rivian R1T {VIN}", "2024 Rivian R1T Adventure", "<div>Recently sold vehicles</div>")
    assert linkcheck.classify(url, 200, url, html)[0] == "ok"


def test_search_page_links_are_not_requested():
    s = FakeSession({})
    out = linkcheck.check_host([f"https://www.autolist.com/rivian-r1t#vin={VIN}"], s, sleep=lambda _: None)
    assert out[f"https://www.autolist.com/rivian-r1t#vin={VIN}"][0] == "not_checkable" and s.calls == []


def test_robots_disallow_is_respected():
    url = f"https://www.carfax.com/vehicle/{VIN}"
    s = FakeSession({url: Resp(200, url, page(VIN))}, robots="User-agent: *\nDisallow: /vehicle/\n")
    out = linkcheck.check_host([url], s, sleep=lambda _: None)
    assert out[url][0] == "not_allowed" and s.calls == ["https://www.carfax.com/robots.txt"]


def test_blocked_site_is_not_retried():
    urls = [f"https://www.carvana.com/vehicle/{n}" for n in (1111111, 2222222, 3333333)]
    s = FakeSession({urls[0]: Resp(403, urls[0], page("Just a moment..."))})
    out = linkcheck.check_host(urls, s, sleep=lambda _: None)
    assert [out[u][0] for u in urls] == ["blocked"] * 3
    assert s.calls == ["https://www.carvana.com/robots.txt", urls[0]]          # one real request, then stop
    assert "not retried" in out[urls[1]][3]


def test_requests_to_one_site_are_spaced_out():
    urls = [f"https://dealer.example/vdp/{n}" for n in (100001, 100002, 100003)]
    s = FakeSession({u: Resp(200, u, page("Rivian R1T")) for u in urls})
    waits = []
    linkcheck.check_host(urls, s, delay=2.5, sleep=waits.append)
    assert waits == [2.5, 2.5]


def test_network_error_is_reported_not_raised():
    url = "https://dealer.example/vdp/100001"
    s = FakeSession({url: requests.ConnectionError("down")})
    assert linkcheck.check_host([url], s, sleep=lambda _: None)[url][:2] == ("error", None)


def test_check_all_saves_results_and_inventory_shows_them(conn, settings):
    good, dead = vin(801), vin(802)
    pipeline.import_listings(conn, [listing("dealer", import_method="manual", vin=good, url=f"https://a.example/vdp/{good}"),
                                    listing("dealer", import_method="manual", vin=dead, url="https://b.example/vdp/555555")],
                             "manual_entry")
    pages = {f"https://a.example/vdp/{good}": Resp(200, f"https://a.example/vdp/{good}", page(good)),
             "https://b.example/vdp/555555": Resp(404, "https://b.example/vdp/555555", "")}
    summary = linkcheck.check_all(conn, session_factory=lambda: FakeSession(pages), sleep=lambda _: None)
    assert summary["counts"] == {"ok": 1, "gone": 1} and summary["problems"] == ["https://b.example/vdp/555555"]
    assert "1 live, 1 dead or moved" in linkcheck.summary_text(summary)
    inv = queries.inventory_frame(conn, settings).set_index("vin")
    assert inv.loc[good, "link_result"] == "ok" and inv.loc[dead, "link_result"] == "gone"
    assert linkcheck.label("gone") == "✗ dead link" and linkcheck.label("") == ""
    assert inv.loc[dead, "find_seller_url"]          # a dead seller link gets a 'find it again' search


def test_only_active_real_listings_are_checked(conn):
    v = vin(803)
    pipeline.import_listings(conn, [listing("dealer", import_method="manual", vin=v, url="https://c.example/vdp/777777")],
                             "manual_entry")
    assert linkcheck.urls_to_check(conn) == ["https://c.example/vdp/777777"]
    conn.execute("UPDATE listings SET status='removed'")
    assert linkcheck.urls_to_check(conn) == []


def test_listing_network_click_through_links_are_not_judged():
    """A Vast click-through token expires (410) while the truck is still for sale — never call that a dead truck."""
    from rivian_finder import links
    url = "http://details.vast.com/details/cars/ob-00000000000000000000000000000001/?pl=20&context=synthetic"
    s = FakeSession({url: Resp(410, url, "")})
    out = linkcheck.check_host([url], s, sleep=lambda _: None)
    assert out[url][0] == "not_checkable" and "expires" in out[url][3] and s.calls == []
    assert links.listing_role(url, "dealer")[0] == "aggregator"
