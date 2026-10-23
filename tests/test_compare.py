import pandas as pd

from rivian_finder import compare


def trucks():
    base = {"fit_score": 70, "year": 2023, "generation": "Gen 1", "trim": "Adventure", "motor": "Dual", "color": "",
            "wheels": "", "owners": "", "recall_count": None, "seller_site": "", "seller": "", "location": "",
            "distance_mi": None, "est_monthly": None, "cash_to_target": None, "total_cost": None, "found_on": "",
            "vin": "", "price_change": 0, "epa_range": None, "warranty": "Unknown", "warranty_months_left": None}
    return pd.DataFrame([
        {**base, "price": 58000, "miles": 20000, "battery": "Large", "tonneau": "yes",
         "title_status": "clean", "accident_history": "unknown", "warranty_months_left": 20},
        {**base, "price": 61000, "miles": 12000, "battery": "Max", "tonneau": "yes",
         "title_status": "unknown", "accident_history": "unknown", "warranty_months_left": 30},
        {**base, "price": 58000, "miles": 30000, "battery": "Unknown", "tonneau": "no",
         "title_status": "branded", "accident_history": "unknown"},
    ])


def test_best_values_highlighted():
    table, best = compare.build(trucks())
    names = list(table.columns)
    assert len(set(names)) == 3                                    # duplicate names get disambiguated
    assert best.loc["Price"].tolist() == [True, False, True]       # ties both highlighted
    assert best.loc["Mileage"].tolist() == [False, True, False]
    assert best.loc["Battery"].tolist() == [False, True, False]    # Unknown never wins
    assert best.loc["Powered tonneau"].tolist() == [True, True, False]   # both "Yes"
    assert best.loc["Title"].tolist() == [True, False, False]
    assert best.loc["Warranty left"].tolist() == [False, True, False]
    assert not best.loc["Accidents"].any()                         # all unknown: nothing to highlight
    assert table.loc["Price", names[0]] == "$58,000"
    assert table.loc["Powered tonneau", names[1]] == "Yes"
    assert table.loc["EPA range", names[0]] == "—"
    assert table.loc["Year", names[0]] == "2023"
