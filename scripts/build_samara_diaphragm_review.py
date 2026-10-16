"""L06 passive-resistance study. Does not select a manufactured diaphragm.

PYTHONPATH=. venv/bin/python scripts/build_samara_diaphragm_review.py
"""
from collections import Counter
from dataclasses import asdict
import json
from math import isfinite
from xml.sax.saxutils import escape

from app.calc.fire_diaphragm import NORMATIVE_SOURCES, prepare_nomogram_inputs
from app.calc.fire_hydraulics import MPA_TO_M
from app.calc.fire_pressure_flow import (
    FixedLossCharacteristic, handbook_characteristic, check_pump_operating_point)
from app.intake.project_builder import build_project
from app.pz.ios2_orchestrator import design_ios2
from scripts.build_samara_fire_flow_review import floor_network
from scripts.build_samara_pump_comparison import calculate_comparison
from scripts.build_samara_section_study import (
    ROOT, OUTPUT, load_basis, make_draft, make_request, make_fire_station)


def group_target_resistances(by_floor, group_size):
    """An explicit study heuristic, NOT a normative diaphragm selection rule.

    Use the least throttling target within each consecutive group; then solve
    all scenarios again. Even 3/4-floor grouping allowed by p7.5 may fail.
    Coefficients are frozen across scenarios, never refitted at each flow.
    """
    floors = sorted(by_floor)
    if (group_size not in (3, 4) or not floors
            or floors != list(range(floors[0], floors[-1]+1))
            or any(not isfinite(r) or r <= 0 for r in by_floor.values())):
        raise ValueError('Explicit positive targets on consecutive floors and group size 3/4 required')
    return [dict(floors=floors[i:i+group_size],
                 resistance_head_per_lps2=min(by_floor[f] for f in floors[i:i+group_size]))
            for i in range(0, len(floors), group_size)]


def calculate_diaphragm_review(basis, bundle):
    # Fresh calculations, not saved JSON: geometry, source and pump stay linked.
    comparison = calculate_comparison(basis, bundle)
    candidate = next(c for c in comparison['candidates'] if c['candidate']['id']=='cnp-cdm32-3')
    if not candidate['complete_ideal_solution']:
        raise ValueError('Incomplete ideal reference cannot define target resistances')
    base = bundle.fire_station_result.network
    chars = [handbook_characteristic(c, hose_material='rubber_lined',
                                    nozzle_kind='non_shutoff') for c in base.cabinets]
    if len({c.resistance_head for c in chars}) != 1:
        raise ValueError('This study requires identical representative cabinet kits')
    target = {floor: float('inf') for floor in candidate['ideal_control_floors']}
    for scenario in candidate['scenarios']:
        rows = scenario['ideal_selective']['operating']['cabinets']
        for floor, row in zip(scenario['floors'], rows):
            if floor in target:
                target[floor] = min(target[floor], row['control_drop_m']/row['flow_lps']**2)
    station = make_fire_station(basis)
    source = station.supplies[0]
    resistance = sum(p.A*p.effective_length_m for p in source.segments)
    floors = basis['study_assumptions']['residential_floors']
    height = basis['study_assumptions']['floor_to_floor_m']
    design_flow = (chars[0].minimum_head_m/chars[0].resistance_head)**.5
    result = dict(method='L06 fixed passive resistance targets; not aperture selection',
        release_ready=False, selection_confirmed=False, selected_product=None,
        legacy_modified=False, aperture_selection_status='nomogram_reading_and_product_curve_required',
        normative_sources=NORMATIVE_SOURCES,
        pump=candidate['candidate'], nominal_static_by_floor_mpa=candidate['static_by_floor_mpa'],
        source_guaranteed_m=comparison['suction_guaranteed_m'],
        source_maximum_m=comparison['suction_maximum_m'], maximum_source_is_study_assumption=True,
        required_flow_lps=chars[0].minimum_flow_lps,
        required_pressure_mpa=chars[0].minimum_head_m/MPA_TO_M,
        design_flow_lps=design_flow, cabinet_characteristic=asdict(chars[0]),
        target_resistance_by_floor=target, scenario_count=candidate['scenario_count'],
        normative_coverage_verified=False, static_protection_by_diaphragm=False,
        free_summary=candidate['summary']['free'], ideal_summary=candidate['summary']['ideal_selective'],
        variants=[])
    for size in (3, 4):
        groups = group_target_resistances(target, size)
        for group in groups:
            loss = group['resistance_head_per_lps2']*design_flow**2
            group['nomogram_inputs'] = asdict(prepare_nomogram_inputs(
                valve_dn=base.cabinets[0].dn, flow_lps=design_flow,
                inlet_head_m=chars[0].minimum_head_m+loss,
                required_outlet_head_m=chars[0].minimum_head_m))
        fixed_by_floor = {f: FixedLossCharacteristic(g['resistance_head_per_lps2'],
            'L06: target from minimum ideal-control loss over explicit study scenarios; not a product curve',
            'required_characteristic_study') for g in groups for f in g['floors']}
        scenarios=[]
        for a in range(1, floors+1):
            for b in range(1, floors+1):
                levels=(a,b)
                net=floor_network(base, levels, height)
                devices={c.cabinet_id:fixed_by_floor[f] for c,f in zip(chars,levels) if f in fixed_by_floor}
                for boundary,hs,r in (
                    ('one_supply_guaranteed',comparison['suction_guaranteed_m'],resistance),
                    ('maximum_head_no_supply_loss_bound',comparison['suction_maximum_m'],0)):
                    out=check_pump_operating_point(net, chars, candidate['candidate']['curve'],
                        suction_static_head_m=hs, supply_resistance=r, fixed_losses=devices)
                    scenarios.append(dict(floors=list(levels), boundary=boundary,
                        fixed_cabinets={key:asdict(value) for key,value in devices.items()}, result=asdict(out)))
        operations=[s['result']['operating'] for s in scenarios]
        rows=[row for op in operations if op is not None for row in op['cabinets']]
        complete=all(op is not None for op in operations)
        pressures=[c['outlet_head_m']/MPA_TO_M for c in rows]
        result['variants'].append(dict(group_size=size, groups=groups, scenarios=scenarios,
            complete_solution=complete, summary=dict(Counter(s['result']['status'] for s in scenarios)),
            pressure_range_mpa=[min(pressures),max(pressures)] if complete else None,
            flow_range_lps=[min(c['flow_lps'] for c in rows),max(c['flow_lps'] for c in rows)] if complete else None,
            dynamic_pressure_limit_met=complete and max(pressures) <= .45,
            selection_confirmed=False))
    return result


def render_review(path, review):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, PageBreak, Spacer

    pdfmetrics.registerFont(TTFont('DiaphragmStudy', str(ROOT/'app/assets/fonts/OpenGOSTtypeB-Regular.ttf')))
    body=ParagraphStyle('body',fontName='DiaphragmStudy',fontSize=11,leading=14.5,spaceAfter=9)
    title=ParagraphStyle('title',parent=body,fontSize=22,leading=25,spaceAfter=15)
    sub=ParagraphStyle('sub',parent=body,fontSize=14,leading=17,spaceBefore=7,spaceAfter=10)
    def p(text, style=body): return Paragraph(escape(str(text)),style)
    def n(value,d=3): return f'{value:.{d}f}'.replace('.',',')
    def table(rows,widths):
        out=Table([[p(cell) for cell in row] for row in rows],colWidths=[x*mm for x in widths],repeatRows=1)
        out.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.35,colors.HexColor('#bec7ce')),
            ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eef2f5')),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
        return out
    a,b=review['variants']
    story=[p('В2 / диафрагмы у ПК',title),
        p('Секция 3.2, Самара. CNP CDM32-3. Проверка постоянных сопротивлений; '
          'не окончательный подбор отверстий и не рабочий проект.'),
        p('Результат',sub),
        table([('Группировка','Минимумы ПК','p после устройства, МПа'),
            *[(f'По {v["group_size"]} этажа',f'{v["summary"].get("meets_minimum",0)}/{review["scenario_count"]}',
              ' - '.join(n(x,5) for x in v['pressure_range_mpa'])) for v in review['variants']]], [45,42,83]),
        Spacer(1,10*mm),
        p('Группа по три этажа проходит проверенные сочетания с требуемыми постоянными '
          'сопротивлениями. Выбранная группа по четыре этажа не проходит в восьми сочетаниях: '
          'наименьшее давление '+n(b['pressure_range_mpa'][0],6)+' МПа вместо 0,210 МПа. '
          'Округление до двух знаков скрывает этот недостаток.'),
        p('Это не общий запрет групп по четыре этажа. Пункт 7.5 СП10 допускает одинаковые '
          'отверстия на 3-4 этажах, но не гарантирует работу любой выбранной группировки.'),
        p('Что изменилось в модели',sub),
        p('Диафрагма моделируется постоянным сопротивлением: Δh = R × q². '
          'При изменении расхода изменяются потери. Давление после неё не фиксируется '
          'на уставке, как в прежнем опыте с идеальными регуляторами.'),
        p('Сопротивления зафиксированы до прогона и одинаковы во всех сценариях. '
          'Одновременно решены расходы двух ПК, потери кольца и пересечение с кривой насоса. '
          'Проверены баланс расхода и энергии; за пределы каталожной кривой расчёт не выходит.'),
        p('Границы опыта',sub),
        p('16 этажей по 3 м; два разных представительных стояка, 256 пар этажей × 2 границы источника. '
          'Нижняя граница: один подвод с потерями и Hгар = 30 м. Верхняя: учебный максимум '
          'Hист = 35 м без потерь подвода - огибающая, не расчёт распределения по двум вводам. '
          'Сочетания этажей не подтверждают покрытие помещений при одном пожаре.'),
        PageBreak(),p('Целевые сопротивления',title),
        p('Вариант по три этажа: одно значение R для каждого ПК соответствующей группы. '
          '16-й этаж в данном опыте без местного ограничителя.'),
        table([('Этажи','R, м/(л/с)²','Δp при qрасч, МПа','Шкала P номограммы'),
            *[(f'{g["floors"][0]}-{g["floors"][-1]}',n(g['resistance_head_per_lps2'],4),
                n(g['nomogram_inputs']['pressure_drop_mpa'],4),
                n(g['nomogram_inputs']['pressure_axis_value'],2)) for g in a['groups']]], [27,46,49,48]),
        Spacer(1,9*mm),
        p('qрасч = '+n(review['design_flow_lps'],6)+' л/с на один ПК при p = 0,210 МПа '
          'по справочной характеристике принятого рукава/ствола. Табличный минимум расхода '
          '2,6 л/с не заменён; расход и давление проверяются независимо.'),
        p('Как получен R',sub),
        p('Для каждого этажа найдена наименьшая требуемая потеря идеального ограничителя '
          'среди 512 прежних сценариев. R = Δh / q². Для группы взято наименьшее из этих '
          'сопротивлений, затем вся сеть пересчитана с постоянными R. Это исследовательский '
          'способ задания цели, НЕ нормативный алгоритм выбора отверстия.'),
        p('Номограмма: учтено изменение № 1',sub),
        p('СП10, приложение Б, пункт Б.2.1 в редакции изменения 1: в шкалу P идёт '
          'разница фактического и необходимого давлений. Вход для рисунка: '
          'Pшк = 100 × (pдо - pпосле), давления в МПа. '
          'Нельзя подставлять только pпосле = 0,210 МПа.'),
        p('Все приведённые точки попадают в опубликованные шкалы q = 2,5-10 л/с '
          'и Δp = 0,02-0,70 МПа, используется левая шкала для крана DN50. '
          'Это подготовленные точки для графического определения отверстий, а не диаметры диафрагм.'),
        p('Почему ещё нет миллиметров отверстия',sub),
        p('R пока задан как требуемая характеристика, а не получен из паспорта выбранной диафрагмы. '
          'Не назначен произвольный коэффициент расхода. После чтения номограммы, выбора '
          'реального отверстия и учёта его характеристики/допуска нужно повторить весь прогон. '
          'В варианте по три этажа минимальное давление близко к границе: запаса на округление '
          'отверстия по умолчанию нет.'),
        PageBreak(),p('Контроль и границы результата',title)]
    rows=[]
    for variant,levels in [(a,[16,16]),(a,[1,16]),(a,[1,1]),(a,[4,9]),(b,[4,9])]:
        s=next(s for s in variant['scenarios'] if s['floors']==levels and s['boundary']=='one_supply_guaranteed')
        r=s['result']; op=r['operating']
        rows.append((str(variant['group_size']),'/'.join(map(str,levels)),
            ' / '.join(n(c['flow_lps'],4) for c in op['cabinets']),
            ' / '.join(n(c['outlet_head_m']/MPA_TO_M,5) for c in op['cabinets']),
            'да' if r['status']=='meets_minimum' else 'нет'))
    story.extend([table([('Группа','Этажи','q каждого ПК, л/с','p каждого ПК, МПа','Минимумы'),*rows], [19,22,51,54,24]),
        Spacer(1,8*mm),
        p('Статика проверяется отдельно',sub),
        p('При q = 0 потери диафрагмы равны нулю. Она не защищает от избыточного '
          'статического давления. Номинальная огибающая нижнего ПК остаётся '
          +n(max(review['nominal_static_by_floor_mpa'].values()),6)+' МПа; '
          'предел независимого ВПВ 0,9 МПа. Допуски насоса, переходные режимы и верхняя '
          'граница наружного источника требуют подтверждения.'),
        p('Перед подбором и выпуском',sub),
        p('1. Определить отверстия по приложению Б; подтвердить точное исполнение и '
          'гидравлическую характеристику диафрагм, клапанов ПК, рукавов и стволов.'),
        p('2. Повторить совместную проверку с реальными потерями станции PFFS, '
          'выбранными устройствами и допусками. R из этой таблицы не включён в спецификацию '
          'как закупаемое изделие.'),
        p('3. Подтвердить NPSH, рабочий диапазон, управление и резервирование; '
          'проверить отключения участков кольца и совместное тушение по планам.'),
        p('Источники',sub),
        p('Предоставленный СП10.13130.2020: приложение Б, номограмма и Б.2 на PDF с.35; '
          'изменение 1, уточнение Б.2.1 на PDF с.33 (печатная с.32); пп.6.2.20, 7.5, 7.6, '
          '7.14 и таблица 7.3. Пособие ВНИИПО, 2010, раздел 7.9, печатные с.377-379: '
          'потеря на диафрагме связана с квадратом скорости; произвольное значение коэффициента '
          'сопротивления из пособия не назначено.'),
        p('Каталог CDM/CDMF: CDM32-3, PDF с.33; каталог PFFS: PDF с.40. '
          'Гидравлическая кривая одиночного насоса не объявлена гарантированной кривой станции.'),
        p('Отдельное исследование L06, не комплект ИОС2 по ГОСТ Р21.619-2023. '
          'Производственная ПЗ, спецификация, сайт и legacy не заменены. '
          'Все значения, сценарии и причины отказов сохранены в расчётном JSON.')])
    def footer(canvas,doc):
        canvas.setFont('DiaphragmStudy',9)
        canvas.drawString(20*mm,12*mm,'ЗАРЯ / секция 3.2 / постоянные сопротивления / 04.10.2026')
        canvas.drawRightString(190*mm,12*mm,str(doc.page))
    SimpleDocTemplate(str(path),pagesize=A4,leftMargin=20*mm,rightMargin=20*mm,
        topMargin=18*mm,bottomMargin=22*mm,title='В2 - проверка постоянных сопротивлений диафрагм').build(
            story,onFirstPage=footer,onLaterPages=footer)


def main():
    basis=load_basis()
    bundle=design_ios2(build_project(make_request(make_draft(basis))),
        output_dir=str(OUTPUT/'documents'),fire_station=make_fire_station(basis),render_documents=False)
    review=calculate_diaphragm_review(basis,bundle)
    OUTPUT.mkdir(parents=True,exist_ok=True)
    (OUTPUT/'fire-diaphragm-review.json').write_text(json.dumps(review,ensure_ascii=False,indent=2,allow_nan=False))
    path=OUTPUT/'В2-диафрагмы-проверка.pdf'
    render_review(path,review)
    print(json.dumps(dict(pdf=str(path),variants=[{k:v for k,v in x.items() if k!='scenarios'}
        for x in review['variants']]),ensure_ascii=False))


if __name__=='__main__': main()
