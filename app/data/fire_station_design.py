"""Samara study input accepted by user: designer chooses preliminary pipework.

NOT CNP bill of materials or certified Kv. Each value below is a visible project
assumption/required hydraulic envelope. Actual products must meet it or trigger
a recalculation. Existing Samara A inputs are retained, not new pipe tables.
"""
from app.calc.fire_station_pipework import PipeworkElement, StationPipework
from app.data.pipe_catalog import steel_vgp_ordinary


# Updated local design after pipework inclusion, not an automatic universal rule.
# 18.5 mm on floors 13-15 failed 31/512; 19.5 alone left one graphical
# sensitivity failure at floor 12. Both groups are rechecked jointly below.
SAMARA_PIPEWORK_APERTURES_MM = {
    f: (13.5, 14., 15., 16.5, 19.5)[(f-1)//3] for f in range(1,16)
}


def samara_pipework():
    rows=[]
    for side,word in [('suction','Всасывание'),('discharge','Напор')]:
        for dn,length,A in [(100,1.,.0023),(65,.5,.011)]:
            rows.append(PipeworkElement(f'{side}-pipe-{dn}',f'{word}: труба DN{dn}',side,dn,1,
                'A_L',A,'L принята проектировщиком; A сохранено из учебной базы секции 3.2',
                length_m=length,inner_mm=steel_vgp_ordinary(dn).inner_mm))
        rows.append(PipeworkElement(f'{side}-valve-100',f'{word}: общая запорная арматура',
            side,100,1,'Kv',200.,'Требование к выбору: Kv не ниже 200 м³/ч; не паспорт PFFS'))
        rows.append(PipeworkElement(f'{side}-valve-65',f'{word}: арматура рабочей ветви',
            side,65,1,'Kv',100.,'Требование к выбору: Kv не ниже 100 м³/ч; не паспорт PFFS'))
        rows.append(PipeworkElement(f'{side}-fittings',f'{word}: сборка фасонных частей',
            side,65,1,'zeta',2.,'Суммарное ζ=2 принято для предварительной сборки; не норма СП',
            inner_mm=steel_vgp_ordinary(65).inner_mm))
    rows.append(PipeworkElement('discharge-check','Обратный клапан рабочей ветви','discharge',65,1,
        'Kv',50.,'Требуемая эквивалентная Kv не ниже 50 в диапазоне рабочих расходов; '
        'проверяется полная Δp(Q), включая открытие пружины; не паспорт конкретного клапана'))
    return StationPipework(tuple(rows),
        'Разрешение пользователя 04.10.2026: расчётная обвязка на усмотрение проектировщика. '
        'Один активный путь: два коллектора DN100 по 1 м, две ветви DN65 по 0,5 м. '
        'Трубы ВГП 114×4,5 / 75,5×4,0; A - учебные значения, не подтверждённая заводская геометрия. '
        'Проценты местных потерь поверх явных сопротивлений не добавляются.')


AUTOMATION_ASSIGNMENT = dict(
    status='project_requirement', manufacturer_confirmed=False, duty_pumps=1, reserve_pumps=1,
    reserve_in_flow_sum=False, reserve_installed=True, awaiting_manufacturer_response=False,
    reference='СП 10.13130.2020, п.12.3 с изменением 1; ГОСТ Р21.619-2023, пп.5.1.8, 5.1.14',
    requirements=(
        'Предусмотреть один рабочий и один установленный резервный пожарный насос одинаковой производительности.',
        'Резерв автоматически включается при невыходе рабочего на расчётный режим, его аварийном отключении или несрабатывании.',
        'Резервный насос не участвует в суммировании расчётной подачи. При его замещении рабочая характеристика сохраняется.',
        'Реализовать предусмотренные проектом автоматический, дистанционный и местный пуск; источники команд согласовать с разделом пожарной автоматики.',
        'Для резервного пожарного насоса не предусматривать автоматическую защиту и отключение по перегрузке по току, температуре и сухому ходу согласно п.12.3 с изменением 1.',
        'Передавать на диспетчеризацию состояния готовности, работы и аварии каждого насоса, режим управления, состояние электропитания и положения контролируемой арматуры.',
        'Датчики давления до и после насосов, критерий выхода на режим, уставки и временные задержки увязать с гидравликой и смежным разделом; численные уставки данным расчётом не назначаются.',
        'Алгоритмы остановки, электроснабжение, АВР, силовые защиты и контроль линий выполнить в профильных разделах по действующим требованиям; данное задание не является электрической схемой.',
    ),
    equipment_acceptance='При выборе шкафа обеспечить выполнение задания; соответствие конкретного изделия проверяется по документации. Переписка с изготовителем не является условием выпуска задания.',
)
