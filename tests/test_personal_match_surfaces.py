"""Required equipment stays unverified consistently across shopping views and exports."""
from conftest import AttributeClaim, listing

from rivian_finder import attributes, compare, export_xlsx, pipeline, queries
from rivian_finder.ui import cards, common, inventory


def test_advertised_required_equipment_is_not_a_verified_match(conn, settings, monkeypatch):
    settings["shopping_profile"]["must_have"] = ["heated_seats"]
    pipeline.import_listings(conn, [listing(make="Ford", model="F-150 Lightning", trim="Lariat",
                                           attributes=[AttributeClaim("heated_seats", "yes", "medium",
                                                                      "listing", evidence="Advertised heated seats")])], "manual_entry")
    vid = conn.execute("SELECT id FROM vehicles").fetchone()[0]
    inv = queries.inventory_frame(conn, settings).assign(photo="", _near=False)
    monkeypatch.setattr(common, "add_photo_column", lambda df: df.assign(photo=""))
    view = inventory.table_view(inv, set())
    card = cards.payload(view, set(), settings["filters"])[0]
    assert any("Needs verification" in label for label, _ in card["chips"])
    assert "Heated seats" in card["match_note"]
    assert "Heated seats" in view.iloc[0]["match_details"]
    table, _ = compare.build(inv)
    assert table.loc["My requirements"].iloc[0] == "Needs verification"
    assert "Heated seats" in table.loc["Needs proof"].iloc[0]
    settings["export"]["include_filtered_out"] = True
    ws = export_xlsx.build_workbook(conn, settings)["Current Inventory"]
    headers = [cell.value for cell in ws[1]]
    assert ws.cell(2, headers.index("My Requirements") + 1).value == "Needs verification"
    assert "Heated seats" in ws.cell(2, headers.index("Needs Proof") + 1).value

    attributes.set_override(conn, vid, "heated_seats", "yes", "Confirmed on window sticker")
    inv = queries.inventory_frame(conn, settings).assign(photo="", _near=False)
    card = cards.payload(inv, set(), settings["filters"])[0]
    assert any("Meets requirements" in label for label, _ in card["chips"])
    assert "Heated seats" not in card["match_note"]
