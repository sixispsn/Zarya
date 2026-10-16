"""Optional suction check, rebuilt against the current project at every output.

External loss values remain explicit engineering inputs. A matching graph is
not evidence of their accuracy or of the flow distribution in G.1.
"""
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from app.calc.pump_suction import NpshaInput, calculate_npsha
from app.calc.suction_losses import SuctionLoss, bind_suction_losses
from app.pz.water_station_review import connected_network, review_station
from app.schemas.pump_suction import ProjectSuctionInput

ROOT = Path(__file__).resolve().parents[2]
VERSION = 'project-suction-2'


class SuctionCheckError(ValueError):
    pass


def numeric_identity(value):
    """YAML 0 / 0.0 are the same input; do not round non-integral values."""
    if isinstance(value, dict):
        return {k: numeric_identity(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [numeric_identity(v) for v in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def digest(value):
    return sha256(json.dumps(numeric_identity(value), ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def dependency_stamp():
    # Conservative invalidation also covers catalogue revisions and changes
    # to calculated source results; no persistent cache of an old acceptance.
    files = [p for directory in ('app/calc', 'app/data', 'app/pz', 'app/intake', 'app/schemas')
             for p in (ROOT / directory).rglob('*') if p.suffix in ('.py', '.json')]
    return digest({str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest()
                   for p in sorted(files)})


def project_context(project, *, dependencies=None):
    report = review_station(project) or {}
    manifest = report.get('suction_paths') or {}
    network = connected_network(project)
    if not network or not manifest.get('complete') or not manifest.get('routes'):
        raise SuctionCheckError('Для текущей компоновки нет полного состава путей всасывания. '
                          'Поддерживаются общий ВУ и насосная В1 1+1.')
    labels = {node.id: node.title or node.id for node in network.nodes}
    routes = []
    for route in manifest['routes']:
        nodes = route['nodes']
        components = {f'node:{n}': labels[n] for n in nodes[1:-1]}
        components.update({f'link:{a}->{b}': f'{labels[a]} → {labels[b]}'
                           for a, b in zip(nodes, nodes[1:])})
        routes.append({**route, 'id': digest(nodes),
                       'label': ' → '.join(labels[n] for n in nodes),
                       'components': components})
    # Full current inputs, geometry, selected products and calculated results
    # are included, not just the list of component IDs.
    # Exclude the check itself and document metadata. Neither a YAML roundtrip
    # nor pagination changes hydraulics.
    engineering = asdict(project)
    for key in ('suction_check', 'document', 'digital_passport'):
        engineering.pop(key, None)
    fingerprint = digest(dict(version=VERSION, project=engineering,
        network=asdict(network), closed=manifest['closed_components'],
        dependencies=dependencies if dependencies is not None else dependency_stamp()))
    return dict(fingerprint=fingerprint, routes=routes, notes=manifest['notes'],
        pump_elevation_m=project.source.station_suction_elevation_m,
        catalogue_notes=[
            'Водомер: S и расчётные потери типоразмера не являются паспортной кривой изделия. '
            'Предел ДЕКАСТ Δp ≤ 0,1 МПа при Qmax не задаёт точную потерю.',
            'Размеры фильтра и подводок не определяют сопротивление. Нужны готовые потери '
            'с основанием при указанном расходе и температуре; состояние фильтра укажите в основании.',
            'Прежние потери при Qрасч не переносятся в максимальный режим. '
            'Готовые суммы с местными сопротивлениями учитываются один раз.'])


def evaluate(context, payload):
    if payload.fingerprint != context['fingerprint']:
        raise SuctionCheckError('Проект или каталог изменились. Откройте проверку заново.')
    route = next((r for r in context['routes'] if r['id'] == payload.route_id), None)
    if route is None:
        raise SuctionCheckError('Выбранный путь отсутствует в текущем графе.')
    data = payload.balance.model_dump(exclude={'suction_path'})
    axis = context.get('pump_elevation_m')
    if axis is not None and data['pump_elevation_m'] is not None and axis != data['pump_elevation_m']:
        raise SuctionCheckError('Ось всасывания не совпадает с явно заданной отметкой насосной в проекте.')
    if data['suction_losses_m'] is not None or payload.balance.suction_path is not None:
        raise SuctionCheckError('Состав пути задаётся текущим проектом; Hf получается только из строк потерь.')
    trace = bind_suction_losses(route['required_components'],
        [SuctionLoss(**{**r.model_dump(), 'covers': tuple(r.covers)}) for r in payload.losses],
        max_flow_m3h=data['max_flow_m3h'], temperature_c=data['temperature_c'],
        path_basis=payload.path_basis)
    data['suction_losses_m'] = trace.total_loss_m
    return dict(balance=asdict(calculate_npsha(NpshaInput(**data))), losses=asdict(trace))


NOTICE = ('Проверка только одного явно заданного режима и пути. Не подтверждает '
          'распределение расходов между вводами, остальные режимы или разрешение на пуск. '
          'Подбор насоса и общая оценка станции автоматически не изменяются. '
          'Достоверность внешних потерь и NPSHr и их применимость к изделию '
          'не подтверждаются самим вычислением.')

INPUT_LABELS = {
    'pressure_kind': 'Вид давления', 'pressure_bar': 'Давление исходного сечения, бар',
    'atmospheric_pressure_bar': 'Атмосферное давление, бар',
    'source_elevation_m': 'Отметка исходного сечения, м',
    'pump_elevation_m': 'Отметка оси всасывания, м',
    'max_flow_m3h': 'Максимальная рабочая подача одного насоса, м³/ч',
    'temperature_c': 'Температура воды, °C', 'vapor_head_m': 'Hv при этой температуре, м',
    'npshr_m': 'NPSHr при той же подаче, м', 'safety_margin_m': 'Запас Hs, м',
    'suction_losses_m': 'Полные потери пути в максимальном режиме, м',
    'basis': 'Основания исходных данных', 'npshr_basis': 'Основание NPSHr',
}


def review_suction(project):
    if project.suction_check is None:
        return None
    base = dict(result=None, notice=NOTICE)
    try:
        payload = ProjectSuctionInput.model_validate(project.suction_check)
        context = project_context(project)
        if payload.fingerprint != context['fingerprint']:
            return dict(base, status='stale', note='Проверка устарела: проект, методика или каталог '
                        'изменились. Требуется повторное подтверждение исходных и потерь.')
        result = evaluate(context, payload)
        route = next(r for r in context['routes'] if r['id'] == payload.route_id)
        return dict(base, status='current', note='Пересчитано по сохранённым исходным.',
                    result=result, inputs=payload.model_dump(), route=route,
                    input_rows=[(label, getattr(payload.balance, key)) for key, label in INPUT_LABELS.items()
                                if key not in ('basis', 'npshr_basis', 'suction_losses_m', 'pressure_kind')
                                and (key != 'atmospheric_pressure_bar' or payload.balance.pressure_kind == 'gauge')],
                    missing=[INPUT_LABELS.get(key, key) for key in result['balance']['missing']])
    except ValueError as exc:
        return dict(base, status='invalid', note='Проверка не подтверждена: ' + str(exc))
