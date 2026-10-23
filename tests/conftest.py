import json
from pathlib import Path

import pytest

from rivian_finder import config, db
from rivian_finder.models import AttributeClaim, NormalizedListing
from rivian_finder.vin import with_check_digit

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def isolated_data_dirs(tmp_path, monkeypatch):
    """Never let a test touch the real data/ folder."""
    for name in ("DATA_DIR", "BACKUP_DIR", "EXPORT_DIR", "LOG_DIR"):
        monkeypatch.setattr(config, name, tmp_path / name.lower())
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "data_dir" / "rivian_finder.db")


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    yield c
    c.close()


@pytest.fixture
def settings(conn):
    """A saved EV-truck setup exercises compatibility independently of new-install defaults."""
    s = db.load_settings(conn)
    s["home_zip"] = "84020"
    s["filters"].update(year_min=2023, year_max=2026, max_price=65000, max_miles=45000)
    s["collection"].update(searches=None, include_other_brands=True, other_max_miles=45000,
                            other_max_distance=650, other_min_range=301, exclude_standard_range=True,
                            excluded_trims={"Ford": ["Pro"], "Chevrolet": ["WT"]},
                            marketcheck_zip="84020", mc_second_opinion=True)
    s["finance"].update(target_monthly=800, terms=[60, 66, 72], aprs=[4.49, 4.99],
                         sales_tax_rate=7.45, dmv_fees=400,
                         discounts=[{"seller": "carvana", "amount": 1000, "when": "trade"}])
    s["shipping"].update(fee_sellers=["carvana", "carmax"], included_sellers=["vroom"])
    return s


def load_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def vin(serial: int, year_code: str = "R", motor: str = "B") -> str:
    """Synthetic but checksum-valid R1T VIN (serial 9xxxxx is outside Rivian's real range so far)."""
    return with_check_digit(f"7FCTG{motor}AL0{year_code}N9{serial:05d}")


def listing(source="autodev", sid=None, **kw) -> NormalizedListing:
    base = dict(source_key=source, import_method="api", source_listing_id=sid, year=2024, make="Rivian",
                model="R1T", price=60000, miles=15000, seller_name="Test Motors", state="UT", city="Draper",
                zip="84020")
    base.update(kw)
    if base.get("vin") and sid is None and source in ("autodev",):
        base["source_listing_id"] = base["vin"]
    return NormalizedListing(**base)


class FakeAdapter:
    """Connector stand-in: returns queued FetchResults or raises queued exceptions."""

    def __init__(self, key, results, name=None, configured=True):
        self.key = key
        self.name = name or key
        self.results = list(results)
        self.configured = configured

    def is_configured(self):
        return (self.configured, "" if self.configured else "no key")

    def fetch(self, scope):
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


__all__ = ["AttributeClaim", "FakeAdapter", "listing", "load_json", "vin"]
