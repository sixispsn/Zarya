from dataclasses import replace
from pathlib import Path

from app.normative.baseline import NormativeBaseline, get_active_baseline
from app.normative.radar import (
    NormativeRadarStore,
    RadarIndicator,
    SourceHealth,
    parse_official_page,
    run_radar_check,
)


def _official_page(
    designation: str,
    amendments: tuple[str, ...] = (),
    *,
    status: str = "Действует",
    corrections: int = 0,
) -> bytes:
    change_rows = "".join(
        f"<li>Изменение №{number} к {designation}</li>"
        for number in amendments
    )
    correction_rows = "".join(
        f'<li><a href="/correction/{index}">Поправка к {designation}</a></li>'
        for index in range(corrections)
    )
    return (
        "<!doctype html><html><body>"
        f"<h1>{designation}</h1><strong>{status}</strong>"
        f"<ul>{change_rows}{correction_rows}</ul>"
        "</body></html>"
    ).encode("utf-8")


def _exact_fetcher(url: str, timeout: float) -> bytes:
    del timeout
    baseline = get_active_baseline()
    document = next(row for row in baseline.documents if row.source_url == url)
    amendments = tuple(row for row in document.amendments if row.isdigit())
    if document.document_id == "sp_10_13130_2020":
        amendments = ("1",)
    corrections = 1 if document.document_id == "gost_21_110_2013" else 0
    return _official_page(document.designation, amendments, corrections=corrections)


def _entry(snapshot, document_id: str):
    return next(row for row in snapshot.entries if row.document_id == document_id)


def test_initial_snapshot_exposes_manual_baseline_state(tmp_path):
    snapshot = NormativeRadarStore(tmp_path).load(get_active_baseline())

    assert snapshot.summary == {
        "green": 9,
        "orange": 0,
        "red": 0,
        "gray": 1,
        "total": 10,
    }
    assert snapshot.overall_indicator == RadarIndicator.GRAY
    assert _entry(snapshot, "sp_10_13130_2020").indicator == RadarIndicator.GREEN
    assert _entry(snapshot, "pp87").source_health == SourceHealth.UNCONFIGURED


def test_official_page_parser_extracts_status_changes_and_ignores_zero():
    content = _official_page(
        "СП 30.13330.2020",
        ("0", "5", "1", "5"),
        corrections=2,
    )

    probe = parse_official_page(content, "СП 30.13330.2020")

    assert probe.official_status == "Действует"
    assert probe.amendments == ("1", "5")
    assert probe.correction_count == 2
    assert len(probe.semantic_sha256) == 64


def test_online_check_confirms_sp10_change_one(tmp_path):
    store = NormativeRadarStore(tmp_path)

    snapshot = run_radar_check(store=store, fetcher=_exact_fetcher)

    assert snapshot.summary == {
        "green": 9,
        "orange": 0,
        "red": 0,
        "gray": 1,
        "total": 10,
    }
    sp30 = _entry(snapshot, "sp_30_13330_2020")
    assert sp30.indicator == RadarIndicator.GREEN
    assert sp30.source_health == SourceHealth.OK
    assert sp30.official_amendments == ("1", "2", "3", "4", "5")
    assert _entry(snapshot, "gost_21_110_2013").official_correction_count == 1
    sp10 = _entry(snapshot, "sp_10_13130_2020")
    assert sp10.indicator == RadarIndicator.GREEN
    assert sp10.official_amendments == ("1",)
    assert "совпадает" in sp10.reason


def test_unaccepted_change_is_orange_and_event_is_not_duplicated(tmp_path):
    baseline = get_active_baseline()
    store = NormativeRadarStore(tmp_path)

    def fetcher(url: str, timeout: float) -> bytes:
        content = _exact_fetcher(url, timeout)
        document = next(row for row in baseline.documents if row.source_url == url)
        if document.document_id == "sp_30_13330_2020":
            return _official_page(document.designation, ("1", "2", "3", "4", "5", "6"))
        return content

    first = run_radar_check(store=store, baseline=baseline, fetcher=fetcher)
    second = run_radar_check(store=store, baseline=baseline, fetcher=fetcher)

    assert _entry(first, "sp_30_13330_2020").indicator == RadarIndicator.ORANGE
    assert _entry(second, "sp_30_13330_2020").indicator == RadarIndicator.ORANGE
    sp30_events = [
        row for row in store.events(50)
        if row.document_id == "sp_30_13330_2020"
    ]
    assert len(sp30_events) == 1
    assert sp30_events[0].kind == "amendment_detected"
    assert "№ 6" in sp30_events[0].message


def test_invalid_official_status_is_red(tmp_path):
    baseline = get_active_baseline()

    def fetcher(url: str, timeout: float) -> bytes:
        content = _exact_fetcher(url, timeout)
        document = next(row for row in baseline.documents if row.source_url == url)
        if document.document_id == "gost_r_21_619_2023":
            return _official_page(document.designation, status="Заменен")
        return content

    snapshot = run_radar_check(
        store=NormativeRadarStore(tmp_path),
        baseline=baseline,
        fetcher=fetcher,
    )

    document = _entry(snapshot, "gost_r_21_619_2023")
    assert document.indicator == RadarIndicator.RED
    assert document.official_status == "Заменен"


def test_source_failure_is_gray_without_fabricating_status(tmp_path):
    def unavailable(url: str, timeout: float) -> bytes:
        del url, timeout
        raise OSError("network unavailable")

    snapshot = run_radar_check(
        store=NormativeRadarStore(tmp_path),
        fetcher=unavailable,
    )

    sp30 = _entry(snapshot, "sp_30_13330_2020")
    assert sp30.indicator == RadarIndicator.GRAY
    assert sp30.source_health == SourceHealth.ERROR
    assert sp30.official_status == ""
    assert "network unavailable" in sp30.error
    assert _entry(snapshot, "sp_10_13130_2020").indicator == RadarIndicator.GRAY


def test_semantic_card_drift_requires_review(tmp_path):
    store = NormativeRadarStore(tmp_path)
    run_radar_check(store=store, fetcher=_exact_fetcher)
    baseline = get_active_baseline()

    def changed_card(url: str, timeout: float) -> bytes:
        content = _exact_fetcher(url, timeout)
        document = next(row for row in baseline.documents if row.source_url == url)
        if document.document_id == "gost_r_21_620_2023":
            return _official_page(document.designation, corrections=1)
        return content

    snapshot = run_radar_check(store=store, fetcher=changed_card)

    assert (
        _entry(snapshot, "gost_r_21_620_2023").indicator
        == RadarIndicator.ORANGE
    )
    assert "поправка" in _entry(snapshot, "gost_r_21_620_2023").reason


def test_new_baseline_resets_accepted_semantic_fingerprint(tmp_path):
    store = NormativeRadarStore(tmp_path)
    first = run_radar_check(store=store, fetcher=_exact_fetcher)
    assert _entry(first, "sp_30_13330_2020").accepted_semantic_sha256

    baseline = get_active_baseline()
    changed_document = replace(
        baseline.documents[3],
        verified_on="2026-09-04",
    )
    changed_baseline = NormativeBaseline(
        baseline_id="ru-ios-2026-09-04-v1",
        accepted_on="2026-09-04",
        documents=(
            *baseline.documents[:3],
            changed_document,
            *baseline.documents[4:],
        ),
    )

    reconciled = store.load(changed_baseline)

    assert reconciled.baseline_fingerprint == changed_baseline.fingerprint
    assert not _entry(reconciled, "sp_30_13330_2020").accepted_semantic_sha256


def test_radar_routes_and_interface_are_exposed():
    from app.main import app

    paths = app.openapi()["paths"]
    assert "/wizard/normatives" in paths
    assert "/wizard/normatives/check" in paths
    assert "/wizard/normatives/status.json" in paths

    template = Path("app/web/templates/wizard_normatives.html").read_text(
        encoding="utf-8",
    )
    javascript = Path("app/web/static/wizard.js").read_text(encoding="utf-8")
    stylesheet = Path("app/web/static/wizard.css").read_text(encoding="utf-8")
    assert "Нормативная база ВК под наблюдением" in template
    assert "Обнаружение ≠ принятие" in template
    assert "/wizard/normatives/status.json" in javascript
    assert "radar-orange-blink" in stylesheet
