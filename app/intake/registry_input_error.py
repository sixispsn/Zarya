"""Optional UI addresses; the canonical validation messages remain unchanged."""


class RegistryInputError(ValueError):
    def __init__(self, errors, issues):
        super().__init__(" ".join(errors))
        self.input_issues = issues
        self.input_message = (
            " ".join(issue["message"] for issue in issues)
            if len(issues) == len(errors) else None
        )


def field_error(detail, registry, row_index, field, label, code):
    """Describe the existing parser refusal without changing its first-error order."""
    reasons = {
        "required_value": "заполните обязательное поле",
        "invalid_number": "введите число",
        "nonfinite_number": "введите конечное число",
        "integer_required": "введите целое число",
        "boolean_required": "выберите явно «Да» или «Нет»",
    }
    title = {"sewage_risers": "Расчётный стояк", "sewer_elements": "Элемент К1/К2",
             "wastewater_fan_ventilation": "Фановое окончание"}.get(
        registry, "Труба К1/К2")
    return RegistryInputError([detail], [dict(code=code, registry=registry,
        row_index=row_index, field=field,
        message=f"{title}, строка {row_index + 1}, «{label}»: {reasons[code]}.")])
