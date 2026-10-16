"""Graphical aperture study: no production selection or specification mutation."""
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from xml.sax.saxutils import escape

from app.calc.fire_diaphragm_graph import read_aperture, read_pressure_drop, neighbouring_apertures
from app.calc.fire_hydraulics import MPA_TO_M
from app.calc.fire_nomogram_flow import check_nomogram_operating_point
from app.calc.fire_pressure_flow import handbook_characteristic
from app.data.fire_diaphragm_nomogram import APOGEY_SOURCE, SOURCE_SHA256, IMAGE_XREF, IMAGE_SIZE
from app.intake.project_builder import build_project
from app.pz.ios2_orchestrator import design_ios2
from scripts.build_samara_diaphragm_review import calculate_diaphragm_review
from scripts.build_samara_fire_flow_review import floor_network
from scripts.build_samara_section_study import ROOT,OUTPUT,load_basis,make_draft,make_request,make_fire_station


def calculate_apertures(basis,bundle):
    reference=calculate_diaphragm_review(basis,bundle)
    groups=[]
    for group in reference['variants'][0]['groups']:
        point=group['nomogram_inputs']
        reading=read_aperture(valve_dn=point['valve_dn'],flow_lps=point['flow_lps'],
                              pressure_drop_mpa=point['pressure_drop_mpa'])
        neighbours=neighbouring_apertures(reading,APOGEY_SOURCE['apertures_mm'])
        nearest=min(neighbours,key=lambda d:abs(d-reading.approximate_aperture_mm))
        next_size=next(d for d in APOGEY_SOURCE['apertures_mm'] if d>max(neighbours))
        groups.append(dict(floors=group['floors'],reading=asdict(reading),
            neighbouring_sizes_mm=neighbours,nearest_mm=nearest,upper_mm=max(neighbours),
            next_size_mm=next_size))
    base=bundle.fire_station_result.network
    chars=[handbook_characteristic(c,hose_material='rubber_lined',nozzle_kind='non_shutoff') for c in base.cabinets]
    source=make_fire_station(basis).supplies[0]
    resistance=sum(p.A*p.effective_length_m for p in source.segments)
    floors=basis['study_assumptions']['residential_floors']
    height=basis['study_assumptions']['floor_to_floor_m']
    result=dict(method='L06 joint solve against raster nomogram, B.2.1 amendment 1',
        release_ready=False,selection_confirmed=False,selected_product=None,
        legacy_modified=False,normative_coverage_verified=False,
        source=reference['normative_sources'],product_source=APOGEY_SOURCE,
        pump=reference['pump'],static_by_floor_mpa=reference['nominal_static_by_floor_mpa'],
        input_basis_sha256=sha256(json.dumps(basis,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
        groups=groups,variants=[],reference_pressure_min_mpa=reference['required_pressure_mpa'],
        source_boundary_notes='30m guaranteed; 35m study maximum, not confirmed utility limit',
        graphic_accuracy_not_guaranteed=True,
        sensitivity_notes='Explicit +/-2 native pixels on aperture scale only; not a full uncertainty or manufacturing tolerance')
    for name,key,offset in [('nearest','nearest_mm',0),('upper','upper_mm',0),
                            ('upper_axis_minus_2','upper_mm',-2),('upper_axis_plus_2','upper_mm',2),
                            ('next_size','next_size_mm',0),('next_size_axis_minus_2','next_size_mm',-2),
                            ('next_size_axis_plus_2','next_size_mm',2)]:
        layout={f:g[key] for g in groups for f in g['floors']}
        scenarios=[]
        for a in range(1,floors+1):
            for b in range(1,floors+1):
                levels=(a,b)
                net=floor_network(base,levels,height)
                apertures={c.cabinet_id:layout[f] for c,f in zip(chars,levels) if f in layout}
                for boundary,hs,r in [
                    ('one_supply_guaranteed',reference['source_guaranteed_m'],resistance),
                    ('maximum_head_no_supply_loss_bound',reference['source_maximum_m'],0)]:
                    out=check_nomogram_operating_point(net,chars,reference['pump']['curve'],
                        suction_static_head_m=hs,supply_resistance=r,apertures_mm=apertures,axis_offset_px=offset)
                    scenarios.append(dict(floors=list(levels),boundary=boundary,
                        apertures_mm=apertures,result=asdict(out)))
        rows=[c for s in scenarios if s['result']['operating'] for c in s['result']['operating']['cabinets']]
        complete=all(s['result']['operating'] is not None for s in scenarios)
        summary=dict(Counter(s['result']['status'] for s in scenarios))
        result['variants'].append(dict(name=name,apertures_by_floor_mm=layout,axis_offset_px=offset,
            scenario_count=len(scenarios),summary=summary,complete_solution=complete,
            p_range_mpa=[min(c['outlet_head_m']/MPA_TO_M for c in rows),max(c['outlet_head_m']/MPA_TO_M for c in rows)],
            meets_scenario_minima=complete and summary=={'meets_minimum':len(scenarios)},
            below_dynamic_limit=complete and max(c['outlet_head_m']/MPA_TO_M for c in rows)<=.45,
            scenarios=scenarios,selection_confirmed=False))
    # Audit why one-point R is not silently reused as the whole printed relation.
    p1=read_pressure_drop(valve_dn=50,flow_lps=2.6,aperture_mm=16)
    p2=read_pressure_drop(valve_dn=50,flow_lps=3.2,aperture_mm=16)
    result['quadratic_audit']=dict(aperture_mm=16,q1=2.6,q2=3.2,p1_mpa=p1,p2_nomogram_mpa=p2,
        p2_quadratic_mpa=p1*(3.2/2.6)**2,not_a_legacy_error=True)
    return result


def render_apertures(path,review,nomogram_image):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Table,TableStyle,PageBreak,Spacer,Flowable
    pdfmetrics.registerFont(TTFont('DiaGraph',str(ROOT/'app/assets/fonts/OpenGOSTtypeB-Regular.ttf')))
    body=ParagraphStyle('body',fontName='DiaGraph',fontSize=11,leading=14,spaceAfter=8)
    heading=ParagraphStyle('heading',parent=body,fontSize=21,leading=24,spaceAfter=14)
    sub=ParagraphStyle('sub',parent=body,fontSize=14,leading=17,spaceBefore=7)
    def p(x,style=body):return Paragraph(escape(str(x)),style)
    def n(v,k=3):return f'{v:.{k}f}'.replace('.',',')
    def table(rows,widths):
        t=Table([[p(c) for c in row] for row in rows],colWidths=[w*mm for w in widths],repeatRows=1)
        t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.35,colors.HexColor('#c1cad1')),
            ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eef2f6')),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
        return t
    a,b,c,d,e,f,g=review['variants']
    story=[p('В2 / размеры отверстий',heading),
        p('Самара, секция 3.2. CNP CDM32-3, ПК DN50. Предварительный вариант '
          'по номограмме СП10; не утверждённая спецификация оборудования.'),
        table([('Этажи','Чтение рисунка, мм ≈','Верхний соседний размер, мм','Следующий размер, мм'),
            *[(f'{g["floors"][0]}-{g["floors"][-1]}',n(g['reading']['approximate_aperture_mm'],1),
                n(g['upper_mm'],1),n(g['next_size_mm'],1)) for g in review['groups']]], [23,47,50,50]),
        Spacer(1,6*mm),p('На 16-м этаже в этом опыте местная диафрагма не добавляется. '
          'Цифры в последнем столбце - отверстия шайб, а не DN пожарных клапанов.'),
        p('Проверка совместной работы',sub),
        table([('Набор размеров','Минимумы ПК','p у ПК, МПа'),
            ('Округление к ближайшему',f'{a["summary"].get("meets_minimum",0)}/512',
             ' - '.join(n(x,5) for x in a['p_range_mpa'])),
            ('Верхний соседний размер',f'{b["summary"].get("meets_minimum",0)}/512',
             ' - '.join(n(x,5) for x in b['p_range_mpa'])),
            ('Следующий размер',f'{e["summary"].get("meets_minimum",0)}/512',
             ' - '.join(n(x,5) for x in e['p_range_mpa']))],[76,33,61]),
        Spacer(1,6*mm),
        p('Простое округление не прошло. Набор 13 / 13,5 / 14,5 / 15,5 / 18 мм '
          'проходит номинальный расчёт, но чувствителен к чтению шкалы. Следующий '
          'каталожный набор 13,5 / 14 / 15 / 16 / 18,5 мм проходит также проверку ±2 пикселя. '
          'Это проверяемый кандидат, не универсальное правило округления или оптимальный подбор.'),
        p('В расчёте неизвестны расходы каждого ПК. По их сумме берётся точка каталожной '
          'кривой насоса; решается кольцо, а потеря на каждом отверстии читается по номограмме '
          'при текущем расходе. Неизвестные потери готовой PFFS этим не подтверждены.'),
        p('Границы: 16 этажей по 3 м, два разных представительных стояка; 256 пар этажей × '
          '2 границы источника. Гарантированный напор 30 м, учебный максимум 35 м. '
          'Разновысотные пары - чувствительность модели, не подтверждение зон тушения.'),
        p('Каталожный ряд',sub),
        p('В техническом описании ООО «Апогей» есть DN50/DN65, отверстия 12-25 мм с шагом '
          '0,5 мм, латунь ЛС59-1. Использован только размерный ряд. Старый порог 0,40 МПа '
          'и ссылка на СНиП из этого документа НЕ заменяют действующий п.7.5 СП10.'),
        PageBreak(),p('Номограмма / проверяемое чтение',heading),
        p('Исходный рисунок из предоставленного СП10, приложение Б, PDF с.35. Цветные '
          'прямые соединяют Δp и q исходных точек пяти групп. Шкала отверстия для DN50 - слева.' )]
    palette=['#bd3c3c','#bd711d','#288059','#256bb6','#7b50a0']
    class Graph(Flowable):
        def __init__(self):
            super().__init__();self.width=135*mm;self.height=self.width*524/422
        def draw(self):
            c=self.canv;s=self.width/422
            c.drawImage(str(nomogram_image),0,0,width=self.width,height=self.height)
            for group,color in zip(review['groups'],palette):
                r=group['reading'];x1,y1=r['pressure_point_px'];x2,y2=r['flow_point_px'];x,y=r['aperture_point_px']
                c.setStrokeColor(colors.HexColor(color));c.setLineWidth(.8)
                c.line(x1*s,self.height-y1*s,x2*s,self.height-y2*s)
                c.circle(x*s,self.height-y*s,2,stroke=1,fill=0)
    story.extend([Graph(),Spacer(1,4*mm),
        p('Цвета по порядку сверху вниз: 1-3, 4-6, 7-9, 10-12, 13-15 этажи. '
          'Пункт Б.2.1 изменения 1: шкала P означает 100 × Δp (МПа), а не давление после шайбы.'),
        p('Рисунок растровый: 422 × 524 пикселя. Считаны деления, учтён наклон осей. '
          'Используется построение прямой по Б.2.2-4 внутри шкал, без экстраполяции. '
          'DN65 и диаметры вне проверенного интервала 12-25 мм автоматическому чтению не доверены.'),
        PageBreak(),p('Точность и условия применения',heading),
        p('Чувствительность к чтению рисунка',sub),
        table([('Набор / сдвиг средней шкалы','Минимумы ПК','Минимальное p, МПа'),
            ('Верхний соседний / -2 пикселя',f'{c["summary"].get("meets_minimum",0)}/512',n(c['p_range_mpa'][0],6)),
            *[(f'Следующий / {v["axis_offset_px"]:+g} пикселя',f'{v["summary"].get("meets_minimum",0)}/512',
                n(v['p_range_mpa'][0],6)) for v in (f,g)]],[70,40,60]),
        Spacer(1,5*mm),
        p('±2 исходных пикселя - заданная проверка чувствительности графического чтения, '
          'НЕ нормативный допуск, не точность изготовителя и не полная оценка погрешности '
          'всех осей. Сдвиг общий для всех диафрагм, не независимые ошибки каждого изделия. '
          'Все 3584 сценария и остатки баланса сохранены.'),
        p('Почему прежнее R не перенесено молча',sub),
        p('Для отверстия 16 мм номограмма даёт при 2,6 л/с около '
          +n(review['quadratic_audit']['p1_mpa'],4)+' МПа, при 3,2 л/с - '
          +n(review['quadratic_audit']['p2_nomogram_mpa'],4)+' МПа. Квадратичное продолжение '
          'из первой точки дало бы '+n(review['quadratic_audit']['p2_quadratic_mpa'],4)+' МПа. '
          'Поэтому прежний опыт с целевым постоянным R не является проверкой реальных отверстий. '
          'Это ограничение исследовательской модели L06, не новая ошибка legacy.'),
        p('Что остаётся незакрытым',sub),
        p('1. Чертёж/паспорт конкретной шайбы: допуск отверстия, толщина и кромка, '
          'посадка между клапаном и соединительной головкой, допустимое давление и '
          'совместимость материалов. В найденном описании есть ограничения контакта латуни '
          'с железом, алюминием и цинком; нельзя обещать совместимость любого ПК.'),
        p('2. Реальные характеристики ПК и станции PFFS, внутренние потери, допуски '
          'насосной кривой, NPSH, резервирование, управление и аварийные режимы.'),
        p('3. Плановая проверка совместного тушения и отключений кольца. При закрытых '
          'ПК диафрагмы не ограничивают статику. Номинальное давление нижнего ПК остаётся '
          +n(max(review['static_by_floor_mpa'].values()),6)+' МПа; допуски и гидроудар не подтверждены.'),
        p('Источники и статус',sub),
        p('СП10.13130.2020: PDF с.35; изменение 1: PDF с.33, Б.2.1. '
          'Каталог CNP CDM/CDMF: PDF с.33; PFFS: PDF с.40. '
          'Техническое описание ООО «Апогей», 1 лист, опубликовано на dn.ru; ссылка и '
          'SHA256 сохранены в JSON. Найденный размерный ряд не подтверждает наличие на складе.'),
        p('Локальное предварительное исследование, не комплект ИОС2 по ГОСТ Р21.619-2023. '
          'Отверстия не записаны автоматически в проектную спецификацию. '
          'Сайт, исходный насос, рабочий и архивный legacy не изменены.')])
    def footer(c,doc):
        c.setFont('DiaGraph',9);c.drawString(20*mm,12*mm,'ЗАРЯ / секция 3.2 / отверстия диафрагм / 04.10.2026')
        c.drawRightString(190*mm,12*mm,str(doc.page))
    SimpleDocTemplate(str(path),pagesize=A4,leftMargin=20*mm,rightMargin=20*mm,
        topMargin=17*mm,bottomMargin=22*mm,title='В2 - предварительная проверка отверстий диафрагм').build(
            story,onFirstPage=footer,onLaterPages=footer)


def extract_nomogram():
    import pymupdf
    source=Path('/Users/antonpashkevich/Downloads/SP10.13130.2020.pdf')
    if sha256(source.read_bytes()).hexdigest()!=SOURCE_SHA256: raise ValueError('Nomogram source changed')
    doc=pymupdf.open(source);pix=pymupdf.Pixmap(doc,IMAGE_XREF)
    if (pix.width,pix.height)!=IMAGE_SIZE:raise ValueError('Raster calibration mismatch')
    target=ROOT/'tmp/pdfs/sp10-nomogram-native.png';target.parent.mkdir(parents=True,exist_ok=True)
    pix.save(str(target));return target


def main():
    basis=load_basis();bundle=design_ios2(build_project(make_request(make_draft(basis))),
        output_dir=str(OUTPUT/'documents'),fire_station=make_fire_station(basis),render_documents=False)
    result=calculate_apertures(basis,bundle)
    OUTPUT.mkdir(parents=True,exist_ok=True)
    (OUTPUT/'fire-diaphragm-apertures.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    path=OUTPUT/'В2-диафрагмы-подбор-отверстий.pdf'
    render_apertures(path,result,extract_nomogram())
    print(json.dumps(dict(pdf=str(path),groups=result['groups'],variants=[{k:v for k,v in r.items() if k!='scenarios'}
        for r in result['variants']]),ensure_ascii=False))


if __name__=='__main__':main()
