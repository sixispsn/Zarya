"""Explicit drawing inputs; never a substitute for the meter calculation."""
from dataclasses import dataclass, field
from math import isfinite
from app.pz.metering_pipes import MeteringPipeSection, PIPE_ROLES
from app.pz.metering_connections import CONNECTION_ROLES
from app.pz.metering_reducers import REDUCER_ROLES
from app.pz.metering_mounting import MeteringMounting


@dataclass
class MeteringDetailData:
    # Compatibility for saved YAML/projects. New Studio projects explicitly
    # select common; absence in an old project must not rewrite its topology.
    inlet_metering_mode: str = field(default="per_inlet", kw_only=True)
    # Explicit migration: saved common-meter projects retain their old graph.
    common_topology: str = field(default="merge_before", kw_only=True)
    room_number: str = ""
    room_name: str = ""
    inlet_dn: int | None = None
    bypass_dn: int | None = None
    fire_branch_dn: int | None = None
    meter_model: str = ""
    inlet_elevation_m: float | None = None
    # Stable manufacturer IDs, pinned to a versioned dimensions catalogue.
    # This layer does not override the accepted hydraulic meter selection.
    catalogue_revision: str = ""
    catalogue_items: dict[str, str] = field(default_factory=dict)
    # Product binding for each calculated node; automatic Studio proposals are
    # explicitly separate from a manually accepted manufacturer assignment.
    meter_selection_mode: str = "manual"
    meter_products: dict[str, str] = field(default_factory=dict)
    meter_mounting: str = "unknown"
    # Independent passport orientation per calculated node; old files retain
    # the scalar fallback. The drawing axis must match the primary node.
    meter_orientations: dict[str, str] = field(default_factory=dict)
    filter_offset_family: str = ""
    filter_inline_family: str = ""
    # Assembly axis and each component's permitted mounting are separate.
    assembly_orientation: str = "horizontal_dial_up"
    component_orientations: dict[str, str] = field(default_factory=dict)
    flexible_connections: dict = field(default_factory=dict)
    design_pressure_bar: float | None = None
    water_temperature_c: float | None = None
    # Explicit installation conditions, not inferred from the room's name,
    # inlet elevation, city or an enabled ASKUE checkbox.
    room_location: str = "unknown"
    room_min_temperature_c: float | None = None
    service_access_confirmed: bool | None = None
    seismic_design_basis: str = ""
    permafrost_design_basis: str = ""
    # Local pipe at the support, not meter DN or nominal inlet diameter.
    support_pipe_outer_diameter_mm: float | None = None
    support_pipe_material: str = "unknown"
    support_design_load_z_n: float | None = None
    # Local sections can have different materials. Never inherit cold_mains:
    # its free-text classifier cannot distinguish stainless steel from VGP.
    pipe_sections: dict[str, MeteringPipeSection] = field(default_factory=dict)
    support_pipe_section: str = ""
    connection_items: dict[str, str] = field(default_factory=dict)
    # Optional intermediate threaded fitting: equipment -> fitting -> socket.
    # It is never inferred just because both adjacent ports are female.
    connection_thread_items: dict[str, str] = field(default_factory=dict)
    # Explicit metal transitions outside the meter's straight-section kit.
    reducer_items: dict[str, str] = field(default_factory=dict)
    # Multi-port bodies, reducers and explicit filter_turn_in/out elbows.
    # No auto tee/cross/elbow product substitution.
    fitting_items: dict[str, str] = field(default_factory=dict)
    # Bind straight F/F joints by graph ID, not by a mutable SO row number.
    # Proposals only fill unassigned joints with one compatible catalogue item.
    inline_joint_items: dict[str, str] = field(default_factory=dict)
    inline_joint_selection_mode: str = "manual"
    service_items: dict[str, str] = field(default_factory=dict)
    service_selection_mode: str = "manual"
    # Explicit opt-in; existing projects retain their authored topology.
    maintenance_layout: str = "existing"
    gauge_pressure_mode: str = "unknown"
    # Optional wishes / explicit accessory choices; never overwrite hydraulics.
    enhancements: dict[str, str] = field(default_factory=dict)
    # Project procurement preference, stored beside equipment options. Applies
    # to all equipment, not merely the manufacturer printed on the meter.
    russian_equipment_only: bool = False
    mounting: MeteringMounting = field(default_factory=MeteringMounting)

    def __post_init__(self):
        # Accept plain YAML/asdict payloads, preserving malformed data for
        # validate() instead of silently discarding unknown fields.
        from app.pz.metering_flexible import FlexibleConnectionChoice
        if isinstance(self.flexible_connections, dict):
            for role, value in self.flexible_connections.items():
                if isinstance(value, dict):
                    try:
                        self.flexible_connections[role] = FlexibleConnectionChoice(**value)
                    except TypeError:
                        pass
        if isinstance(self.mounting, dict):
            try:
                self.mounting = MeteringMounting(**self.mounting)
            except TypeError:
                pass
        if isinstance(self.pipe_sections, dict):
            parsed = {}
            for role, value in self.pipe_sections.items():
                if isinstance(value, dict):
                    try:
                        value = MeteringPipeSection(**value)
                    except TypeError:
                        pass
                parsed[role] = value
            self.pipe_sections = parsed

    def validate(self) -> list[str]:
        from app.pz.metering_options import validate_options
        errors = validate_options(self.enhancements)
        if self.inlet_metering_mode not in ("common", "per_inlet"):
            errors.append("metering_detail.inlet_metering_mode: неизвестная схема учёта")
        if self.common_topology not in ("merge_before", "gost_g1"):
            errors.append("metering_detail.common_topology: неизвестная топология общего ВУ")
        from app.pz.metering_flexible import FlexibleConnectionChoice, FLEX_ROLES
        if not isinstance(self.flexible_connections, dict):
            errors.append('metering_detail.flexible_connections: требуется словарь')
        else:
            for role, value in self.flexible_connections.items():
                if role not in FLEX_ROLES or not isinstance(value,FlexibleConnectionChoice):
                    errors.append('metering_detail.flexible_connections: неизвестная роль/формат')
                else:
                    errors.extend(f'metering_detail.flexible_connections.{role}: {e}' for e in value.validate())
        from app.pz.metering_fitting_selection import FITTING_ROLES
        if not isinstance(self.fitting_items, dict) or any(
            k not in FITTING_ROLES or not isinstance(v, str) or not v.strip()
            for k, v in self.fitting_items.items()
        ):
            errors.append("metering_detail.fitting_items: нужны известные узлы и ID фасонных частей")
        if type(self.russian_equipment_only) is not bool:
            errors.append("metering_detail.russian_equipment_only: требуется true/false")
        if not isinstance(self.mounting, MeteringMounting):
            errors.append("metering_detail.mounting: неверные данные монтажных размеров")
        else:
            errors.extend("metering_detail.mounting." + e for e in self.mounting.validate())
        if self.meter_selection_mode not in ("manual", "catalogue_proposal"):
            errors.append("metering_detail.meter_selection_mode: неизвестный режим")
        if self.inline_joint_selection_mode not in ("manual", "catalogue_proposal"):
            errors.append("metering_detail.inline_joint_selection_mode: неизвестный режим")
        from app.pz.metering_service import SERVICE_ROLES
        if self.service_selection_mode not in ("manual", "catalogue_proposal"):
            errors.append("metering_detail.service_selection_mode: неизвестный режим")
        if self.maintenance_layout not in ("existing", "serviceable"):
            errors.append("metering_detail.maintenance_layout: неизвестная компоновка обслуживания")
        if self.gauge_pressure_mode not in ("unknown", "constant", "variable"):
            errors.append("metering_detail.gauge_pressure_mode: неизвестный режим давления")
        if not isinstance(self.service_items, dict) or any(
            k not in SERVICE_ROLES or not isinstance(v, str) or not v.strip()
            for k, v in self.service_items.items()
        ):
            errors.append("metering_detail.service_items: нужны известные роли и ID изделий")
        if not isinstance(self.inline_joint_items, dict) or any(
            not isinstance(k, str) or not k.startswith("joint_")
            or not isinstance(v, str) or not v.strip()
            for k, v in self.inline_joint_items.items()
        ):
            errors.append("metering_detail.inline_joint_items: нужны ID стыков joint_* и непустые ID изделий")
        from app.data.metering_installation import ORIENTATIONS
        if not isinstance(self.meter_orientations, dict) or any(
            k not in ("total", "cold", "hot") or v not in ORIENTATIONS
            for k, v in self.meter_orientations.items()
        ):
            errors.append("metering_detail.meter_orientations: неизвестный узел/ориентация")
        if self.filter_offset_family not in ("", "valtec_vt192_vtr090"):
            errors.append("metering_detail.filter_offset_family: неизвестное исполнение")
        if self.filter_inline_family not in ("", "valtec_vt386"):
            errors.append("metering_detail.filter_inline_family: неизвестное исполнение")
        if self.filter_inline_family and self.filter_offset_family:
            errors.append("Нельзя одновременно выбрать фильтр на оси и со смещением")
        if self.meter_mounting not in ("unknown", "vertical", *ORIENTATIONS):
            errors.append("metering_detail.meter_mounting: неизвестная ориентация")
        if self.assembly_orientation not in ORIENTATIONS:
            errors.append("metering_detail.assembly_orientation: неизвестная ориентация")
        if not isinstance(self.component_orientations, dict) or any(
            k not in ('inlet_valve','meter_valves','filter','check_valve','bypass_valve','outlet_valve')
            or v not in ORIENTATIONS for k,v in self.component_orientations.items()
        ):
            errors.append("metering_detail.component_orientations: неизвестная роль/ориентация")
        if not isinstance(self.meter_products, dict) or any(
            k not in ("total", "cold", "hot") or not isinstance(v, str) or not v.strip()
            for k, v in self.meter_products.items()
        ):
            errors.append("metering_detail.meter_products: нужны узлы total/cold/hot и ID изделий")
        for name in ("inlet_dn", "bypass_dn", "fire_branch_dn"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value <= 0):
                errors.append(f"metering_detail.{name}: требуется положительный целый DN")
        if self.inlet_elevation_m is not None and (
            isinstance(self.inlet_elevation_m, bool)
            or not isinstance(self.inlet_elevation_m, (int, float))
            or not isfinite(self.inlet_elevation_m)
        ):
            errors.append("metering_detail.inlet_elevation_m: требуется конечная отметка")
        for name in ("room_number", "room_name", "meter_model", "catalogue_revision",
                     "seismic_design_basis", "permafrost_design_basis"):
            if not isinstance(getattr(self, name), str):
                errors.append(f"metering_detail.{name}: требуется строка")
        for name in ("design_pressure_bar", "water_temperature_c", "room_min_temperature_c"):
            value = getattr(self, name)
            if value is not None and (type(value) not in (int, float) or not isfinite(value)
                                      or (name == "design_pressure_bar" and value <= 0)):
                errors.append(f"metering_detail.{name}: некорректное числовое значение")
        for name in ("support_pipe_outer_diameter_mm", "support_design_load_z_n"):
            value = getattr(self, name)
            if value is not None and (type(value) not in (int, float) or not isfinite(value) or value <= 0):
                errors.append(f"metering_detail.{name}: требуется положительное конечное число")
        if self.support_pipe_material not in ("unknown", "stainless_steel", "steel", "copper", "plastic", "other"):
            errors.append("metering_detail.support_pipe_material: неизвестный материал трубы")
        if self.room_location not in ("unknown", "basement", "first_floor",
                                      "ventilated_crawlspace", "outside", "other"):
            errors.append("metering_detail.room_location: неизвестное место установки")
        if self.service_access_confirmed is not None and type(self.service_access_confirmed) is not bool:
            errors.append("metering_detail.service_access_confirmed: требуется true/false или null")
        roles = {"meter", "inlet_valve", "meter_valves", "filter", "check_valve", "bypass_valve",
                 "meter_connections", "pipe_clamp", "outlet_valve"}
        if not isinstance(self.catalogue_items, dict) or any(
            role not in roles or not isinstance(ident, str) or not ident.strip()
            for role, ident in self.catalogue_items.items()
        ):
            errors.append("metering_detail.catalogue_items: нужны известные роли и непустые ID изделий")
        if not isinstance(self.pipe_sections, dict):
            errors.append("metering_detail.pipe_sections: требуется словарь участков")
        else:
            for role, section in self.pipe_sections.items():
                prefix = f"metering_detail.pipe_sections.{role}"
                if role not in PIPE_ROLES or not isinstance(section, MeteringPipeSection):
                    errors.append(f"{prefix}: неизвестный участок или некорректные данные трубы")
                else:
                    errors.extend(f"{prefix}.{error}" for error in section.validate())
        if not isinstance(self.connection_items, dict) or any(
            role not in CONNECTION_ROLES or not isinstance(ident, str) or not ident.strip()
            for role, ident in self.connection_items.items()
        ):
            errors.append("metering_detail.connection_items: нужны известные стыки и непустые ID соединителей")
        if not isinstance(self.connection_thread_items, dict) or any(
            role not in CONNECTION_ROLES or not isinstance(ident, str) or not ident.strip()
            for role, ident in self.connection_thread_items.items()
        ):
            errors.append("metering_detail.connection_thread_items: нужны известные стыки и непустые ID соединителей")
        elif isinstance(self.connection_items, dict) and any(
            role not in self.connection_items for role in self.connection_thread_items
        ):
            errors.append("metering_detail.connection_thread_items: промежуточная деталь без конечного соединителя трубы")
        if not isinstance(self.reducer_items, dict) or any(
            role not in REDUCER_ROLES or not isinstance(ident, str) or not ident.strip()
            for role, ident in self.reducer_items.items()
        ):
            errors.append("metering_detail.reducer_items: нужны известные места переходов и непустые ID изделий")
        if not isinstance(self.support_pipe_section, str) or (
            self.support_pipe_section and self.support_pipe_section not in PIPE_ROLES
        ):
            errors.append("metering_detail.support_pipe_section: неизвестный участок трубы")
        return errors
