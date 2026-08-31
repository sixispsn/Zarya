from app.intake.applicability import (
    applicability_rules_for_web,
    infer_applicability_scope,
)
from app.intake.request_dto import ConsumerGroupRequest


def test_plain_residential_group_does_not_open_technology_questionnaire():
    scope = infer_applicability_scope([
        ConsumerGroupRequest("residential_full_bath", 500, "Жилая часть"),
    ])
    assert not scope.group_showers
    assert not scope.food_service


def test_sport_and_catering_codes_open_only_relevant_questions():
    sport = infer_applicability_scope([
        ConsumerGroupRequest("sport_pool", 120, "Спортивный комплекс"),
    ])
    assert sport.group_showers
    assert not sport.food_service

    catering = infer_applicability_scope([
        ConsumerGroupRequest("cafe_dining_in", 800, "Ресторан"),
    ])
    assert not catering.group_showers
    assert catering.food_service


def test_free_form_functional_name_is_detected_without_assuming_answer():
    scope = infer_applicability_scope([
        ConsumerGroupRequest("office", 30, "Производственный цех и столовая"),
    ])
    assert scope.group_showers
    assert scope.food_service


def test_saved_positive_answer_keeps_question_visible_for_editing():
    scope = infer_applicability_scope(
        [], group_showers_answer="yes", food_service_answer="yes"
    )
    assert scope.group_showers
    assert scope.food_service


def test_web_rules_are_serialisable_lists():
    rules = applicability_rules_for_web()
    assert "sport_pool" in rules["group_showers_consumer_codes"]
    assert "cafe_dining_in" in rules["food_service_consumer_codes"]
    assert all(isinstance(value, list) for value in rules.values())
