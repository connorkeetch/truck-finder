import random

import pandas as pd

from rivian_finder import deals


def market(n=60, seed=7):
    """Synthetic trucks priced by a known rule plus ±2% noise."""
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        year = rng.choice([2023, 2024, 2025])
        miles = rng.randint(5000, 50000)
        battery = rng.choice(["Large", "Max", "Unknown"])
        motor = rng.choice(["Dual", "Quad", "Unknown"])
        price = 52000 + 5000 * (year - 2023) - 0.15 * miles + {"Max": 4000}.get(battery, 0) + {"Quad": 8000}.get(motor, 0)
        rows.append({"vehicle_id": i, "year": year, "miles": miles, "battery": battery, "motor": motor,
                     "tonneau": "unknown", "price": round(price * (1 + rng.uniform(-0.02, 0.02))), "status": "active",
                     "title_status": "unknown", "accident_history": "unknown", "is_demo": False})
    return pd.DataFrame(rows)


def test_underpriced_and_overpriced_trucks_are_flagged():
    df = market()
    df.loc[0, ["year", "miles", "battery", "motor", "price"]] = [2024, 20000, "Large", "Dual", round(0.80 * (57000 - 3000))]
    df.loc[1, ["year", "miles", "battery", "motor", "price"]] = [2024, 20000, "Large", "Dual", round(1.12 * (57000 - 3000))]
    df.loc[4, ["year", "miles", "battery", "motor", "price"]] = [2023, 30000, "Large", "Dual", round(0.90 * 47500)]
    df.loc[5, ["year", "miles", "battery", "motor", "price", "title_status"]] = [
        2025, 10000, "Large", "Dual", round(0.80 * 60500), "clean"]
    out = deals.annotate(df)
    assert out.loc[0, "deal_label"] == "⚠ Check title" and out.loc[0, "deal_delta"] < -5000   # 20% under: suspicious
    assert "branded/rebuilt" in out.loc[0, "deal_note"]
    assert out.loc[4, "deal_label"] == "Great deal"                                          # 10% under
    assert out.loc[5, "deal_label"] == "Great deal"                                          # verified clean title
    assert out.loc[1, "deal_label"] == "Overpriced"
    fair = out.loc[6:, "deal_pct"].abs()
    assert (fair < 0.05).mean() > 0.9          # ordinary trucks land near their estimate
    assert "comparable 2024 Dual" in out.loc[0, "comps_text"]
    assert "similar trucks" in out.loc[0, "deal_note"]


def test_branded_title_is_not_advertised_as_a_deal():
    df = market()
    df.loc[3, ["price", "title_status"]] = [30000, "branded"]
    out = deals.annotate(df)
    assert out.loc[3, "deal_label"] == "Not rated (branded title)"
    assert pd.notna(out.loc[3, "market_price"])   # still shows what a clean one would cost


def test_not_enough_data():
    out = deals.annotate(market(n=10))
    assert (out["deal_label"] == "Not rated").all()
    assert "Needs at least" in out.loc[0, "deal_note"]


def test_label_bands():
    assert [deals.label_for(p) for p in (-0.10, -0.05, 0.0, 0.05, 0.10, None)] == [
        "Great deal", "Good deal", "Fair price", "Above market", "Overpriced", "Not rated"]
