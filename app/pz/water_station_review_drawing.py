"""Design review sheets, from the same report as Studio and the explanatory note."""
from app.pz.metering_modes_drawing import _schedule
from app.pz.water_station_review import review_station


def station_review_contents(project):
    r = review_station(project)
    if not r:
        return []
    pages = _schedule('В1. Увязка ВУ и насосной', (27,119,170,407),
        ('Проверка', 'Данные', 'Граница подтверждения'),
        [(x['id'], (x['title'], x['value'], x['note'])) for x in r['hydraulic']],
        kind='station-hydraulics', intro='Гидравлическая полнота: не подтверждена. Существующий подбор не изменён.',
        footer=('ГОСТ Р 21.619-2023, 5.2.2.5, приложение В; СП 30, 13.11, 13.14, 13.16.',
                'Без размеров и сопротивлений обвязки нет окончательного расчёта её потерь.'))
    labels = {'checked':'проверено по связям', 'blocked':'не обеспечено', 'needs_data':'не подтверждено'}
    rows = []
    for s in r['scenarios']:
        m = s['removal']
        rows.append((s['target'], (s['title'], ', '.join(s['close_tags']),
            s['active'] + (': путь есть; работа при ремонте не разрешена этой проверкой' if s['delivery_path_exists'] else ': путь не найден'),
            'Отсечение: '+labels[m['isolation']]+'. Сброс: '+labels[m['pressure_relief']]+
            '. Слив: '+labels[m['drainage']]+'. Воздух: '+labels[m['air_admission']]+'. '+
            s['body_service']+' '+s['pocket_note'])))
    if r['service']:
        rows += [('factory-service',('Штатные точки','В составе насоса','Не отдельная закупка',
            r['service']['summary']+' '+r['service']['source'])),
            ('maintenance-scope',('Граница проверки','По РЭ PBS','Не разрешение работ',
            r['service']['maintenance']+' '+r['service']['limitation']))]
    for a in r['access_requirements']:
        rows.append((a['id'], (a['mark']+'* · '+a['location'], 'Требует решения',
            'Не установленное оборудование', a['requirement']+' '+a['scope'])))
    if not rows:
        rows = [('unsupported', ('Не поддержано','-','-',r['unsupported_note']))]
    pages += _schedule('В1. Обслуживание насосных ветвей', (27,90,129,205,407),
        ('Режим','Отсечки','Другой агрегат','Проверка отключённой ветви'),rows,
        kind='station-maintenance', intro='НЗ1/НЗ2 - отсечки Н1; НЗ3/НЗ4 - отсечки Н2. Метки не являются позициями СО.',
        footer=('Обратный клапан и остановленный насос не являются ремонтными отсечками.',
                'Общий спуск за отсечками не опорожняет насос и полость за обратным клапаном.',
                'Путь через другой насос не подтверждает Q/H и допустимость ремонта на работающей НУ.'))
    if r['automation']:
        pages += _schedule('В1. Задание по управлению насосами', (27,91,313,407),
            ('Событие','Требуемая реакция','Основание'),
            [(str(i),(row['title'],row['action'],row['basis'])) for i,row in enumerate(r['automation'])],
            kind='station-automation', intro='Проектные требования для 1 рабочего + 1 резервного. Не готовая программа ПЛК.',
            footer=('Порог, гистерезис, выдержки времени и сценарий возврата без исходных данных не назначены.',
                    'Число 5 м в СП 30, 13.14 относится к наружной сети, не к уставке защиты насоса.'))
    return pages
