"""Three-sheet, model-bound aperture/repair annex; no independent selection."""
from io import BytesIO
from xml.sax.saxutils import escape


def correction_review_pdf(r, *, document=None, framed=True):
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, PageBreak, Spacer
    from app.data.fire_diaphragm_layout import diaphragm_groups, floor_label
    from app.pz.drafting_font import DRAFTING_FONT_PATH
    from app.pz.project import DocumentInfo
    from app.pz.fire_station_input_report import frame_station_calculation

    pdfmetrics.registerFont(TTFont('DiaphragmReview',str(DRAFTING_FONT_PATH)))
    body=ParagraphStyle('body',fontName='DiaphragmReview',fontSize=11,leading=14,spaceAfter=8)
    small=ParagraphStyle('small',parent=body,fontSize=10,leading=12,spaceAfter=5)
    heading=ParagraphStyle('heading',parent=body,fontSize=17,leading=21,spaceAfter=12)
    sub=ParagraphStyle('sub',parent=body,fontSize=13,leading=16,spaceBefore=8,spaceAfter=8)
    def p(t,style=body):
        t=str(t)
        for a,b in [('—','-'),('–','-'),('−','-'),('³','3'),('²','2')]:t=t.replace(a,b)
        return Paragraph(escape(t),style)
    def n(v,d=3):return f'{v:.{d}f}'.replace('.',',')
    def table(rows,widths):
        out=Table([[p(v,small) for v in row] for row in rows],colWidths=[v*mm for v in widths],repeatRows=1)
        out.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.3,colors.HexColor('#9aabb4')),
            ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eef2f4')),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),
            ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
        return out
    correction=r['correction']
    variants=[v for c in r['cases'] for v in c['variants']]
    worst_case,worst=min(((c,v) for c in r['cases'] for v in c['variants']),
        key=lambda cv:cv[1]['pressure_range_mpa'][0])
    total=sum(v['scenario_count'] for v in variants)
    minimum=min(v['pressure_range_mpa'][0] for v in variants)
    maximum=max(v['pressure_range_mpa'][1] for v in variants)
    story=[p('В2. Уточнение диафрагм',heading),
        p('Самара, секция 3.2. Увязка с отключениями расчётной сети. '
          'Насос CDM32-3, обвязка и диаметры труб сохранены. Резерв в расход не включён.'),
        p('Изменение: этаж '+', '.join(map(str,correction['changed_floors']))+': '
          +n(correction['old_mm'],1)+' -> '+n(correction['new_mm'],1)+' мм.',sub),
        table([('Этажи','Отверстие, мм','Количество в модели'),
            *[(floor_label(g),n(g['aperture_mm'],1),str(2*(g['end']-g['start']+1)))
              for g in diaphragm_groups(r['apertures_mm'])],
            ('16','Без диафрагмы','2 ПК')],[42,65,67]),
        p('Показаны два характерных стояка. Эти количества не являются ведомостью всех '
          'ПК здания и не подставляются в закупку без планов.',small),
        p('Сравнение соседних размеров',sub),
        table([('Изменяемые этажи','Отверстие, мм','Прошло / всего','Минимум, МПа'),
            *[('13-15' if t['scope']=='group' else '15',n(t['diameter_mm'],1),
               f"{t['passed']}/{t['total']}",n(t['minimum_pressure_mpa'],6))
              for t in correction['trials']]],[43,35,49,47]),
        p(correction['decision'],small),
        PageBreak(),p('Штатный и ремонтные режимы',heading),
        p('Для каждого состояния: 16 × 16 пар этажей, две границы источника, '
          'три положения средней шкалы номограммы (0, -2, +2 px). '
          'Итого '+str(total)+' сочетаний. Отключается один элемент за раз.',small),
        table([('Состояние сети','0 px','-2 px','+2 px','Диапазон, МПа'),
            *[(c['label'],
               *[f"{next(v for v in c['variants'] if v['axis_offset_px']==o)['summary'].get('meets_minimum',0)}/512"
                 for o in (0,-2,2)],
               n(min(v['pressure_range_mpa'][0] for v in c['variants']),4)+' - '+
               n(max(v['pressure_range_mpa'][1] for v in c['variants']),4)) for c in r['cases']]],[58,25,25,25,41]),
        Spacer(1,3*mm),
        p('Минимальное давление: '+n(minimum,6)+' МПа.',sub),
        p(worst_case['label']+'; этажи '+str(worst['worst']['floors'][0])+'/'+str(worst['worst']['floors'][1])+
          '; сдвиг '+n(worst['axis_offset_px'],0)+' px. Требуемый минимум в этой модели '
          '0,210 МПа. Запас мал и не подтверждает допуски реального изделия.',small),
        p('Максимальное динамическое давление: '+n(maximum,6)+' МПа. '
          'Статическое давление у нижнего ПК при Q=0: '+n(r['nominal_static_lowest_pc_mpa'],6)+' МПа. '
          'Изменение диафрагмы не снижает статику.',small),
        p('Статус: расчётные минимумы и динамические ограничения пройдены при принятых '
          'исходных данных. Допуск полного проекта к экспертизе не выдан.',small),
        PageBreak(),p('Границы проверки и согласованность',heading),
        p('Решение пересчитано заново. Потери обвязки определены по фактическому расходу '
          'отдельно до и после насоса. Подачи рабочего и резервного насосов не складываются.',small),
        p('Что остаётся неподтверждённым',sub),
        *[p(text,small) for text in r['retained_limits']],
        p('Также требуются паспортные допуски диафрагм, NPSH и допустимая область работы '
          'выбранного насосного исполнения. Проверка номограммы ±2 px не заменяет эти данные.',small),
        p('Один источник для документов',sub),
        p('Расчёт, ПЗ, схема и спецификация получают одну поэтажную ведомость. '
          'Группы образуются только из соседних этажей с одинаковым отверстием. '
          'Проверка подписи исходных данных не позволяет использовать старые результаты '
          'после изменения сети или насосной.'),
        p('Нормативная трассировка',sub),
        p('СП 10.13130.2020 с изменением 1: п.7.5 допускает одинаковые отверстия на '
          'нескольких этажах, но не требует объединять весь диапазон 13-15; '
          'п.7.6 - взаимное влияние расходов и давлений. ГОСТ Р21.619-2023: '
          'п.5.1.8 - напоры, насосная и рабочая точка; п.5.1.14 - автоматизация. '
          'Баланс по п.5.1.21 и форме 2 приложения А включён отдельным листом основного комплекта.',small),
        p('Приложение относится только к фиксированному контрольному примеру Самары. '
          'Это не универсальный подбор для любого жилого здания.',small)]
    content=BytesIO()
    SimpleDocTemplate(content,pagesize=A4,leftMargin=25*mm,rightMargin=10*mm,
        topMargin=12*mm,bottomMargin=65*mm).build(story)
    pdf=PdfReader(content)
    if len(pdf.pages)!=3:raise ValueError(f'Expected three review sheets, got {len(pdf.pages)}')
    writer=PdfWriter();document=document or DocumentInfo()
    titles=['Уточнение диафрагм','Штатный и ремонтные режимы','Границы проверки']
    for i,page in enumerate(pdf.pages,1):
        writer.add_page(page)
        writer.add_outline_item(titles[i-1],i-1)
    writer.add_metadata({'/Title':'В2 - уточнение диафрагм и проверка отключений','/Author':'ЗАРЯ'})
    out=BytesIO();writer.write(out)
    # A parent report must frame the combined document once, not restart at 1/3.
    return (frame_station_calculation(out.getvalue(), document, 'В2. Диафрагмы и отключения')
            if framed else out.getvalue())
