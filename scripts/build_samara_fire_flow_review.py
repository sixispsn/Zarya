"""L06 private study extension. Does not modify legacy, Studio or production.

PYTHONPATH=. venv/bin/python scripts/build_samara_fire_flow_review.py
Baseline Samara packages remain a fixed-flow comparison, not free-discharge proof.
"""
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from xml.sax.saxutils import escape

from app.calc.fire_hydraulics import MPA_TO_M
from app.calc.fire_pressure_flow import (
    handbook_characteristic, required_common_header, check_pump_operating_point)
from app.calc.water_local_losses import local_loss_factor
from app.calc.fire_regulator_review import BAR_TO_M, screen_regulator, setpoint_window
from app.data.fire_regulators import CANDIDATES
from app.intake.project_builder import build_project
from app.pz.ios2_orchestrator import design_ios2
from scripts.build_samara_section_study import load_basis, make_draft, make_request, make_fire_station, OUTPUT, ROOT


def floor_network(base, levels, height):
    net=deepcopy(base)
    if len(net.cabinets)!=len(levels):
        raise ValueError("One floor per representative cabinet required")
    for cab,floor in zip(net.cabinets,levels):
        z=(floor-1)*height+1.35
        net.nodes[cab.node_id].elevation_m=z
        terminal=[s for s in net.segments if s.to_node==cab.node_id]
        if len(terminal)!=1:
            raise ValueError("Expected one independent terminal segment")
        terminal[0].length_m=z-net.nodes[terminal[0].from_node].elevation_m
        terminal[0].equiv_length_m=local_loss_factor("fire")*terminal[0].length_m
    return net


def calculate_review(basis, bundle):
    station=make_fire_station(basis)
    base=bundle.fire_station_result.network
    if len(base.cabinets)!=2 or len({c.riser_id for c in base.cabinets})!=2:
        raise ValueError("This study represents two independent risers only")
    chars=[handbook_characteristic(c,hose_material="rubber_lined",nozzle_kind="non_shutoff")
           for c in base.cabinets]
    floors=basis["study_assumptions"]["residential_floors"]
    height=basis["study_assumptions"]["floor_to_floor_m"]
    pump=bundle.project.fire_pumps
    # Identical supplies in this study. Do not silently pick one if they differ.
    supplies=[(s.guaranteed_head_m+s.source_elevation_m-station.pump_axis_m,
               s.maximum_head_m+s.source_elevation_m-station.pump_axis_m,
               sum(seg.A*seg.effective_length_m for seg in s.segments)) for s in station.supplies]
    if len(set(supplies))!=1:
        raise ValueError("Study review requires separate enumeration of unequal external supplies")
    suction_min,suction_max,resistance=supplies[0]
    static_header=suction_max+max(h for _,h in pump.curve)
    lowest_z=1.35
    header_static_limit=.9*MPA_TO_M+lowest_z-station.pump_axis_m
    controls={c.cabinet_id:c.minimum_head_m for c in chars}
    minimum_header=required_common_header(base,chars,ceiling_head_m=header_static_limit)
    required_q=minimum_header.total_flow_lps
    required_boost=minimum_header.header_head_m-(suction_min-resistance*required_q**2)
    scenarios=[]
    for a in range(1,floors+1):
        for b in range(1,floors+1):
            net=floor_network(base,(a,b),height)
            for mode,h_suction,r in (
                    ("one_supply_guaranteed",suction_min,resistance),
                    ("maximum_head_no_supply_loss_bound",suction_max,0.0)):
                args=dict(suction_static_head_m=h_suction,supply_resistance=r)
                free=check_pump_operating_point(net,chars,pump.curve,**args)
                controlled=check_pump_operating_point(net,chars,pump.curve,
                    ideal_outlet_heads=controls,**args)
                scenarios.append(dict(floors=[a,b],boundary=mode,free=asdict(free),ideal_control=asdict(controlled)))
    summary={}
    for kind in ('free','ideal_control'):
        counts={}
        for row in scenarios:
            status=row[kind]['status']
            counts[status]=counts.get(status,0)+1
        summary[kind]=counts
    drops=[c['control_drop_m'] for s in scenarios for c in
           (s['ideal_control']['operating'] or {}).get('cabinets',[])]
    review = dict(method="L06 pressure-driven handbook study", source=
        "https://mchs.fun/wp-content/uploads/2017/11/Vnutrenniy-PPV-VNIIPO-MCHS-Rossii-2010.pdf",
        legacy_modified=False, normative_coverage_verified=False, release_ready=False,
        characteristics=[asdict(c) for c in chars], pump_model=pump.model, pump_curve=pump.curve,
        pump_archived=pump.top3[0].archived if pump.top3 else None,
        minimum_header=asdict(minimum_header), minimum_boost_m=required_boost,
        fixed_flow_baseline_lps=5.2,
        supply_resistance=resistance, suction_static_guaranteed_m=suction_min,
        static_header_m=static_header, allowed_static_header_m=header_static_limit,
        lowest_static_pressure_mpa=(static_header+station.pump_axis_m-lowest_z)/MPA_TO_M,
        required_static_reduction_m=max(0,static_header-header_static_limit),
        control_drop_range_m=[min(drops),max(drops)],
        scenario_count=len(scenarios),summary=summary,scenarios=scenarios)
    review['regulator_review'] = review_regulators(review)
    return review


def review_regulators(review):
    """Screen the previous ideal duty, without substituting a real valve model."""
    operations = [s['ideal_control']['operating'] for s in review['scenarios']]
    if not operations or any(o is None for o in operations):
        raise ValueError('A complete ideal study is required for equipment screening')
    cabinets = [c for o in operations for c in o['cabinets']]
    flows = [c['flow_lps'] * 3.6 for c in cabinets]
    settings = [c['outlet_head_m'] / BAR_TO_M for c in cabinets]
    if max(settings) - min(settings) > 1e-5:
        raise ValueError('This screening expects one common ideal PC setting')
    available_drop_bar = min(c['control_drop_m'] for c in cabinets) / BAR_TO_M
    items = []
    for c in CANDIDATES:
        screen = screen_regulator(c, application='standalone_vpv',
            flow_range_m3h=(min(flows), max(flows)), setting_bar=min(settings),
            minimum_available_drop_bar=available_drop_bar,
            maximum_inlet_pressure_bar=review['lowest_static_pressure_mpa'] * 10)
        items.append(dict(candidate=asdict(c), cabinet_screen=asdict(screen)))
    # Necessary common-header conditions at the existing ideal flow, NOT a new
    # operating point. The common device and every PC share this pressure budget.
    available_header = min(o['header_head_m'] for o in operations)
    required_header = review['minimum_header']['header_head_m']
    ridan = next(c for c in CANDIDATES if c.id == 'ridan-c101-082X6100RL')
    optimistic = setpoint_window(required_dynamic_head_m=required_header,
        available_inlet_head_m=available_header,
        allowed_static_head_m=review['allowed_static_header_m'],
        minimum_control_drop_bar=ridan.minimum_drop_bar[0],
        no_flow_extra_bar=ridan.nominal_no_flow_extra_bar,
        lower_error_bar=0, upper_error_bar=0)
    return dict(selected_product=None, selection_confirmed=False,
        stage='manufacturer_limits_screening_not_equipment_selection',
        checked_at='2026-10-04', cabinet_flow_range_m3h=[min(flows), max(flows)],
        cabinet_setting_bar=min(settings), minimum_available_drop_bar=available_drop_bar,
        items=items, common_available_header_m=available_header,
        common_required_header_m=required_header,
        common_pressure_budget_m=available_header-required_header,
        ridan_common_window_optimistic_zero_tolerance=asdict(optimistic),
        rkm_nominal_static_ceiling_before_tolerance_m=
            review['allowed_static_header_m'] - BAR_TO_M)


def render_review(path, review):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Table,TableStyle,Spacer,PageBreak
    pdfmetrics.registerFont(TTFont('L06',str(ROOT/'app/assets/fonts/OpenGOSTtypeB-Regular.ttf')))
    body=ParagraphStyle('body',fontName='L06',fontSize=11,leading=14,spaceAfter=7)
    title=ParagraphStyle('title',parent=body,fontSize=20,leading=23,spaceAfter=14)
    def p(s,style=body): return Paragraph(escape(str(s)),style)
    def n(v,d=3): return f'{v:.{d}f}'.replace('.',',')
    def table(rows,widths):
        t=Table([[p(c) for c in row] for row in rows],colWidths=[w*mm for w in widths],repeatRows=1)
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#edf1f5')),
            ('GRID',(0,0),(-1,-1),.3,colors.HexColor('#b4bcc7')),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
        return t
    def sample(a,b,mode='one_supply_guaranteed'):
        return next(s for s in review['scenarios'] if s['floors']==[a,b] and s['boundary']==mode)
    rows=[]
    for a,b in ((16,16),(15,16),(1,16),(1,1)):
        s=sample(a,b)['free']; o=s['operating']
        rows.append((f'{a} / {b}',n(o['total_flow_lps']) if o else 'вне кривой',
                     ' / '.join(n(c['flow_lps']) for c in o['cabinets']) if o else '-',
                     ' / '.join(n(c['outlet_head_m']/MPA_TO_M) for c in o['cabinets']) if o else '-',
                     {'meets_minimum':'минимумы есть','insufficient_at_cabinet':'дефицит у ПК',
                      'outside_published_curve':'не определён'}.get(s['status'],s['status'])))
    top=sample(16,16)['ideal_control']; top_o=top['operating']
    h=review['minimum_header']
    story=[p('В2 / совместная работа ПК',title),p('Самара, секция 3.2. L06. 04.10.2026.'),
        p('Расчётное дополнение к контрольному примеру. Не рабочий проект и не окончательный подбор оборудования. '
          'Результаты фиксированных отборов в прежнем комплекте остаются сравнительной базой.'),
        p('Что изменилось',title),
        p('Расход каждого открытого ПК определяется совместно с давлением сети. После изменения расхода заново '
          'увязываются кольцо, потери вводов, давление на всасывании и точка на кривой насоса. '
          'Суммарный расход больше не задан заранее как 2 × 2,6 л/с.'),
        table([('Входные данные','Принято в этом расчёте'),
            ('Сеть','16 этажей; 2 представительных стояка. Геометрия, сопротивления и насосная - из контрольного примера секции 3.2.'),
            ('Комплект ПК','DN50, неперекрывной ствол 13 мм, прорезиненный рукав 20 м. Справочная характеристика, не паспорт модели.'),
            ('Минимум СП10, табл.7.3','2,6 л/с и 0,210 МПа при компактной струе 12 м. Оба условия проверяются независимо.'),
            ('Сравниваемый насос',review['pump_model']+
                ('; архивная каталожная модель, актуальность не подтверждена' if review['pump_archived']
                 else '; актуальность источника не установлена' if review['pump_archived'] is None else '')+
                '; точки Q-H без экстраполяции.'),
            ('Граница по источнику','Hгар=30 м; расчёт одного наружного ввода на весь расход. Отдельно: верхняя оценка Hmax=35 м без потерь наружного подвода.')],[46,124]),
        Spacer(1,8),p('Проверены 256 сочетаний этажей на двух разных стояках при двух границах источника: '
          '512 сценариев свободного истечения и 512 сценариев идеального регулирования. '
          'Разновысотные пары - чувствительность модели; их возможность совместного тушения должна подтверждаться планами.'),
        PageBreak(),p('В2 / результат без регулирования',title),
        table([('Этажи','Q, л/с','q ПК, л/с','p ПК, МПа','Проверка'),*rows],[22,26,42,42,38]),
        Spacer(1,8),table([('Статус / 512 сценариев','Количество'),
            ('Обеспечены табличные минимумы',review['summary']['free'].get('meets_minimum',0)),
            ('Не обеспечен хотя бы один ПК',review['summary']['free'].get('insufficient_at_cabinet',0)),
            ('Пересечение вне опубликованной кривой',review['summary']['free'].get('outside_published_curve',0))],[132,38]),
        p('«Минимумы есть» не означает годность решения: отдельно остаются максимальное давление, '
          'характеристики реального комплекта ПК, NPSH, резервирование, автоматика и покрытие помещений.'),
        p(f'Для двух верхних ПК минимальный напор общего коллектора по этой модели: {n(h["header_head_m"])} м; '
          f'суммарный расход {n(h["total_flow_lps"])} л/с; насосная добавка с одним наружным вводом '
          f'{n(review["minimum_boost_m"])} м. Это расчётная потребность, не рабочая точка насоса.'),
        p('Численное решение контролирует баланс подачи и отборов, невязку кольца и соответствие расхода '
          'давлению каждого ПК. Нет сходимости или нет точки в каталоге - нет подтверждённого результата.'),
        PageBreak(),p('В2 / что требуется от регулирования',title),
        p('Проверен идеальный ограничитель давления после клапана каждого активного ПК: 0,210 МПа. '
          'Это исследование требуемой функции, а не выбранное изделие или монтажная уставка. '
          'Реальный регулятор имеет погрешность и минимальный перепад; их здесь не выдумываем.'),
        table([('Расчётный показатель','Результат'),
            ('Два верхних ПК, один ввод',f'Q={n(top["pump_flow_m3h"])} м³/ч; Hнас={n(top["pump_head_m"])} м; '
                f'Hколл={n(top_o["header_head_m"])} м'),
            ('Идеальный контроль: минимумы',f'{review["summary"]["ideal_control"].get("meets_minimum",0)} из 512 сценариев'),
            ('Требуемое гашение при расходе',f'От {n(review["control_drop_range_m"][0])} до {n(review["control_drop_range_m"][1])} м по сценариям'),
            ('Статическая огибающая внизу',n(review['lowest_static_pressure_mpa'])+' МПа; предел самостоятельного ВПВ - 0,9 МПа'),
            ('Допустимая статика на коллекторе',n(review['allowed_static_header_m'])+' м; без ограничения '+n(review['static_header_m'])+' м'),
            ('Необходимое снижение статики','Не менее '+n(review['required_static_reduction_m'])+' м в рассмотренной огибающей')],[75,95]),
        p('Диафрагма при Q=0 не снижает статический напор. Нужна отдельная проверяемая функция '
          'ограничения статики сети: схема регулирования/зонирования, согласованная с требованиями пожарной насосной. '
          'Регулятор только после пожарного клапана не защищает всю сеть до него.'),
        p('Каталожный кандидат пока НЕ принят. Паспортная проверка трёх серий и общий бюджет '
          'давления приведены на листах 5-6. Идеальные 512 успешных сценариев не подтверждают '
          'работоспособность с реальными клапанами.'),
        PageBreak(),p('Методика и границы доказательства',title),
        p('Нормативное основание: предоставленный СП10.13130.2020, изменение 1: п.7.6 - совместная работа ПК; '
          'п.7.14 и таблица 7.3 - минимумы; п.7.5 - ограничение давления у ПК; п.6.2.20 - статика самостоятельного ВПВ. '
          'Таблица 7.3 и legacy не изменены.'),
        p('Инженерная модель, не дословная формула СП: для ствола q=10K√p; потери рукава Δp=Aq²L/100. '
          'Сложение даёт pкомплекта=q²(1/K²+AL)/100. Давление в МПа, q в л/с. '
          'K=0,588; A=0,0065; L=20 м. Источник: Мешман и др., «Внутренний противопожарный водопровод», '
          'ВНИИПО, 2010, с.109 и 385 (PDF 110 и 387).'),
        p('При табличных 0,210 МПа справочная модель даёт около 2,636 л/с, а не ровно 2,6. '
          'Это различие не скрыто под исправлением таблицы: расчёт проверяет одновременно оба табличных минимума. '
          'Совпадение с legacy для этого нового режима не заявляется; старый режим проверяется отдельно.'),
        p('Условия модели: ствол на отметке ПК, свободный выход в атмосферу, открытый клапан. '
          'Дополнительное сопротивление конкретного клапана, соединений, диапазон и допуски реального комплекта '
          'не подтверждены паспортом. Справочные коэффициенты не являются доказательством характеристик поставляемого оборудования.'),
        p('Поддерживается целое кольцо, два выхода одного коллектора и независимые конечные ветви ПК. '
          'Несколько активных ПК на одной общей ветви и ремонтные отключения новым режимом ещё не охвачены; '
          'существующий расчёт отказов остаётся расчётом заданных отборов.'),
        p('Расчётное приложение не меняет состав ПЗ и графических листов ИОС2 по ГОСТ Р21.619-2023. '
          'Баланс, планы, принципиальная схема и паспорта не заменяются этим отчётом. '
          'Выдача для экспертизы остаётся неподтверждённой.'),
        p('Источник физической модели: '+review['source']),
    ]
    rr = review['regulator_review']
    w = rr['ridan_common_window_optimistic_zero_tolerance']
    story.extend([
        PageBreak(), p('В2 / реальные регуляторы', title),
        p('Проверка изготовителей от 04.10.2026. Ни одна модель не записана в спецификацию '
          'как выбранная. Ниже проверены ограничения, а не смоделированы характеристики клапанов.'),
        p(f'Для замены идеального устройства у каждого ПК: расход около '
          f'{n(rr["cabinet_flow_range_m3h"][0])} м³/ч, выход {n(rr["cabinet_setting_bar"])} бар; '
          f'минимальный доступный перепад {n(rr["minimum_available_drop_bar"])} бар. '
          'Уставка 2,1 бар взята из прежнего идеального опыта; допуски реального изделия ещё не учтены.'),
        table([('Изделие / источник', 'Подтверждено', 'Результат проверки'),
            ('Ридан C101-R\n082X6100RL DN50\nПаспорт 08.09.2026, с.2, 4-5',
             'PN16; Q=0,5-45 м³/ч; Kv=65; настройка 0,5-8 бар; минимальный перепад 1,5 бар.',
             'Перепада у верхних ПК не хватает. Применение в отдельном ВПВ не подтверждено; '
             'паспорт исключает автоматическое водяное/пенное пожаротушение.'),
            ('АСТА Р01/02 DN50\nОписание серии, PDF с.1-4',
             'PN16; Kvs=50; минимум перепада 0,5-1,5 бар зависит от исполнения; пилот уточняется.',
             'Нельзя принять нижнюю границу 0,5 бар для любого клапана. Нужны исполнение, '
             'рабочий диапазон расходов и подтверждение для ВПВ.'),
            ('ПромВодОчистка РКМ-60 DN50\nСтатья изготовителя',
             'Указано противопожарное применение и максимум 16 бар; в тупике - уставка плюс 1 бар.',
             'Кандидат для запроса паспорта. Не известны Δpmin, точность, '
             'кавитационный диапазон и рабочие расходы.')], [52,58,60]),
        p('Ридан: паспорт конкретного артикула требует 1,5 бар. В РЭ встречается 12 м, '
          'в общем каталоге 12-15 м. Разночтение зафиксировано; благоприятное значение '
          'не подставляется. При нашем запасе около 5,5 м ни одно из этих значений не выполняется.'),
        p('Kvs не является максимальным рабочим расходом. PN и герметичное закрытие сами '
          'по себе не подтверждают пригодность для ВПВ, точность удержания или безопасность схемы.'),
        p('Источники: ridan.ru/product/082X6100RL; '
          'npoasta.ru/data/description/pilot_valve/ASTA_R01_feb26.pdf; '
          'prom-water.ru/articles/klapan-dlya-sistem-pozharotusheniya/. '
          'Полные URL, локаторы и SHA256 паспортов сохранены в JSON расчёта.'),
        PageBreak(), p('В2 / ограничение статики', title),
        p('Две разные функции: общий узел ограничивает давление защищаемой части сети; '
          'местные устройства у ПК регулируют расход открытых кранов. Участок перед общим '
          'регулятором остаётся под исходным давлением и проверяется отдельно.'),
        table([('Проверка при существующем идеальном расходе', 'Напор, м'),
            ('Минимум после общего узла для двух верхних ПК', n(rr['common_required_header_m'])),
            ('Доступно перед общим узлом при одном вводе', n(rr['common_available_header_m'])),
            ('Весь запас для общего узла и местного регулирования', n(rr['common_pressure_budget_m'])),
            ('Статический предел коллектора по нижнему ПК', n(review['allowed_static_header_m'])),
            ('Ридан: верхняя динамическая граница после вычета 1,5 бар', n(w['dynamic_ceiling_head_m'])),
            ('РКМ-60: номинальный потолок уставки при добавке 1 бар в тупике',
             n(rr['rkm_nominal_static_ceiling_before_tolerance_m']))], [136,34]),
        p('Ридан не проходит даже оптимистическую проверку общего узла с нулевыми допусками: '
          f'после него доступно не более {n(w["maximum_setting_head_m"])} м, '
          f'а требуется минимум {n(w["minimum_setting_head_m"])} м. '
          'Это отсев конкретного сочетания насоса и устройства, не запрет модели для всех объектов.'),
        p('Для РКМ-60 вычитание 1 бар относится только к номинальной статике. Без точности, '
          'минимального перепада, расходной и кавитационной характеристик монтажная уставка '
          'не определяется. Редукционный клапан также не сбрасывает уже запертое избыточное '
          'давление: нужны проверка начального состояния, отказов и схема защиты.'),
        p('Следующий расчёт: схема общего ограничения давления с местным регулированием '
          'только там, где оно необходимо; затем совместная увязка с насосом. Запас одного '
          'и того же напора нельзя одновременно потратить на общий и местный регуляторы.'),
        p('Для изготовителя подготовлены исходные в JSON: расходы, требуемое выходное '
          'давление, диапазон перепадов и статический максимум. Необходимо подтвердить '
          'исполнение для ВПВ, диапазон Q/P, Δpmin, допуски и закрытие при Q=0, кавитацию, '
          'схему установки и поведение при отказах. Запросы наружу не отправлялись.'),
        p('Окончательный насос и регуляторы не приняты. Legacy, продуктивный подбор и '
          'спецификация не изменены; это дополнение к исследовательскому расчёту.')])
    def page(canvas,doc):
        canvas.setFont('L06',9)
        canvas.drawString(20*mm,12*mm,'ЗАРЯ / секция 3.2 / отдельная методика L06')
        canvas.drawRightString(190*mm,12*mm,str(doc.page))
    SimpleDocTemplate(str(path),pagesize=A4,leftMargin=20*mm,rightMargin=20*mm,
        topMargin=18*mm,bottomMargin=22*mm,title='В2 - совместная работа пожарных кранов').build(
            story,onFirstPage=page,onLaterPages=page)


def main():
    basis=load_basis()
    bundle=design_ios2(build_project(make_request(make_draft(basis))),
        output_dir=str(OUTPUT/'documents'),fire_station=make_fire_station(basis),render_documents=False)
    review=calculate_review(basis,bundle)
    source=ROOT/'tmp/pdfs/vniipo-vpv-2010.pdf'
    if source.exists(): review['handbook_sha256']=sha256(source.read_bytes()).hexdigest()
    OUTPUT.mkdir(parents=True,exist_ok=True)
    (OUTPUT/'fire-pressure-flow-review.json').write_text(json.dumps(review,ensure_ascii=False,indent=2,allow_nan=False))
    path=OUTPUT/'В2-совместная-работа-ПК.pdf'
    render_review(path,review)
    print(json.dumps(dict(pdf=str(path),summary=review['summary'],minimum_header=review['minimum_header'],
        boost=review['minimum_boost_m'],static_reduction=review['required_static_reduction_m']),ensure_ascii=False))


if __name__=='__main__': main()
