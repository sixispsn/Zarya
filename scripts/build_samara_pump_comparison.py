"""L06: compare source-backed pumps, without replacing the baseline selection.

PYTHONPATH=. venv/bin/python scripts/build_samara_pump_comparison.py
"""
from collections import Counter
from dataclasses import asdict
import json
from xml.sax.saxutils import escape

from app.calc.fire_hydraulics import MPA_TO_M
from app.calc.fire_pressure_flow import (
    handbook_characteristic, required_common_header, check_pump_operating_point)
from app.calc.fire_pump_envelope import screen_pump_envelope
from app.calc.fire_regulator_review import BAR_TO_M, screen_regulator
from app.data.fire_pump_study import STUDY_CANDIDATES
from app.data.fire_regulators import CANDIDATES as REGULATORS
from app.intake.project_builder import build_project
from app.pz.ios2_orchestrator import design_ios2
from scripts.build_samara_fire_flow_review import floor_network
from scripts.build_samara_section_study import (
    ROOT, OUTPUT, load_basis, make_draft, make_request, make_fire_station)


def calculate_comparison(basis, bundle):
    station = make_fire_station(basis)
    base = bundle.fire_station_result.network
    if len(base.cabinets) != 2 or len({c.riser_id for c in base.cabinets}) != 2:
        raise ValueError("Two independent representative risers required")
    supplies = [(s.guaranteed_head_m + s.source_elevation_m - station.pump_axis_m,
                 s.maximum_head_m + s.source_elevation_m - station.pump_axis_m,
                 sum(p.A * p.effective_length_m for p in s.segments)) for s in station.supplies]
    if not supplies or len(set(supplies)) != 1:
        raise ValueError("This comparison requires explicit identical source boundaries")
    suction_min, suction_max, resistance = supplies[0]
    floors = basis['study_assumptions']['residential_floors']
    height = basis['study_assumptions']['floor_to_floor_m']
    chars = [handbook_characteristic(c, hose_material='rubber_lined',
                                    nozzle_kind='non_shutoff') for c in base.cabinets]
    static_limit = .9 * MPA_TO_M + 1.35 - station.pump_axis_m
    required = required_common_header(base, chars, ceiling_head_m=static_limit)
    q = required.total_flow_lps
    boost = required.header_head_m - (suction_min - resistance * q * q)
    args = dict(required_q_m3h=q * 3.6, required_boost_m=boost,
                maximum_suction_head_m=suction_max, allowed_header_static_m=static_limit)
    result = dict(method='L06 joint study; nominal bare-pump curves',
        release_ready=False, selected_product=None, legacy_modified=False,
        required_q_m3h=q * 3.6, required_boost_m=boost,
        maximum_pump_shutoff_m=static_limit - suction_max,
        suction_guaranteed_m=suction_min, suction_maximum_m=suction_max,
        maximum_source_is_study_assumption=True,
        static_limit_mpa=.9, cabinet_pressure_screen_mpa=.45,
        baseline=dict(model=bundle.project.fire_pumps.model,
            screen=asdict(screen_pump_envelope(bundle.project.fire_pumps.curve, **args))),
        control_policy='ideal cap at tabular minimum on floors with nominal static pressure >0.45 MPa; not a selected regulator',
        network_model='intact ring, two different risers; floor combinations are sensitivity, not coverage proof',
        candidates=[])
    for candidate in STUDY_CANDIDATES:
        screen = screen_pump_envelope(candidate.curve, **args)
        if screen.shutoff_head_m is None:
            raise ValueError("Explicit shutoff head required for floor pressure screening")
        static_by_floor = {
            f: (suction_max + screen.shutoff_head_m + station.pump_axis_m
                - ((f - 1) * height + 1.35)) / MPA_TO_M
            for f in range(1, floors + 1)}
        # Conservative pressure screen includes nominal static pressure. No claim
        # that dynamic checks alone exempt a cabinet from SP10 p7.5.
        controlled_floors = [f for f, p in static_by_floor.items() if p > .45]
        scenarios = []
        for a in range(1, floors + 1):
            for b in range(1, floors + 1):
                levels = (a, b)
                net = floor_network(base, levels, height)
                controls = {c.cabinet_id: c.minimum_head_m for c, f in zip(chars, levels)
                            if f in controlled_floors}
                for boundary, hs, r in (
                    ('one_supply_guaranteed', suction_min, resistance),
                    ('maximum_head_no_supply_loss_bound', suction_max, 0)):
                    kw = dict(suction_static_head_m=hs, supply_resistance=r)
                    free = check_pump_operating_point(net, chars, candidate.curve, **kw)
                    regulated = check_pump_operating_point(net, chars, candidate.curve,
                        ideal_outlet_heads=controls, **kw)
                    scenarios.append(dict(floors=list(levels), boundary=boundary,
                        controlled_cabinets=list(controls), free=asdict(free),
                        ideal_selective=asdict(regulated)))
        def counts(kind):
            return dict(Counter(s[kind]['status'] for s in scenarios))
        operations = [s['ideal_selective']['operating'] for s in scenarios]
        controlled = [c for s in scenarios if s['ideal_selective']['operating'] is not None
                      for c in s['ideal_selective']['operating']['cabinets']
                      if c['cabinet_id'] in s['controlled_cabinets']]
        outlets = [c for o in operations if o is not None for c in o['cabinets']]
        regulator_screens = []
        # Incomplete operation is never passed as a complete real-device duty.
        if all(o is not None for o in operations) and controlled:
            for regulator in REGULATORS:
                regulator_screens.append(asdict(screen_regulator(regulator,
                    application='standalone_vpv',
                    flow_range_m3h=(min(c['flow_lps'] for c in controlled) * 3.6,
                                    max(c['flow_lps'] for c in controlled) * 3.6),
                    setting_bar=chars[0].minimum_head_m / BAR_TO_M,
                    minimum_available_drop_bar=min(c['control_drop_m'] for c in controlled) / BAR_TO_M,
                    maximum_inlet_pressure_bar=max(static_by_floor.values()) * 10)))
        result['candidates'].append(dict(candidate=asdict(candidate), screen=asdict(screen),
            static_by_floor_mpa=static_by_floor, ideal_control_floors=controlled_floors,
            scenario_count=len(scenarios),
            summary={'free': counts('free'), 'ideal_selective': counts('ideal_selective')},
            complete_ideal_solution=all(o is not None for o in operations),
            minimum_control_drop_bar=(min(c['control_drop_m'] for c in controlled) / BAR_TO_M
                                      if controlled and all(o is not None for o in operations) else None),
            maximum_ideal_outlet_mpa=(max(c['outlet_head_m'] for c in outlets) / MPA_TO_M
                                     if outlets and all(o is not None for o in operations) else None),
            regulator_screens=regulator_screens, scenarios=scenarios,
            selection_confirmed=False))
    return result


def render_comparison(path, review):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, PageBreak, Spacer
    from reportlab.graphics.shapes import Drawing, Line, PolyLine, Circle, String

    pdfmetrics.registerFont(TTFont('CNPStudy', str(ROOT / 'app/assets/fonts/OpenGOSTtypeB-Regular.ttf')))
    body = ParagraphStyle('body', fontName='CNPStudy', fontSize=11, leading=14, spaceAfter=8)
    heading = ParagraphStyle('heading', parent=body, fontSize=20, leading=23, spaceAfter=13)
    def p(s, style=body): return Paragraph(escape(str(s)), style)
    def n(v, d=3): return '-' if v is None else f'{v:.{d}f}'.replace('.', ',')
    def table(rows, widths):
        t = Table([[p(c) for c in row] for row in rows], colWidths=[w * mm for w in widths], repeatRows=1)
        t.setStyle(TableStyle([('GRID', (0,0), (-1,-1), .3, colors.HexColor('#bcc5ce')),
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#edf1f5')),
            ('VALIGN', (0,0), (-1,-1), 'TOP'), ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 5), ('BOTTOMPADDING', (0,0), (-1,-1), 4)]))
        return t
    rows = []
    for c in review['candidates']:
        e = c['screen']
        rows.append((c['candidate']['pump_model'], n(e['duty_head_m']),
                     n(e['dynamic_margin_m']), n(e['shutoff_head_m']),
                     n(max(c['static_by_floor_mpa'].values()))))
    story = [p('В2 / насос и давление вместе', heading), p('Самара, секция 3.2. Исследование L06. 04.10.2026.'),
        p('Найдены два каталожных варианта, проходящих номинальные границы подачи и статики. '
          'Общий редуктор может оказаться не нужен. Это ещё не окончательный подбор станции: '
          'использованы характеристики одиночных насосов, без неподтверждённых потерь внутри PFFS.'),
        table([('Требование контрольного примера', 'Значение'),
               ('Минимальный расход двух верхних ПК', n(review['required_q_m3h']) + ' м³/ч'),
               ('Требуемая насосная добавка при этом расходе', n(review['required_boost_m']) + ' м'),
               ('Максимальный допустимый напор насоса при Q=0', n(review['maximum_pump_shutoff_m']) + ' м'),
               ('Исходный насос', review['baseline']['model'] + '; H(0)='
                + n(review['baseline']['screen']['shutoff_head_m'],1) + ' м')], [112,58]),
        Spacer(1,10), table([('Насос', 'H при Qтреб, м', 'Запас, м', 'H(0), м', 'Статика внизу, МПа'), *rows], [43,34,28,27,38]),
        p('Вариант CDM32-3 даёт больший запас при расчётном расходе: около 6,1 м против 1,36 м '
          'у CDM20-4. Именно этот запас ещё должен покрыть неучтённые паспортные сопротивления '
          'и допуски. Ни один из вариантов не принят в спецификацию.'),
        p('Статика рассчитана при принятом в учебном примере максимуме наружного источника 35 м, '
          'на общей высотной базе насосной. Это не подтверждённое ТУ значение. '
          'Гидроудар, допуски кривой, автоматика и реальные потери установки здесь не закрыты.'),
        PageBreak(), p('В2 / проверка открытых ПК', heading),
        p('Для каждого насоса проверены 256 пар этажей на двух разных стояках при двух границах источника '
          '(512 сценариев). Разновысотные пары - проверка чувствительности, не доказательство '
          'возможности совместного тушения одного пожара.'),
        p('Идеальные местные ограничители поставлены в модели только на этажах, где номинальная '
          'статическая огибающая выше 0,45 МПа. Выход принят 0,210 МПа из табличного минимума ПК. '
          'Это консервативный опыт, а не назначенные изделия или монтажные уставки.')]
    for c in review['candidates']:
        floors = c['ideal_control_floors']
        story.append(p(c['candidate']['pump_model'] + ': идеальное ограничение на этажах '
            + ', '.join(map(str, floors)) + '.'))
        samples = []
        for levels in ([16,16], [1,16], [1,1]):
            s = next(s for s in c['scenarios'] if s['floors'] == levels and s['boundary'] == 'one_supply_guaranteed')
            for key, label in [('free','свободно'), ('ideal_selective','идеал. огр.')]:
                o = s[key]['operating']
                samples.append(('/'.join(map(str,levels)), label,
                    ' / '.join(n(x['flow_lps']) for x in o['cabinets']) if o else 'вне кривой',
                    ' / '.join(n(x['outlet_head_m']/MPA_TO_M) for x in o['cabinets']) if o else '-'))
        story.extend([table([('Этажи', 'Режим', 'q каждого ПК, л/с', 'p каждого ПК, МПа'), *samples], [22,35,55,58]),
            p('Идеальная модель: минимумы выполнены в '
              + str(c['summary']['ideal_selective'].get('meets_minimum',0)) + '/512 сценариях; '
              + 'максимум давления после ограничения ' + n(c['maximum_ideal_outlet_mpa']) + ' МПа.')])
    story.extend([PageBreak(), p('В2 / каталожные характеристики', heading)])
    d = Drawing(170*mm, 105*mm)
    x0,y0,w,h = 38,36,420,215
    def xy(q,head): return (x0+q/40*w, y0+head/70*h)
    for q in range(0,41,10):
        x,_ = xy(q,0)
        d.add(Line(x,y0,x,y0+h,strokeColor=colors.HexColor('#dce2e8'),strokeWidth=.4))
        d.add(String(x,y0-14,str(q),fontName='CNPStudy',fontSize=10,textAnchor='middle'))
    for head in range(0,71,10):
        _,y = xy(0,head)
        d.add(Line(x0,y,x0+w,y,strokeColor=colors.HexColor('#dce2e8'),strokeWidth=.4))
        d.add(String(x0-8,y-3,str(head),fontName='CNPStudy',fontSize=10,textAnchor='end'))
    palette = ['#647c91','#d86d35']
    for c,color in zip(review['candidates'],palette):
        points = [v for q,head in c['candidate']['curve'] for v in xy(q,head)]
        d.add(PolyLine(points,strokeColor=colors.HexColor(color),strokeWidth=1.7))
        s = next(s for s in c['scenarios'] if s['floors']==[16,16] and s['boundary']=='one_supply_guaranteed')['free']
        x,y=xy(s['pump_flow_m3h'],s['pump_head_m'])
        d.add(Circle(x,y,3.4,fillColor=colors.HexColor(color),strokeColor=colors.white))
    x,y=xy(review['required_q_m3h'],review['required_boost_m'])
    d.add(Circle(x,y,3.5,strokeColor=colors.black,fillColor=None,strokeWidth=1.1))
    _,y=xy(0,review['maximum_pump_shutoff_m'])
    d.add(Line(x0,y,x0+w,y,strokeColor=colors.HexColor('#a04040'),strokeWidth=.8,strokeDashArray=[4,3]))
    d.add(String(x0+5,y+5,'Предел H(0) = '+n(review['maximum_pump_shutoff_m'],2)+' м',fontName='CNPStudy',fontSize=10))
    d.add(String(x0,y0+h+17,'H насоса, м',fontName='CNPStudy',fontSize=11))
    d.add(String(x0+w,y0-29,'Q, м³/ч',fontName='CNPStudy',fontSize=11,textAnchor='end'))
    story.extend([d, p('Серо-синяя кривая - CDM20-4; оранжевая - CDM32-3. Цветные точки - '
        'совместно рассчитанная работа двух верхних ПК без регуляторов при одном вводе. '
        'Чёрное незалитое кольцо - минимальная расчётная потребность, НЕ рабочая точка. '
        'Пунктир ограничивает только H(0), не всю рабочую характеристику.'),
        table([('Насос / верхние ПК', 'Q, м³/ч', 'H насоса, м')]+[
            (c['candidate']['pump_model'], n(s['pump_flow_m3h']), n(s['pump_head_m']))
            for c in review['candidates']
            for s in [next(s for s in c['scenarios'] if s['floors']==[16,16]
                           and s['boundary']=='one_supply_guaranteed')['free']]], [92,39,39]),
        p('Кривые перенесены из точных таблиц CNP без изменения точек. Используется согласованная '
          'линейная интерполяция внутри опубликованного диапазона; экстраполяции нет. '
          'Резервный насос не добавлен к подаче рабочего. Потери внутри готовой станции '
          'не приняты равными нулю как проектное решение: это незакрытая проверка применимости кривой.'),
        PageBreak(),p('В2 / что остаётся подтвердить',heading),
        table([('Насос', 'Минимальный перепад на идеальном местном ограничителе'), *[
            (c['candidate']['pump_model'],n(c['minimum_control_drop_bar'])+' бар') for c in review['candidates']]], [80,90]),
        p('Ридан C101-R требует 1,5 бар по паспорту конкретного артикула. Не проходит для '
          'замены всех этих идеальных ограничителей: на верхнем регулируемом этаже перепада меньше. '
          'Это не запрет применения на отдельных нижних этажах. АСТА и РКМ-60 требуют данных '
          'точного исполнения; готовая реальная схема регулирования ещё не доказана.'),
        p('1. Подтвердить гарантированную характеристику PFFS с внутренней арматурой, '
          'максимальный напор при закрытых кранах и допуски. Для CDM20-4 запас особенно мал.'),
        p('2. Выбрать реальный комплект ПК и местное устройство по п.7.5 СП10. '
          'Проверить его характеристику и повторно решить совместные расходы. '
          'Идеальный ограничитель не равен диафрагме; размер отверстия из этой модели не выдаётся.'),
        p('3. Проверить NPSH, допустимые расходы, электроснабжение, резервирование, '
          'алгоритм управления, отключения участков кольца и зоны совместного тушения по планам.'),
        p('Источники и воспроизводимость',heading),
        p('Предоставленные каталоги: CDM/CDMF, PDF с.31 (20-4) и с.33 (32-3); '
          'PFFS, PDF с.38 / печатная с.39 и PDF с.40 / печатная с.40. '
          'Обе станции существуют в таблицах; мощность одного насоса 5,5 кВт; '
          'присоединения соответственно DN80 и DN100. Точное исполнение станции не угадано.'),
        p('Нормативная трассировка: предоставленный СП10.13130.2020 с изменением 1, '
          'пп.6.2.20, 7.5, 7.6, 7.14 и таблица 7.3. Справочная характеристика рукава и ствола - '
          'ранее согласованная модель L06 по ВНИИПО, не паспорт конкретного ПК.'),
        p('Это отдельное расчётное исследование, не комплект ИОС2 по ГОСТ Р21.619-2023. '
          'ПЗ, производственный подбор, спецификация и legacy не заменены. '
          'Исходные точки, SHA256 каталогов и все сценарии сохранены в JSON рядом с PDF.')])
    def footer(canvas,doc):
        canvas.setFont('CNPStudy',9)
        canvas.drawString(20*mm,12*mm,'ЗАРЯ / секция 3.2 / исследование L06')
        canvas.drawRightString(190*mm,12*mm,str(doc.page))
    SimpleDocTemplate(str(path),pagesize=A4,leftMargin=20*mm,rightMargin=20*mm,
        topMargin=18*mm,bottomMargin=22*mm,title='В2 - сравнение насосов и давления').build(
            story,onFirstPage=footer,onLaterPages=footer)


def main():
    basis=load_basis()
    bundle=design_ios2(build_project(make_request(make_draft(basis))),
        output_dir=str(OUTPUT/'documents'),fire_station=make_fire_station(basis),render_documents=False)
    review=calculate_comparison(basis,bundle)
    OUTPUT.mkdir(parents=True,exist_ok=True)
    (OUTPUT/'fire-pump-comparison.json').write_text(json.dumps(review,ensure_ascii=False,indent=2,allow_nan=False))
    path=OUTPUT/'В2-сравнение-насосов-CNP.pdf'
    render_comparison(path,review)
    print(json.dumps(dict(pdf=str(path),candidates=[{k:v for k,v in c.items() if k!='scenarios'}
        for c in review['candidates']]),ensure_ascii=False))


if __name__ == '__main__': main()
