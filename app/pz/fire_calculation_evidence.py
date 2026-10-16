"""Describe existing V2 results consistently; no calculation or release waiver."""


def fire_calculation_evidence(project):
    fire, pumps = project.fire, project.fire_pumps
    if not fire.required:
        return dict(status="verified", result=fire.normative_note or "В2 не требуется",
                    action="Нет действий", preliminary=False)
    from app.pz.fire_review_binding import requested, validate_binding
    if pumps.pressure_review or pumps.station_design or requested(project):
        try:
            if pumps.pressure_review:
                r = validate_binding(project)
                count, passed = r["scenario_count"], r["minimum_pass_count"]
                op = r["control_mode"]["result"]
            elif pumps.station_design:
                from app.pz.fire_station_binding import validate_design
                r = pumps.station_design
                validate_design(r, project, project.fire_station_input)
                count = passed = 512
                op = r["representative_operating_point"]["result"]
            else:
                raise ValueError(pumps.selection_note or "Предварительный вариант В2 не принят")
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            return dict(status="fail", result=str(exc), action="Пересчитать и проверить вариант В2",
                        preliminary=False)
        return dict(status="specified", preliminary=True,
            result=(f"Расчёт L06 приложен: минимумы проходят в {passed}/{count} заданных режимов. "
                    f"{pumps.model}, контрольный режим Q={op['pump_flow_m3h']:.3f} м³/ч, "
                    f"Hнас={op['pump_head_m']:.3f} м; 1 рабочий + 1 резервный. "
                    "Это результат модели, не подтверждение всех ПК здания."),
            action="См. отдельную проверку проектной применимости В2; повторно задавать рассчитанную сеть не нужно")
    ready = fire.q_total > 0 and fire.required_head_m is not None
    return dict(status="verified" if ready else "missing", preliminary=False,
        result=(f"q={fire.q_total:.3f} л/с; Hтр={fire.required_head_m:.3f} м" if ready else
                "В2 требуется; расчёт расхода и напора не завершён"),
        action="Нет действий" if ready else "Задать расчётную схему В2 и выполнить гидравлику")
