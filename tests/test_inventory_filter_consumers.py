"""Saved deal filters stay consistent in the workbook and matching-listing alerts."""
from conftest import listing, vin
from rivian_finder import alerts, db, export_xlsx, pipeline, queries


def test_saved_deal_seller_and_price_drop_filters_reach_exports_and_alerts(conn, settings, monkeypatch):
    run = pipeline.import_listings(conn, [listing(vin=vin(801), seller_type="private"),
                                          listing(vin=vin(802), seller_type="dealer")], "manual_entry")
    inventory = queries.inventory_frame(conn, settings)
    private = inventory["vin"].eq(vin(801))
    inventory.loc[private, "deal_label"] = "Good deal (accident reported)"
    inventory.loc[~private, "deal_label"] = "Fair price"
    inventory["price_drops"] = private.astype(int)
    settings["filters"].update(deal_types=["Good deal"], seller_types=["private"], price_drops_only=True)
    db.save_settings(conn, settings)
    saved = db.load_settings(conn)
    monkeypatch.setattr(queries, "inventory_frame", lambda *args: inventory.copy())
    workbook = export_xlsx.build_workbook(conn, saved)
    rows = list(workbook["Current Inventory"].values)
    assert len(rows) == 2
    assert rows[1][rows[0].index("VIN")] == vin(801)
    notice = alerts.collect(conn, run["run_id"], saved)
    assert notice["count"] == 1 and "1 new vehicle" in notice["title"]
