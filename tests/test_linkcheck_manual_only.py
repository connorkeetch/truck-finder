"""Exercise Requests' real redirect handling against an in-memory adapter; never contact a site."""
import io

import pytest
import requests

from rivian_finder import linkcheck


class Pages(requests.adapters.BaseAdapter):
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def send(self, request, **kwargs):
        self.calls.append((request.url, dict(request.headers)))
        status, headers, text = self.pages[request.url]
        response = requests.Response()
        response.status_code, response.url, response.request = status, request.url, request
        response.headers.update(headers)
        response._content, response._content_consumed = text.encode(), True
        response.raw, response.encoding = io.BytesIO(response._content), "utf-8"
        return response

    def close(self):
        pass


def session_for(pages):
    session = requests.Session()
    session.trust_env = False
    adapter = Pages(pages)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session, adapter


@pytest.mark.parametrize("url", [
    "https://carfax.com/vehicle/123456", "https://www.carfax.com/VehicleHistory/p/Report.cfx?vin=TEST",
    "https://partner.carfax.com/report", "https://CARFAX.COM:443/report", "https://carfax.com./report",
    "https://%63arfax.com/report",
])
def test_direct_carfax_skips_both_robots_and_page(url):
    session, adapter = session_for({})
    result = linkcheck.check_host([url], session)[url]
    assert result == ("not_allowed", None, None, linkcheck.MANUAL_NOTE)
    assert adapter.calls == []
    assert result[0] not in linkcheck.PROBLEMS
    assert linkcheck.label(result[0]) == "? check"


@pytest.mark.parametrize("target", [
    "https://www.carfax.com/report", "//partner.carfax.com/report", "https://%63arfax.com/report",
])
def test_dealer_redirect_chain_stops_before_carfax(target):
    url, jump = "https://dealer.example/vdp/123456", "https://dealer.example/jump"
    robots = "https://dealer.example/robots.txt"
    session, adapter = session_for({
        robots: (200, {}, "User-agent: *\nAllow: /\n"),
        url: (302, {"Location": "/jump"}, ""), jump: (301, {"Location": target}, ""),
    })
    result = linkcheck.check_host([url], session)[url]
    assert result == ("not_allowed", 301, None, linkcheck.MANUAL_NOTE)
    assert [call[0] for call in adapter.calls] == [robots, url, jump]


def test_robots_redirect_to_carfax_stops_before_page_check():
    url, robots = "https://dealer.example/vdp/123456", "https://dealer.example/robots.txt"
    session, adapter = session_for({robots: (302, {"Location": "https://carfax.com/robots.txt"}, "")})
    results = linkcheck.check_host([url, "https://dealer.example/vdp/654321"], session)
    assert all(result[0] == "not_allowed" for result in results.values())
    assert [call[0] for call in adapter.calls] == [robots]


def test_manual_redirect_does_not_skip_delay_before_next_dealer_page():
    urls = ["https://dealer.example/vdp/123456", "https://dealer.example/vdp/654321"]
    session, adapter = session_for({
        "https://dealer.example/robots.txt": (200, {}, "User-agent: *\nAllow: /\n"),
        urls[0]: (302, {"Location": "https://carfax.com/report"}, ""),
        urls[1]: (200, {}, "<title>Used truck</title>"),
    })
    waits = []
    results = linkcheck.check_host(urls, session, delay=2.5, sleep=waits.append)
    assert [results[url][0] for url in urls] == ["not_allowed", "ok"]
    assert waits == [2.5]


def test_allowed_redirects_keep_requests_auth_stripping_and_session_hooks():
    url, final = "https://dealer.example/vdp/123456", "https://inventory.example/used/123456"
    robots = "https://dealer.example/robots.txt"
    session, adapter = session_for({
        robots: (200, {}, "User-agent: *\nAllow: /\n"), url: (302, {"Location": final}, ""),
        final: (200, {}, "<title>Used truck</title>"),
    })
    session.headers["Authorization"] = "Basic synthetic-test-value"
    observed = []
    session.hooks["response"].append(lambda response, **kw: observed.append(response.url))
    result = linkcheck.check_host([url], session)[url]
    assert result[:3] == ("ok", 200, final)
    assert observed == [robots, url, final]
    assert adapter.calls[1][1]["Authorization"] == "Basic synthetic-test-value"
    assert "Authorization" not in adapter.calls[2][1]


def test_redirect_loops_still_use_requests_limit():
    url, robots = "https://dealer.example/vdp/123456", "https://dealer.example/robots.txt"
    session, adapter = session_for({
        robots: (200, {}, "User-agent: *\nAllow: /\n"), url: (302, {"Location": url}, ""),
    })
    session.max_redirects = 2
    assert linkcheck.check_host([url], session)[url] == ("error", None, None, "TooManyRedirects")


@pytest.mark.parametrize("host", ["notcarfax.com", "carfax.com.dealer.example"])
def test_similarly_named_dealer_domains_are_not_carfax(host):
    url, robots = f"https://{host}/vdp/123456", f"https://{host}/robots.txt"
    session, adapter = session_for({
        robots: (200, {}, "User-agent: *\nAllow: /\n"), url: (200, {}, "<title>Used truck</title>"),
    })
    assert linkcheck.check_host([url], session)[url][0] == "ok"
    assert [call[0] for call in adapter.calls] == [robots, url]
