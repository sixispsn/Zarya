"""Нормативные замечания к исходным данным Wizard."""
from app.intake.advisories import review_request
from app.intake.request_dto import (
    ConsumerGroupRequest, DocumentRequest, IOS2Request,
)


def _req(building_type="residential", height=48.0, consumers=None):
    return IOS2Request(
        document=DocumentRequest(
            cipher="ТЕСТ", object_name="Объект", organization="Тест"),
        building_type=building_type,
        floors=16,
        building_height_m=height,
        consumers=consumers or [
            ConsumerGroupRequest("residential_central_hw", 480, "Жилая часть")
        ],
    )


def test_residential_48m_has_no_high_rise_warning():
    assert not any("СП 253" in item.message for item in review_request(_req()))


def test_residential_above_75m_warns_about_sp253():
    warnings = review_request(_req(height=75.1))
    assert any(item.code == "sp30_4_1_high_rise_residential" for item in warnings)


def test_public_above_50m_warns_about_sp253():
    warnings = review_request(_req(
        building_type="public", height=50.1,
        consumers=[ConsumerGroupRequest("office", 200, "Офисы")],
    ))
    assert any(item.code == "sp30_4_1_high_rise_public" for item in warnings)


def test_residential_with_pool_is_mixed_use_not_high_rise():
    warnings = review_request(_req(consumers=[
        ConsumerGroupRequest("residential_central_hw", 480, "Жилая часть"),
        ConsumerGroupRequest("sport_pool", 120, "Бассейн"),
    ]))
    assert [item.code for item in warnings] == ["sp30_mixed_use"]
    assert warnings[0].reference == "СП 30.13330.2020, пп. 1.1, 7.5–7.6"
