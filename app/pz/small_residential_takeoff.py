"""Explicit quantity proposal for the reviewed eight-apartment house.

No drafting coordinates are read. Fitting identities come from the existing
installation assemblies, not another independently invented symbol catalogue.
This adapter is bounded; NetworkTakeoff itself has no floor/apartment limit.
"""
from dataclasses import dataclass
from math import hypot, isfinite

from app.pz.network_takeoff import (
    NetworkPoint, NetworkTakeoff, QuantityBasis, QuantityComponent, QuantityRoute,
)
from app.pz.small_residential_calculation import ResidentialCalculation
from app.pz.small_residential_preview import ResidentialPreview


@dataclass(frozen=True)
class ApartmentRouteProposal:
    # Distance along the common branch from its capped initial end.
    fixture_chainages_m: tuple[float, ...]
    collector_length_m: float
    fixture_connections_m: tuple[float, ...]
    join_height_m: float
    source: str

    def validate(self, fixture_count: int) -> None:
        values = (*self.fixture_chainages_m, self.collector_length_m,
                  *self.fixture_connections_m, self.join_height_m)
        if (not self.source.strip() or len(self.fixture_chainages_m) != fixture_count
                or len(self.fixture_connections_m) != fixture_count
                or any(isinstance(x, bool) or not isfinite(x) or x <= 0 for x in values)
                or any(a >= b for a, b in zip(self.fixture_chainages_m, self.fixture_chainages_m[1:]))
                or self.fixture_chainages_m[-1] >= self.collector_length_m):
            raise ValueError("explicit ordered apartment route lengths are required")


EDUCATIONAL_APARTMENT_ROUTE = ApartmentRouteProposal(
    (.3, 1.8, 2.8, 3.4), 4., (.45, .25, .45, .20), .20,
    "Учебное предложение v1, не обмер JPG: общая ветвь 4 м; присоединения мойки, "
    "ванны, умывальника, унитаза 0,45 / 0,25 / 0,45 / 0,20 м; ось врезки +0,20 м от пола.",
)

_FITTING_NAMES = {
    "elbow_45": "Отвод 45°", "wye_45": "Косой тройник 45°",
    "wye_45_cleanout": "Косой тройник 45°", "wye_45_through": "Косой тройник 45°",
    "cap": "Заглушка прочистки", "trap": "Гидрозатвор прибора",
    "diameter_transition": "Переход перед врезкой унитаза",
}
_FIXTURE_NAMES = {"sink": "Мойка", "bath": "Ванна", "washbasin": "Умывальник", "toilet": "Унитаз"}


def build_residential_takeoff(
    model: ResidentialPreview, calc: ResidentialCalculation, *,
    apartment_route: ApartmentRouteProposal,
    outlet_lengths_m: tuple[float | None, float | None], outlet_source: str,
) -> NetworkTakeoff:
    """Count all apartments and shared networks, independently of projection.

    Straight-axis envelopes include fitting bodies; subtracting socket lengths,
    ordering stock pipe and support/insulation selection are explicitly pending.
    Outlet lengths stop at the outside face of the wall, NOT at a manhole.
    """
    model.validate()
    calc.validate(model)
    if model.roof is None or len(outlet_lengths_m) != 2 or not outlet_source.strip():
        raise ValueError("roof and explicit independent outlet boundaries are required")
    points, routes, components = [], [], []

    def point(pid, system, role="junction"):
        points.append(NetworkPoint(pid, system, role))
        return pid

    def route(rid, start, end, pipe, length, role, basis, mode="drain"):
        routes.append(QuantityRoute(rid, start, end, pipe, length, role, basis, mode))

    def component(cid, pid, kind, name, size, basis, source_id=None, family=""):
        components.append(QuantityComponent(cid, pid, kind, name, size, 1, basis, source_id or cid, family))

    def pipe_for_dn(dn):
        if dn not in {50, 100}:
            raise ValueError("quantity adapter has no selected pipe for this DN")
        return model.branch_pipe if dn == 50 else model.stack_pipe

    apt_basis = QuantityBasis("proposed", apartment_route.source)
    joins = {}
    for apt in model.apartments:
        f = apt.assembly
        apartment_route.validate(len(f.fixtures))
        if tuple(x.kind for x in f.fixtures) != ("sink", "bath", "washbasin", "toilet"):
            raise ValueError("route proposal is not applicable to this fixture layout")
        if any(x.quantity != 1 for x in f.fixtures):
            raise ValueError("grouped fixture needs its own physical branch geometry")
        prefix = apt.apartment_id
        cap = point(f"{prefix}:cleanout", "K1", "service")
        join = point(f"{prefix}:stack_join", "K1")
        joins[(apt.lane, apt.floor_number)] = join
        junctions = [point(f"{prefix}:j{n}", "K1") for n in range(4)]
        chainages = (0., *apartment_route.fixture_chainages_m, apartment_route.collector_length_m)
        branch_points = (cap, *junctions, join)
        for n, (start, end, a, b) in enumerate(zip(branch_points, branch_points[1:], chainages, chainages[1:])):
            dn = 50 if n < 4 else 100
            # Profiles are horizontal projections; count the sloped axis once.
            route(f"{prefix}:branch-{n}", start, end, pipe_for_dn(dn), hypot(b-a, (b-a)*f.slope(dn)),
                  "apartment_collector", apt_basis, "service" if n == 0 else "drain")
        for n, fixture in enumerate(f.fixtures):
            source = point(f"{prefix}:{fixture.fixture_id}", "K1", "source")
            route(f"{prefix}:connection-{n}", source, junctions[n], pipe_for_dn(fixture.dn_mm),
                  apartment_route.fixture_connections_m[n], "fixture_connection", apt_basis)
            component(f"{prefix}:fixture-{n}", source, "fixture", _FIXTURE_NAMES[fixture.kind],
                      f"DN{fixture.dn_mm}", apt_basis, f"{prefix}:{fixture.fixture_id}")
        for fitting in f.fittings:
            if fitting.kind not in _FITTING_NAMES:
                raise ValueError(f"unmapped fitting: {fitting.kind}")
            pid = cap if fitting.kind == "cap" else join
            if fitting.kind == "diameter_transition":
                pid = junctions[-1]
            for n, fixture in enumerate(f.fixtures):
                if fitting.fitting_id.startswith(fixture.fixture_id + "_"):
                    pid = junctions[n]
            size = "DN50/100" if fitting.kind == "diameter_transition" else f"DN{fitting.dn_mm}"
            # Geometry of every fitting is inherited, not reconstructed from text.
            component(f"{prefix}:{fitting.fitting_id}", pid, fitting.kind,
                      _FITTING_NAMES[fitting.kind], size, apt_basis, f"{f.assembly_id}:{fitting.fitting_id}",
                      family="" if fitting.kind == "trap" else "PP HT")
        component(f"{prefix}:revision", join, "revision", "Ревизия стояка", "DN100", apt_basis,
                  f"section:{prefix}:riser-revision", family="PP HT")

    for system, nodes, pipe, profile, chainages, outlet_invert, outlet_length in (
        ("K1", model.lower_nodes, model.stack_pipe, calc.basement.k1, calc.basement.junction_chainages_m,
         model.basement.proposed_invert_m, outlet_lengths_m[0]),
        ("K2", model.roof.lower_nodes, calc.rain_pipe, calc.rain_profile, calc.rain_chainages_m,
         calc.provisional_k2_outlet_m, outlet_lengths_m[1]),
    ):
        assert profile.length_m is not None and profile.slope is not None and profile.start_invert_m is not None
        basis = QuantityBasis("proposed", (calc.basement.source if system == "K1" else
                              "Учебный профиль К2: 6 м, i=0,015; не обмер плана подвала.") +
                              " Длины по осям до теоретических пересечений; габариты фасонины не вычтены.")
        family = "PP HT" if system == "K1" else "SML"
        def axis(station):
            return profile.start_invert_m-station*profile.slope + pipe.inner_diameter_mm/2000

        cap = point(f"{system}:main-cap", system, "service")
        bases = [point(f"{system}:base-{i}", system) for i in range(len(nodes))]
        top = point(f"{system}:drop-top", system)
        bottom = point(f"{system}:drop-bottom", system)
        outlet = point(f"{system}:outlet", system, "outlet")
        for i, (a, b, start, end) in enumerate(zip((0., *chainages), (*chainages, profile.length_m),
                                                  (cap, *bases), (*bases, top))):
            route(f"{system}:main-{i}", start, end, pipe, hypot(b-a, axis(b)-axis(a)), "basement_collector",
                  basis, "service" if i == 0 else "drain")
        drop = profile.end_invert_m - outlet_invert
        route(f"{system}:drop", top, bottom, pipe, drop, "outlet_drop", basis)
        route(f"{system}:outlet-route", bottom, outlet, pipe, outlet_length, "building_outlet",
              QuantityBasis("proposed", outlet_source))
        for i in range(4):
            component(f"{system}:drop-elbow-{i}", top if i < 2 else bottom, "elbow_45", "Отвод 45°", "DN100",
                      basis, f"section:{system}:drop-{'upper' if i < 2 else 'lower'}-elbow-{i % 2}", family=family)
        component(f"{system}:drop-revision", bottom, "revision", "Ревизия опуска", "DN100", basis, family=family)
        component(f"{system}:wall-sleeve", outlet, "sleeve", "Гильза выпуска", "Размер по узлу проходки", basis)
        for lane, node in enumerate(nodes):
            if bool(node.service_path) != (lane == 0):
                raise ValueError("only the initial free end may have a capped cleanout")
            for fitting in node.fittings:
                component(f"{system}:base-{lane}:{fitting.fitting_id}",
                          cap if fitting.kind == "cap" else bases[lane], fitting.kind,
                          _FITTING_NAMES[fitting.kind], f"DN{fitting.dn_mm}", basis,
                          f"{node.assembly_id}:{fitting.fitting_id}", family=family)
            if system == "K1":
                apartments = sorted((a for a in model.apartments if a.lane == lane), key=lambda a: a.floor_number)
                previous, previous_z = bases[lane], axis(chainages[lane])
                for apt in apartments:
                    join = joins[(lane, apt.floor_number)]
                    z = apt.assembly.floor_elevation_m + apartment_route.join_height_m
                    route(f"K1:stack-{lane}:floor-{apt.floor_number}", join, previous, pipe, z-previous_z,
                          "riser", QuantityBasis("proposed", "Отметки этажей пользователя + высота врезки из "
                                                 "учебного предложения; низ по профилю коллектора."))
                    previous, previous_z = join, z
                vent = point(f"K1:vent-{lane}", "K1", "vent")
                route(f"K1:vent-route-{lane}", vent, previous, pipe,
                      model.roof.elevation_m+model.roof.vent_height_m-previous_z, "ventilation", basis, "vent")
            else:
                funnel = point(f"K2:funnel-{lane}", "K2", "source")
                route(f"K2:stack-{lane}", funnel, bases[lane], pipe, model.roof.elevation_m-axis(chainages[lane]),
                      "riser", basis)
                component(f"K2:funnel-item-{lane}", funnel, "funnel", "Воронка кровельная с обогревом",
                          "DN110; модель из расчётного приложения", basis)
                component(f"K2:lower-revision-{lane}", bases[lane], "revision", "Ревизия стояка", "DN100", basis,
                          f"section:K2-{lane}:riser-revision", family=family)
    result = NetworkTakeoff(tuple(points), tuple(routes), tuple(components), (
        "Полная предложенная К1/К2: 8 квартир, 4 стояка каждой системы. На разрезе показаны характерные квартиры.",
        "Метры - протяжённость осевых трасс с габаритами фасонины, НЕ чистая длина отрезков труб и НЕ заказная спецификация.",
        "Квартирные трассы и участки до наружной грани стены предложены для проверки подсчёта; из загруженных планов не измерены.",
        "Числа фасонных частей получены из монтажных узлов; артикулы, размеры раструбов и комплекты соединений ещё не выбраны.",
        "Крепёж, соединительные муфты SML, изоляция, огнезаделка, противопожарные манжеты и узлы кровли требуют отдельной привязки.",
        "Не включены наружная сеть, В1, В2, Т3/Т4. По ним нельзя использовать эту ведомость как полный объём дома.",
        "Запас, раскрой и длины вставок не добавляются автоматически. Подтверждение трасс и доступности обслуживания остаётся обязательным.",
    ))
    result.validate()
    return result


def educational_residential_takeoff(model: ResidentialPreview, calc: ResidentialCalculation) -> NetworkTakeoff:
    return build_residential_takeoff(model, calc, apartment_route=EDUCATIONAL_APARTMENT_ROUTE,
        outlet_lengths_m=(1.2, 1.2), outlet_source="Учебное предложение v1: по 1,20 м от опуска до наружной "
        "грани стены для К1 и К2; трасса к колодцам не включена. Не обмер АР.")
