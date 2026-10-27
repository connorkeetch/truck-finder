"""Personal preferences, visible favorites and evidence edits stay local and preserve provenance."""
import copy

import pytest

from conftest import listing, vin
from rivian_finder import attributes, checklist, db, matching, pipeline, queries, services
from rivian_finder.ui import common, shortlist


@pytest.fixture
def app_factory(conn, settings, monkeypatch):
    from streamlit.testing.v1 import AppTest
    settings["finance"]["target_monthly"] = 777
    db.save_settings(conn, settings)
    monkeypatch.setattr(common, "conn", lambda: conn)
    monkeypatch.setattr(common, "settings", lambda: db.load_settings(conn))
    monkeypatch.setattr(common, "save_settings", lambda value: db.save_settings(conn, value))
    monkeypatch.setattr(common, "inventory", lambda s: queries.inventory_frame(conn, s))
    monkeypatch.setattr(common.services, "run_sources", lambda *args, **kwargs: pytest.fail("Shortlist must not search."))

    def run():
        app = AppTest.from_string("from rivian_finder.ui.shortlist import render\nrender()").run(timeout=10)
        assert not app.exception
        return app

    return run


def add_truck(conn, serial, *, favorite=True, hidden=False, price=58000, trim="Favorite"):
    pipeline.import_listings(conn, [listing(vin=vin(serial), price=price, trim=trim)], "manual_entry")
    vid = conn.execute("SELECT id FROM vehicles WHERE vin=?", (vin(serial),)).fetchone()[0]
    services.toggle_favorite(conn, vid, favorite)
    with conn:
        conn.execute("UPDATE vehicles SET hidden_at=? WHERE id=?",
                     ("2026-10-25T12:00:00Z" if hidden else None, vid))
    return vid


def test_profile_save_preserves_other_settings_and_no_comfort_defaults(app_factory, conn):
    before = copy.deepcopy(db.load_settings(conn))
    app = app_factory()
    assert app.multiselect(key="profile_must_have").value == []
    assert app.multiselect(key="profile_prefer").value == []
    app.number_input(key="profile_range_min").set_value(301)
    app.selectbox(key="profile_range_priority").set_value("must")
    app.number_input(key="profile_tow_min").set_value(7500)
    app.selectbox(key="profile_tow_priority").set_value("prefer")
    app.multiselect(key="profile_must_have").set_value(["ventilated_seats"])
    app.multiselect(key="profile_prefer").set_value(["heated_steering_wheel"])
    next(button for button in app.button if button.label == "Save shopping profile").click().run(timeout=10)
    assert not app.exception
    saved = db.load_settings(conn)
    assert saved["shopping_profile"] == {"range_min": 301, "range_priority": "must", "tow_min": 7500,
                                          "tow_priority": "prefer", "must_have": ["ventilated_seats"],
                                          "prefer": ["heated_steering_wheel"]}
    assert {key: value for key, value in saved.items() if key != "shopping_profile"} == {
        key: value for key, value in before.items() if key != "shopping_profile"}


def test_overlapping_required_and_preferred_features_do_not_save(app_factory, conn):
    before = db.load_settings(conn)
    app = app_factory()
    app.multiselect(key="profile_must_have").set_value(["tow_package"])
    app.multiselect(key="profile_prefer").set_value(["tow_package"])
    next(button for button in app.button if button.label == "Save shopping profile").click().run(timeout=10)
    assert not app.exception
    assert any("not both" in item.value for item in app.error)
    assert db.load_settings(conn) == before


def test_shortlist_keeps_only_visible_favorites_and_ranks_personal_proof_first(app_factory, conn):
    settings = db.load_settings(conn)
    settings["shopping_profile"]["must_have"] = ["ventilated_seats"]
    db.save_settings(conn, settings)
    rejected = add_truck(conn, 801, price=80000, trim="Above budget")
    winner = add_truck(conn, 802, trim="Proof winner")
    add_truck(conn, 803, favorite=False, price=30000, trim="Not favorite")
    add_truck(conn, 804, hidden=True, trim="Hidden favorite")
    add_truck(conn, 805, trim="Needs proof")
    attributes.set_override(conn, winner, "ventilated_seats", "yes", "Checked window sticker")
    attributes.set_override(conn, rejected, "ventilated_seats", "yes", "Checked window sticker")
    app = app_factory()
    heads = [item.value for item in app.markdown if item.value.startswith("**2024")]
    assert len(heads) == 3
    assert "Proof winner" in heads[0] and "Needs proof" in heads[1] and "Above budget" in heads[2]
    assert any("Need proof" in item.value for item in app.info)
    assert any("Does not meet" in item.value for item in app.warning)
    request = next(item.value for item in app.code if "Ventilated seats" in item.value)
    assert "window sticker" in request and "warranty" in request
    assert "payload sticker" not in request
    assert any("Stored listing:" in item.value and "last seen" in item.value for item in app.caption)


def test_feature_evidence_distinguishes_advertised_verified_and_cleared(app_factory, conn):
    settings = db.load_settings(conn)
    settings["shopping_profile"]["must_have"] = ["ventilated_seats"]
    db.save_settings(conn, settings)
    vid = add_truck(conn, 806)
    app = app_factory()
    app.selectbox(key=f"shortlist_feature_{vid}").set_value("ventilated_seats").run(timeout=10)

    def save(state, note):
        widget = next(w for w in app.selectbox if w.label == "Evidence state")
        widget.set_value(state)
        app.text_area(key=widget.key + "_note").set_value(note)
        next(b for b in app.button if b.label == "Save feature evidence").click().run(timeout=10)
        assert not app.exception

    save("Advertised yes", "Seller listing https://dealer.example/equipment")
    claim = attributes.resolve(conn, vid)["ventilated_seats"]
    assert claim.value == "yes" and claim.confidence == "medium" and claim.source == "user_advertised"
    assert conn.execute("SELECT COUNT(*) FROM user_overrides WHERE vehicle_id=? AND field='ventilated_seats'", (vid,)).fetchone()[0] == 0
    assert queries.inventory_frame(conn, db.load_settings(conn)).iloc[0]["match_status"] == "Needs verification"
    save("Verified yes", "Personally checked this VIN's window sticker")
    assert attributes.resolve(conn, vid)["ventilated_seats"].confidence == "verified"
    assert queries.inventory_frame(conn, db.load_settings(conn)).iloc[0]["match_status"] == "Meets requirements"
    save("Unknown", "")
    resolved = attributes.resolve(conn, vid)["ventilated_seats"]
    assert resolved.value == "yes" and resolved.confidence == "medium"
    assert next(w for w in app.selectbox if w.label == "Evidence state").value == "Advertised yes"
    assert conn.execute("SELECT COUNT(*) FROM vehicle_attributes WHERE vehicle_id=? AND field='ventilated_seats'", (vid,)).fetchone()[0] == 1


def test_missing_and_removed_favorites_remain_visible_with_availability_warnings(app_factory, conn):
    missing = add_truck(conn, 809, trim="Missing favorite")
    removed = add_truck(conn, 810, trim="Removed favorite")
    with conn:
        conn.execute("UPDATE listings SET status='missing' WHERE vehicle_id=?", (missing,))
        conn.execute("UPDATE listings SET status='removed' WHERE vehicle_id=?", (removed,))
    app = app_factory()
    assert len([item for item in app.markdown if item.value.startswith("**2024")]) == 2
    assert any("does not confirm a sale" in item.value for item in app.warning)
    assert any("marked sold/removed" in item.value for item in app.warning)


def test_evidence_requires_a_source_and_verified_no_is_a_real_failure(conn, settings):
    vid = add_truck(conn, 807)
    with pytest.raises(ValueError, match="source"):
        shortlist._save_feature(conn, vid, "tow_package", "Verified yes", "")
    assert "tow_package" not in attributes.resolve(conn, vid) or attributes.resolve(conn, vid)["tow_package"].value is None
    shortlist._save_feature(conn, vid, "tow_package", "Verified no", "Inspected VIN-specific build sheet")
    settings["shopping_profile"]["must_have"] = ["tow_package"]
    row = queries.inventory_frame(conn, settings).iloc[0]
    assert matching.evaluate(row, settings, attributes.resolve(conn, vid))["match_status"] == "Does not qualify"


def test_checklist_model_prompts_preserve_keys_and_existing_answers(conn):
    vid = add_truck(conn, 808)
    answers = {key: ("todo", "") for key, _, _ in checklist.ITEMS}
    answers["title"] = ("ok", "Seen clean title")
    checklist.save(conn, vid, answers)
    ford = checklist.items_for({"make": "Ford", "model": "F-150 Lightning"})
    assert [key for key, _, _ in ford] == [key for key, _, _ in checklist.ITEMS]
    assert all("Rivian" not in label + hint and "Gear tunnel" not in label for _, label, hint in ford)
    assert checklist.items_for({"make": "Rivian", "model": "R1T"}) == checklist.ITEMS
    assert checklist.get(conn, vid)["title"]["note"] == "Seen clean title"
    assert checklist.progress(conn)[vid]["total"] == len(checklist.ITEMS)


def test_seller_request_only_asks_for_towing_evidence_when_it_matters():
    row = {"year": 2024, "make": "Toyota", "model": "Camry", "trim": "LE"}
    request = shortlist.seller_request(row, [])
    assert "Toyota Camry" in request and "truck" not in request
    assert "payload sticker" not in request
    request = shortlist.seller_request(row, [{"field": "tow_package", "label": "Tow package", "status": "Advertised"}])
    assert "payload sticker" in request and "vehicle's tow rating" in request
    assert "payload sticker" in shortlist.seller_request(row, [], tow_required=True)
