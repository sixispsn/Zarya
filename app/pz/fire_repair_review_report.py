"""Separate repair-review annex; never replace the reviewed whole IOS2 package."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape


def render_repair_review(path, r, *, document=None):
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, PageBreak, Spacer
    from app.pz.drafting_font import DRAFTING_FONT_PATH, ensure_drafting_font_registered
    from app.pz.project import DocumentInfo
    from app.pz.fire_station_input_report import frame_station_calculation
    from app.calc.fire_hydraulics import MPA_TO_M

    ensure_drafting_font_registered()
    pdfmetrics.registerFont(TTFont('RepairReview',str(DRAFTING_FONT_PATH)))
    body=ParagraphStyle('body',fontName='RepairReview',fontSize=11,leading=14,spaceAfter=7)
    small=ParagraphStyle('small',parent=body,fontSize=10,leading=12,spaceAfter=5)
    heading=ParagraphStyle('heading',parent=body,fontSize=18,leading=22,spaceAfter=11)
    sub=ParagraphStyle('sub',parent=body,fontSize=13,leading=16,spaceBefore=5,spaceAfter=8)
    def p(text,style=body):
        for a,b in [('—','-'),('–','-'),('−','-'),('²','2'),('³','3')]: text=str(text).replace(a,b)
        return Paragraph(escape(text),style)
    def n(x,d=3):return f'{x:.{d}f}'.replace('.',',')
    def table(rows,widths):
        t=Table([[p(v,small) for v in row] for row in rows],colWidths=[w*mm for w in widths],repeatRows=1)
        t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.3,colors.HexColor('#8d9ca5')),
            ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#edf1f3')),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),
            ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
        return t
    nominal=lambda c:next(v for v in c['variants'] if v['axis_offset_px']==0)
    total=sum(v['scenario_count'] for c in r['cases'] for v in c['variants'])
    header=next(c for c in r['cases'] if c['id']=='header-1');worst=nominal(header)['worst']
    pc=worst['cabinet']
    rows=[('Отключение','Минимумы ПК','Минимум, МПа')]
    for c in r['cases']:
        v=nominal(c)
        label=c['label'] if c['kind']!='ring_segment' else 'Участок '+c['id']+': '+c['label']
        rows.append((label,f'{v["summary"].get("meets_minimum",0)} / {v["scenario_count"]}',n(v['pressure_range_mpa'][0],4)))
    story=[p('В2. Проверка ремонтных режимов',heading),
        p('Самара, секция 3.2. Насосная CNP CDM32-3, один рабочий + один резервный. '
          'Отдельное расчётное приложение; исходный комплект на сайте не заменён.'),
        p('Выявлен дефицит при отключении выхода НУ',sub),
        p('Отключение наружного ввода и отдельных сегментов кольца проходит в принятой модели. '
          'При работе через один выход напорного коллектора минимумы ПК обеспечиваются не во всех сочетаниях.'),
        table(rows,[99,39,36]),Spacer(1,3*mm),
        p('Таблица: номинальное чтение диафрагм; в каждой строке 16 × 16 пар этажей × 2 границы источника. '
          'Это диагностические сочетания двух характерных стояков, не доказательство покрытия помещений.',small),
        p(f'Худший номинальный случай: этажи {worst["floors"][0]} и {worst["floors"][1]}. '
          f'У ПК 15-го этажа p={n(pc["outlet_head_m"]/MPA_TO_M,6)} МПа при минимуме '
          f'{n(pc["minimum_head_m"]/MPA_TO_M,3)} МПа; q={n(pc["flow_lps"],4)} л/с при минимуме '
          f'{n(pc["minimum_flow_lps"],1)} л/с.'),
        p('Резервный насос заменяет рабочий. Их подачи не складываются; включение идентичного '
          'резерва не исправляет этот установившийся режим.',small),
        PageBreak(),p('Почему падает давление у ПК',heading),
        p('Сравниваются одинаковые этажи 15 / 10, Hгар=30 м и прежние отверстия. '
          'Расход каждого ПК заново найден совместно с кривой одного насоса; табличные 5,2 л/с не подставляются вместо решения.'),
    ]
    a,b=[x for x in r['comparison']['cases']]
    rows=[('Параметр','Кольцо целое','Выход НУ 1 закрыт')]
    for label,key in [('Подача насоса, м3/ч','pump_flow_m3h'),('Напор насоса, м','pump_head_m'),
                      ('На всасывании насоса, м','suction_head_m')]:
        rows.append((label,n(a['result'][key]),n(b['result'][key])))
    rows.append(('Напор общего коллектора, м',*[n(x['result']['operating']['header_head_m']) for x in (a,b)]))
    for label,key in [('Потери наружного подвода, м','external_loss_m'),
                      ('Всасывающая обвязка, м','station_suction_loss_m'),
                      ('Напорная обвязка, м','station_discharge_loss_m')]:
        rows.append((label,n(a[key]),n(b[key])))
    for i in (0,1):
        floor=r['comparison']['floors'][i]
        rows.append((f'ПК {floor}-го этажа: расход, л/с',*[n(x['result']['operating']['cabinets'][i]['flow_lps'],4) for x in (a,b)]))
        rows.append((f'ПК {floor}-го этажа: давление, МПа',*[n(x['result']['operating']['cabinets'][i]['outlet_head_m']/MPA_TO_M,6) for x in (a,b)]))
    story += [table(rows,[86,44,44]),Spacer(1,3*mm),
        p('Весь расход теперь проходит через один оставшийся напорный выход, затем часть воды '
          'идёт по кольцу к удалённому стояку. Потери меняются вместе с распределением расходов. '
          'Повышать насосный напор без повторной проверки нижних ПК и статики нельзя.',small),
        p('Следующее проектное действие',sub),
        p('Увязать диафрагмы и сопротивления напорных выходов с ремонтными режимами. '
          'Пока ни насос, ни диаметры, ни отверстия автоматически не изменены. '
          'Любой новый вариант должен повторно пройти всю матрицу, включая максимальные давления.',small),
        PageBreak(),p('Чувствительность и границы вывода',heading),
        p(f'Всего рассчитано {total} режимов. Номинальная обвязка одинакова во всех прогонах. '
          'Сдвиг шкалы +/-2 px проверяет чувствительность чтения номограммы, не заменяет паспортные допуски.'),
        table([('Отключение','-2 px','0 px','+2 px'),*[
            (c['label'] if c['kind']!='ring_segment' else 'Участок '+c['id'],*[
                str(next(v for v in c['variants'] if v['axis_offset_px']==o)['summary'].get('meets_minimum',0))+'/512'
                for o in (-2,0,2)]) for c in r['cases']]],[84,30,30,30]),
        Spacer(1,3*mm),
        *[p(t,small) for t in r['retained_limits'][:5]],
        p('Нормативная трассировка и состав',sub),
        p('Предоставленные СП10.13130.2020 и изменение 1: п.12.27 - оставшиеся входные '
          'трубопроводы на полный расход; пп.6.1.12, 13.1 - ремонтное секционирование; '
          'п.7.6 - совместно работающие ПК. Проверка реального расположения задвижек и '
          'отключаемых стояков остаётся отдельной задачей.',small),
        p('ГОСТ Р21.619-2023, п.5.1.8: приведены насос, рабочие параметры, резерв и давления. '
          'Алгоритм автоматизации и баланс по форме 2 приложения А в ранее собранном ИОС2 '
          'не изменены. Этот расчётный лист не является полным комплектом для экспертизы.',small),
        p('Контроль целостности: '+r['baseline_snapshot'][:24]+'…; полные исходные, невязки '
          'и результаты каждого режима сохранены в repair-review.json.',small)]
    content=BytesIO()
    SimpleDocTemplate(content,pagesize=A4,leftMargin=25*mm,rightMargin=10*mm,
        topMargin=12*mm,bottomMargin=65*mm,title='В2. Ремонтные режимы').build(story)
    pdf=PdfReader(content);writer=PdfWriter()
    if len(pdf.pages)!=3:raise ValueError(f'Expected 3 review sheets, got {len(pdf.pages)}')
    for i,page in enumerate(pdf.pages,1):
        writer.add_page(page)
        writer.add_outline_item(['Результаты проверки','Баланс напора','Границы применимости'][i-1],i-1)
    writer.add_metadata({'/Title':'В2. Самара. Ремонтные режимы','/Author':'ЗАРЯ'})
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    output=BytesIO();writer.write(output)
    Path(path).write_bytes(frame_station_calculation(output.getvalue(), document or DocumentInfo(),
        'В2. Ремонтные режимы'))
    return str(path)
