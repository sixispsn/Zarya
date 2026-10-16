"""Five-sheet calculation/automation annex using the shared SPDS frame."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape


def render_station_design(path, r, *, document=None):
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, PageBreak, Spacer, Flowable
    from app.pz.drafting_font import DRAFTING_FONT_PATH, ensure_drafting_font_registered
    from app.pz.project import DocumentInfo
    from app.pz.fire_station_input_report import frame_station_calculation
    from app.data.fire_diaphragm_layout import diaphragm_groups, floor_label

    ensure_drafting_font_registered()
    pdfmetrics.registerFont(TTFont('StationDesign',str(DRAFTING_FONT_PATH)))
    body=ParagraphStyle('body',fontName='StationDesign',fontSize=11,leading=14,spaceAfter=7)
    small=ParagraphStyle('small',parent=body,fontSize=10,leading=12,spaceAfter=6)
    heading=ParagraphStyle('heading',parent=body,fontSize=18,leading=22,spaceAfter=12)
    sub=ParagraphStyle('sub',parent=body,fontSize=13,leading=16,spaceBefore=6,spaceAfter=8)
    # Keep glyphs supported by the existing drafting font.
    def clean(t):
        for a,b in [('—','-'),('–','-'),('−','-'),('→',' -> '),('ζ','zeta'),('³','3'),('²','2')]:
            t=str(t).replace(a,b)
        return t
    def p(t,style=body):return Paragraph(escape(clean(t)),style)
    def n(v,d=3):return f'{v:.{d}f}'.replace('.',',')
    def table(rows,widths):
        t=Table([[p(v,small) for v in row] for row in rows],colWidths=[w*mm for w in widths],repeatRows=1)
        t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.3,colors.HexColor('#9aabb4')),
            ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eef2f4')),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),
            ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
        return t

    class Chart(Flowable):
        def __init__(self):
            super().__init__();self.width=174*mm;self.height=77*mm
        def draw(self):
            c=self.canv;x0,y0=12*mm,13*mm;w,h=156*mm,55*mm
            qmax=max(x['q_m3h'] for x in r['chart_samples']);hmax=60
            point=lambda q,head:(x0+w*q/qmax,y0+h*head/hmax)
            c.setFont('StationDesign',9)
            for q in range(0,int(qmax)+1,10):
                x,y=point(q,0);c.setStrokeColor(colors.HexColor('#d8dfe3'));c.setLineWidth(.3)
                c.line(x,y,x,y+h);c.setFillColor(colors.black);c.drawCentredString(x,y-10,str(q))
            for head in range(0,hmax+1,10):
                x,y=point(0,head);c.setStrokeColor(colors.HexColor('#d8dfe3'));c.line(x,y,x+w,y)
                c.setFillColor(colors.black);c.drawRightString(x-5,y-3,str(head))
            for field,color,dash in [('single_pump_head_m','#111111',False),('station_net_boost_m','#167888',True)]:
                c.setStrokeColor(colors.HexColor(color));c.setLineWidth(1.4);c.setDash(4,2) if dash else c.setDash()
                path=c.beginPath()
                for i,row in enumerate(r['chart_samples']):
                    x,y=point(row['q_m3h'],row[field]);path.moveTo(x,y) if i==0 else path.lineTo(x,y)
                c.drawPath(path)
            c.setDash();c.setFillColor(colors.black);c.drawString(x0, y0+h+9,'H, м')
            c.drawRightString(x0+w,y0-23,'Q, м3/ч')
            x,y=point(r['required_q_m3h'],r['required_bare_pump_head_m'])
            c.setStrokeColor(colors.black);c.circle(x,y,3,stroke=1,fill=0)
            op=r['representative_operating_point']['result']
            if op['operating']:
                x,y=point(op['pump_flow_m3h'],op['pump_head_m'])
                c.setFillColor(colors.HexColor('#c95720'));c.circle(x,y,3,stroke=0,fill=1)

    nominal=next(v for v in r['variants'] if v['loss_scale']==1 and v['axis_offset_px']==0)
    op=r['representative_operating_point']['result']
    audit=r['pipework'];nominal_pass=r['adopted_assumptions_pass']
    groups=diaphragm_groups(r['nominal_apertures_mm'])
    story=[p('В2. Насосная установка 1 + 1',heading),
        p('Самара, секция 3.2. Расчётное приложение к решениям стадии П. '
          'Принятая обвязка - предварительное проектное решение, не паспорт заводской станции.'),
        table([('При минимальной расчётной подаче','Значение'),
            ('Подача одного рабочего насоса',n(r['required_q_m3h'])+' м³/ч'),
            ('Требуемая добавка на границах станции',n(r['required_net_station_boost_m'])+' м'),
            ('Потери принятой обвязки',n(audit['total_loss_m'])+' м'),
            ('Требуется / имеется у насоса',n(r['required_bare_pump_head_m'])+' / '+n(r['catalog_pump_head_at_required_q_m'])+' м')],[123,51]),
        Spacer(1,4*mm),Chart(),
        p('Сплошная линия - одиночный CDM32-3 (рабочий ИЛИ резервный). '
          'Пунктир - расчётная добавка станции после вычета обвязки; не заводская гарантия. '
          'Окружность - минимальное задание одиночному насосу; цветная точка - совместная работа с двумя верхними ПК.',small),
        p(('Минимумы проверены при принятых допущениях.' if nominal_pass else
           'Выявлены непроходящие режимы: предварительный подбор требует изменения.'),sub),
        p('Резерв установлен, в норме не работает. Подачи двух насосов не складываются. '
          'Полный комплект ИОС2 этим приложением не заменяется.',small),
        PageBreak(),p('Обвязка: откуда берутся потери',heading),
        p('Расчёт одного активного пути. Две одинаковые насосные ветви взаимозаменяемы; '
          'сопротивление закрытой резервной ветви не добавляется. Общая арматура считается один раз.',small)]
    rows=[('Элемент / сторона','Исходное значение','Потеря, м')]
    for e in audit['elements']:
        detail=(f'L={e["length_m"]:g} м; A={e["value"]:g}' if e['method']=='A_L' else
                f'Kv ≥ {e["value"]:g} м³/ч' if e['method']=='Kv' else
                f'zeta={e["value"]:g}; dвн={e["inner_mm"]:g} мм')
        rows.append((e['name'],detail,n(e['loss_m'])))
    story += [table(rows,[77,65,32]),Spacer(1,3*mm),
        p('Hлинейн = A·L·q²; Hарматуры = (Q/Kv)²·100000/(1000·9,81); '
          'Hфасонины = zeta·v²/(2·9,81). q - л/с, Q - м³/ч. '
          'Общие местные 10% поверх этой суммы НЕ прибавляются.',small),
        p('На всасывании '+n(audit['losses_m']['suction'])+' м; на напоре '
          +n(audit['losses_m']['discharge'])+' м; всего '+n(audit['total_loss_m'])+' м.',sub),
        p('Длины и суммарные zeta приняты проектировщиком. A=0,0023/0,011 сохранены из учебной '
          'базы секции, а не подтверждены для заводских коллекторов. Kv - требования к выбору '
          'арматуры, не паспорт неизвестного изделия. Для обратного клапана проверяется полная '
          'кривая потерь, включая открытие пружины, во всём рабочем диапазоне.',small),
        p('Геометрия труб для скоростей: сталь ВГП DN100 114×4,5 (dвн=105); '
          'DN65 75,5×4,0 (dвн=67,5). Каталожное исполнение PFFS этим не изменено.',small),
        PageBreak(),p('Повторная совместная проверка',heading),
        p('Каждый вариант: 16 × 16 пар этажей × 2 границы источника = 512 режимов. '
          'Кольцо неповреждённое; один насос. 30 м - заданный гарантированный напор; '
          '35 м - ранее принятое учебное максимальное значение.',small),
        table([('Множитель потерь','Сдвиг шкалы, px','Минимумы ПК','Давление у ПК, МПа'),
            *[(n(v['loss_scale'],0),n(v['axis_offset_px'],0),
                str(v['summary'].get('meets_minimum',0))+'/'+str(v['scenario_count']),
                ' - '.join(n(x,4) for x in v['pressure_range_mpa']) if v['pressure_range_mpa'] else 'Нет решения')
              for v in r['variants']]],[38,40,38,58]),Spacer(1,4*mm),
        p('0 - только сравнение без обвязки, не принятый проект. 1 - принятые сопротивления. '
          '2 - удвоенные сопротивления для проверки чувствительности, не нормативный запас. '
          'Сдвиг ±2 пикселя - только чувствительность чтения номограммы, не допуск изделия.',small),
        p('При принятой обвязке: Q='+' - '.join(n(x) for x in nominal['flow_range_m3h'])+' м³/ч. '
          'Для пары верхних ПК: Q='+n(op['pump_flow_m3h'])+' м³/ч; Hнас='+n(op['pump_head_m'])+' м; '
          'Hвсас='+n(op['suction_head_m'])+' м.' if op['operating'] else 'Для верхних ПК решение не найдено.'),
        p('Шайбы по этажам: '+' / '.join(floor_label(g) for g in groups)+': '
          +' / '.join(n(g['aperture_mm'],1).removesuffix(',0') for g in groups)+' мм. На 16-м этаже без шайбы. '
          'Прежний набор при новой обвязке: '
          +str(r['previous_layout_check']['summary'].get('meets_minimum',0))+'/512. '
          +('Уточнение 15-го этажа и ремонтные режимы приведены далее; потери обвязки не уменьшались.'
            if r.get('repair_review') else
            'После пересчёта увеличены отверстия двух верхних групп; потери обвязки не уменьшались.'),small),
        p('Статика: '+n(r['nominal_static_lowest_pc_mpa'],6)+' МПа у нижнего ПК. '
          'При Q=0 потери обвязки и шайб равны нулю. Верхний допустимый напор насоса '
          'для принятой базы '+n(r['maximum_allowed_pump_shutoff_m'])+' м; '
          'заводские допуски и переходные процессы проверяются отдельно.',small),
        p('Не подтверждены: реальные границы ТУ, NPSH/минимальная подача и потребляемая мощность, '
          'паспортный диапазон станции, допуски шайб, покрытие помещений и '
          +('границы реальных ремонтных секций. ' if r.get('repair_review') else 'отключения кольца. ')+
          'Положительный результат этой модели не означает готовность всего проекта к экспертизе.',small),
        PageBreak(),p('Текст для пояснительной записки',heading),
        p('ГОСТ Р21.619-2023: п.5.1.8 - напоры, рабочая точка, резервирование и алгоритм; '
          'п.5.1.14 - автоматизация. Ниже - связанный с расчётом фрагмент, не весь подраздел ИОС2.',small),
        *[p(t) for t in r['pz_text']],
        PageBreak(),p('Задание на автоматизацию',heading),
        p('Проектные требования. Не подтверждение конкретного шкафа и не инструкция '
          'по перенастройке установленного оборудования.',small),
        *[p(f'{i}. {text}') for i,text in enumerate(r['automation']['requirements'],1)],
        p(r['automation']['equipment_acceptance']),
        p('Источники и границы',sub),
        p('СП10.13130.2020, п.12.3 и изменение 1 (PDF с.25); ГОСТ Р21.619-2023, '
          'пп.5.1.8, 5.1.14. Q-H: пользовательский каталог CDM/CDMF, PDF с.33; '
          'состав PFFS: каталог, PDF с.40. Допущения обвязки согласованы пользователем 04.10.2026. '
          'Обязательный баланс ИОС2 по п.5.1.21 и форме 2 приложения А в этом дополнении не изменяется.',small),
        p('Изготовителю ничего не отправлено. Исходный каталог, обе копии legacy и ранее '
          'собранные полные комплекты сохранены. Числа и все сценарии записаны в сопровождающий JSON.',small)]

    content=BytesIO()
    SimpleDocTemplate(content,pagesize=A4,leftMargin=25*mm,rightMargin=10*mm,
        topMargin=12*mm,bottomMargin=65*mm,title='В2 - расчёт обвязки и задание на автоматизацию').build(story)
    pdf=PdfReader(content);writer=PdfWriter()
    if len(pdf.pages)!=5:
        raise ValueError(f'Expected five intentionally laid-out sheets, got {len(pdf.pages)}')
    document=document or DocumentInfo()
    for i,page in enumerate(pdf.pages,1):
        writer.add_page(page)
        writer.add_outline_item(['Расчёт и график','Обвязка','Проверка режимов','Текст ПЗ','Автоматизация'][i-1],i-1)
    if r.get('repair_review'):
        from app.pz.fire_diaphragm_correction_report import correction_review_pdf
        writer.append(PdfReader(BytesIO(correction_review_pdf(r['repair_review'],document=document,framed=False))))
    writer.add_metadata({'/Title':'В2 - расчёт обвязки и задание на автоматизацию','/Author':'ЗАРЯ'})
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    output=BytesIO();writer.write(output)
    Path(path).write_bytes(frame_station_calculation(output.getvalue(), document,
        'Насосная В2. Расчёт и автоматика'))
    return str(path)
