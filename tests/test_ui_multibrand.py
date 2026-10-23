"""Other makes keep their identity and truck-specific towing evidence in every comparison view."""
import pandas as pd
import pytest
from contextlib import nullcontext

from conftest import listing
from rivian_finder import attributes, compare, export_xlsx, pipeline, queries
from rivian_finder.ui import cards, common, inventory


def test_mixed_brand_names_and_tow_comparison():
    trucks = pd.DataFrame([
        {"year": 2023, "make": "Ford", "model": "F-150 Lightning", "trim": "Lariat", "price": 48000,
         "tow_capacity_lbs": 10000, "tow_src": "Window sticker", "tow_conf": "verified"},
        {"year": 2024, "make": "Chevrolet", "model": "Silverado EV", "trim": "4WT", "price": 48000,
         "tow_capacity_lbs": 12500, "tow_src": "Dealer", "tow_conf": "medium"},
    ])
    table, best = compare.build(trucks)
    assert "Ford F-150 Lightning" in table.columns[0]
    assert "Chevrolet Silverado EV" in table.columns[1]
    assert table.loc["Tow capacity"].tolist() == ["10,000 lb", "12,500 lb"]
    assert table.loc["Tow confidence"].tolist() == ["verified", "medium"]
    assert best.loc["Tow capacity"].tolist() == [False, True]


def test_brand_and_tow_survive_cards_table_and_export(conn, settings, monkeypatch):
    pipeline.import_listings(conn, [listing(make="Ford", model="F-150 Lightning", trim="Lariat", price=48000,
                                           url="https://dealer.example/lightning")], "manual_entry")
    vid = conn.execute("SELECT id FROM vehicles").fetchone()[0]
    attributes.set_override(conn, vid, "tow_capacity_lbs", "10000", "Confirmed window sticker")
    inv = queries.inventory_frame(conn, settings).assign(photo="", _near=False)
    monkeypatch.setattr(common, "add_photo_column", lambda df: df.assign(photo=""))
    view = inventory.table_view(inv, set())
    assert "Ford F-150 Lightning" in view.iloc[0]["name"]
    assert "R1T" not in common.vehicle_label(inv.iloc[0])
    assert view.iloc[0]["tow_capacity_lbs"] == 10000
    card = cards.payload(view, set(), settings["filters"])[0]
    assert "Ford F-150 Lightning" in card["title"]
    assert card["tow"] == "10,000 lb tow capacity" and "verified" in card["tow_note"]
    assert "Range unknown — verify" in [label for label, _ in card["chips"]]
    settings["export"]["include_filtered_out"] = True
    ws = export_xlsx.build_workbook(conn, settings)["Current Inventory"]
    headers = [c.value for c in ws[1]]
    assert ws.cell(2, headers.index("Brand") + 1).value == "Ford"
    assert ws.cell(2, headers.index("Tow Capacity (lb)") + 1).value == 10000
    assert ws.cell(2, headers.index("Tow Confidence") + 1).value == "verified"


@pytest.mark.parametrize("brand,model", [("Ford", "F-150 Lightning"), ("Chevrolet", "Silverado EV"), ("GMC", "Sierra EV")])
def test_manual_form_keeps_selected_brand_and_specs(monkeypatch, brand, model):
    from rivian_finder.ui import forms

    class Form:
        def columns(self, count):
            return [self] * count

        def form(self, *args, **kwargs):
            return nullcontext()

        def selectbox(self, label, options, index=0, **kwargs):
            return brand if label == "Brand" else options[index]

        def text_input(self, label, value="", **kwargs):
            return {"Make": brand, "Model": model, "Battery (as listed)": "Extended Range", "Motor (as listed)": "Dual"}.get(label, value)

        def number_input(self, label, minimum, maximum, value, *args, **kwargs):
            return {"EPA range (mi, 0 = unknown)": 320, "Tow capacity (lb, 0 = unknown)": 10000}.get(label, value)

        def checkbox(self, label, value=False):
            return value

        def text_area(self, label, value="", **kwargs):
            return value

        def form_submit_button(self, *args, **kwargs):
            return True

    monkeypatch.setattr(forms, "st", Form())
    result = forms.listing_review_form({"price": 48000}, "manual_test", "manual", show_claims=False)
    assert (result.make, result.model) == (brand, model)
    claims = {c.field: c.value for c in result.attributes}
    assert claims["battery"] == "Extended Range"
    assert claims["epa_range"] == "320" and claims["tow_capacity_lbs"] == "10000"
