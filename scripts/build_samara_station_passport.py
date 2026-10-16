"""Reproducible local station audit and draft manufacturer request; sends nothing."""
import json
from hashlib import sha256
from xml.sax.saxutils import escape

from app.calc.fire_station_documents import review_station_documents
from app.data.fire_station_documents import SOURCES, MANUAL_URL, PASSPORT_URL
from app.intake.project_builder import build_project
from app.pz.ios2_orchestrator import design_ios2
from scripts.build_samara_diaphragm_apertures import calculate_apertures
from scripts.build_samara_section_study import (
    ROOT, OUTPUT, load_basis, make_draft, make_request, make_fire_station)


def verify_sources():
    files = {
        'catalog': ROOT.parent.parent.parent/'Downloads/Каталог PFFS.pdf',
        'manual': ROOT/'tmp/pdfs/cnp/pffs-manual-20250527.pdf',
        'passport': ROOT/'tmp/pdfs/cnp/pffs-passport-20250530.pdf',
        'sp10_amendment1': ROOT.parent.parent.parent/'Downloads/sp-10.13130-izm.1.pdf',
    }
    for key, path in files.items():
        if sha256(path.read_bytes()).hexdigest() != SOURCES[key]['sha256']:
            raise ValueError(f'Source changed: {key}; review before rebuilding')


def render_station_review(path, r):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, PageBreak, Spacer
    pdfmetrics.registerFont(TTFont('StationAudit',str(ROOT/'app/assets/fonts/OpenGOSTtypeB-Regular.ttf')))
    body=ParagraphStyle('body',fontName='StationAudit',fontSize=11,leading=14,spaceAfter=8)
    heading=ParagraphStyle('heading',parent=body,fontSize=22,leading=25,spaceAfter=14)
    sub=ParagraphStyle('sub',parent=body,fontSize=14,leading=17,spaceBefore=8,spaceAfter=9)
    small=ParagraphStyle('small',parent=body,fontSize=9,leading=12)
    def p(t,style=body):return Paragraph(escape(str(t)),style)
    def n(v,d=3):return f'{v:.{d}f}'.replace('.',',')
    def table(rows,widths):
        t=Table([[p(c) for c in row] for row in rows],colWidths=[x*mm for x in widths],repeatRows=1)
        t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.35,colors.HexColor('#bec7ce')),
            ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eef2f5')),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
        return t
    e=r['evidence'];sc=r['screen']
    story=[p('В2 / проверка станции',heading),
        p('Самара, секция 3.2. Предварительный кандидат PFFS 2 CDM32-3 D. '
          '04.10.2026. Каталожная комплектация проверена; окончательный заказной код не подтверждён.'),
        table([('Параметр','Что подтверждено'),
            ('Насосы / присоединение','2 × CDM32-3; по 5,5 кВт; DN100. Каталог PFFS, PDF с.40.'),
            ('Рабочий / резервный','В расчёте 1 + 1. Расход резервного насоса не складывается с рабочим.'),
            ('Давление исполнения','Серия имеет варианты 16/25 бар. Конкретный вариант ещё не принят.'),
            ('Условия помещения','Стандартное исполнение: отапливаемое помещение, +5...+40 °C. Каталог, PDF с.7.'),
            ('Внутренние потери','Каталог, PDF с.11: обвязка не учтена в кривых. Гарантированной кривой станции нет.')],[52,118]),
        p('Состав одного комплектного узла',sub),
        table([('В составе станции','Количество'),
            *[(x['name'],f"{x['quantity']} {x['unit']}") for x in r['inventory']]],[137,33]),
        p('Это контроль состава, не отдельные закупочные позиции. При заказе комплектной станции '
          'её внутреннюю арматуру нельзя дублировать в общей спецификации. Типы и DN арматуры '
          'не назначены по одному DN100 присоединения. Жокей-модуль автоматически не добавлен.'),
        p('Размеры по буквам каталожного чертежа',sub),
        p('; '.join(f'{k}={v}' for k,v in e['dimensions_mm'].items())+' мм. '
          'Таблица: PDF с.40, расшифровка букв: PDF с.38. Это не проверка проходов и размещения в насосной.'),
        PageBreak(),p('Гидравлические границы',heading),
        p('Связь с текущим расчётом',sub),
        table([('Параметр','Значение / смысл'),
            ('Минимальная расчётная подача',n(r['required_q_m3h'])+' м³/ч; справочная характеристика ПК L06.'),
            ('Требуемая добавка станции',n(r['required_station_boost_m'])+' м при этой подаче.'),
            ('Одиночный CDM32-3',n(sc['duty_head_m'])+' м; без внутренней обвязки.'),
            ('Разность напоров',n(sc['dynamic_margin_m'])+' м. Только необходимая проверка одной точки!'),
            ('Подачи совместных сценариев',' - '.join(n(x) for x in r['flow_range_m3h'])+' м³/ч.'),
            ('На входной границе модели',' - '.join(n(x) for x in r['suction_range_m'])+' м. До неизвестных внутренних потерь на всасывании.'),
            ('Минимумы ПК','512/512 номинально и при двух смещениях шкалы; станция ещё не проверена в сборе.')],[68,102]),
        p('Разность '+n(sc['dynamic_margin_m'])+' м НЕ разрешает принять столько потерь обвязки. '
          'После получения её характеристики необходимо повторить совместный расчёт: изменятся расходы '
          'ПК, потери в сети и положение на кривой насоса. Нулевые потери станции не назначены.'),
        p('Статика - отдельная граница',sub),
        p('Номинальный напор насоса при Q=0: '+n(r['nominal_shutoff_head_m'],1)+' м. '
          'При учебном максимуме городского напора 35 м давление нижнего ПК: '
          +n(r['static_pressure_lowest_cabinet_mpa'],6)+' МПа. Для принятой высотной базы предел '
          'насосного напора составляет '+n(r['maximum_pump_shutoff_m'])+' м; до него остаётся '
          +n(r['static_headroom_m'])+' м.'),
        p('Этот остаток не является подтверждённым запасом на допуски и гидроудар. '
          'Нужен верхний гарантированный напор изготовителя. PN станции не отменяет предел 0,9 МПа '
          'для самостоятельного ВПВ. Диафрагма при Q=0 не снижает давление.'),
        p('Сохраняются ограничения исходного опыта',sub),
        p('16 этажей по 3 м; два представительных стояка; неповреждённое кольцо. '
          'ТУ на максимум давления, реальные ПК и допуски шайб, NPSH, отключения участков '
          'кольца и покрытие по планам не подтверждены. Сценарии - расчётная чувствительность, '
          'не доказательство нормативного покрытия здания.'),
        PageBreak(),p('Вопросы изготовителю',heading),
        p('Два противоречия, которые нельзя скрыть',sub),
        p('1. Автоматика. В РЭ PFFS, с.27 и 42, предусмотрена блокировка насосов по сухому '
          'ходу, по умолчанию включённая для обоих. Пункт 12.3 СП10 с изменением 1 '
          '(PDF с.25) запрещает такую защиту резервного пожарного насоса, включая '
          'автоматическое отключение по токовым и температурным перегрузкам. Требуется '
          'подтверждённое изготовителем исполнение и согласованный алгоритм; оборудование не перенастраивалось.'),
        p('2. Материал. Каталог, с.8: AISI 304; РЭ, с.11: нержавеющая сталь; '
          'с.12: углеродистая сталь с покрытием. Материал оставлен неопределённым до подтверждения.'),
        p('Черновик технического запроса / не отправлен',sub),
        p('Просим подтвердить исполнение PFFS на двух CDM32-3 для самостоятельного ВПВ '
          'жилой секции: 1 рабочий + 1 резервный. Минимальная точка станции: Q='
          +n(r['required_q_m3h'])+' м³/ч, добавка H='+n(r['required_station_boost_m'])+' м. '
          'Предварительный диапазон совместных расходов: '
          +' - '.join(n(x) for x in r['flow_range_m3h'])+' м³/ч; максимум напора насоса '
          'при Q=0 для принятой базы не более '+n(r['maximum_pump_shutoff_m'])+' м.'),
        *[p(f'{i}. {row["text"]}') for i,row in enumerate(r['requests'],1)],
        p('Файлы и проверяемые источники',sub),
        p('Пользовательские каталог PFFS и изменение 1 к СП10; официальный РЭ PFFS '
          'от 27.05.2025; краткий паспорт от 30.05.2025. Последний является общим бланком, '
          'а не паспортом конкретной собранной установки. SHA256 и страницы сохранены в JSON.',small),
        Paragraph(f'<link href="{MANUAL_URL}" color="#286592">Официальное руководство PFFS</link> · '
                  f'<link href="{PASSPORT_URL}" color="#286592">Краткий паспорт</link>',small),
        p('Локальное исследование, не комплект ИОС2 по ГОСТ Р21.619-2023 и не разрешение на монтаж. '
          'ПЗ, спецификация реального проекта, сайт и legacy не изменены. '
          'Полный заказной код и подтверждение подбора не созданы.',small)]
    def footer(c,doc):
        c.setFont('StationAudit',9)
        c.drawString(20*mm,12*mm,'ЗАРЯ / секция 3.2 / проверка PFFS / 04.10.2026')
        c.drawRightString(190*mm,12*mm,str(doc.page))
    SimpleDocTemplate(str(path),pagesize=A4,leftMargin=20*mm,rightMargin=20*mm,
        topMargin=17*mm,bottomMargin=22*mm,title='В2 - паспортная проверка станции PFFS').build(
            story,onFirstPage=footer,onLaterPages=footer)


def main():
    verify_sources()
    basis=load_basis();station=make_fire_station(basis)
    bundle=design_ios2(build_project(make_request(make_draft(basis))),
        output_dir=str(OUTPUT/'documents'),fire_station=station,render_documents=False)
    apertures=calculate_apertures(basis,bundle)
    review=review_station_documents(basis,bundle.fire_station_result,station,apertures)
    path=OUTPUT/'В2-станция-паспортная-проверка.pdf'
    (OUTPUT/'fire-station-passport-review.json').write_text(
        json.dumps(review,ensure_ascii=False,indent=2,allow_nan=False))
    render_station_review(path,review)
    print(json.dumps(dict(pdf=str(path),flow_range=review['flow_range_m3h'],
        required_boost=review['required_station_boost_m'],screen=review['screen'],
        factory_control_check=review['factory_control_check']),ensure_ascii=False))


if __name__=='__main__':main()
