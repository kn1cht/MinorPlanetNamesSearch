"""Parser for MPCORB minor-planet orbit rows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


ORBIT_TYPES = {
    1: "Atira",
    2: "Aten",
    3: "Apollo",
    4: "Amor",
    5: "q < 1.665 AU",
    6: "Hungaria",
    8: "Hilda",
    9: "Jupiter Trojan",
    10: "Distant",
}


@dataclass(frozen=True)
class OrbitRecord:
    permid_or_packed: str
    readable_designation: str
    absolute_magnitude_h: float | None
    slope_g: float | None
    epoch: str
    mean_anomaly: float | None
    argument_perihelion: float | None
    ascending_node: float | None
    inclination: float | None
    eccentricity: float | None
    mean_daily_motion: float | None
    semimajor_axis: float | None
    uncertainty: str
    observations: int | None
    oppositions: int | None
    rms_residual: float | None
    flags_hex: str | None
    orbit_type: str | None
    is_neo: bool
    is_one_km_neo: bool
    is_pha: bool


def parse_mpcorb_lines(lines: list[str]) -> dict[str, OrbitRecord]:
    """Parse MPCORB rows into records keyed by readable/permanent designation."""
    records: dict[str, OrbitRecord] = {}
    for line in lines:
        record = parse_mpcorb_line(line)
        if not record:
            continue
        for key in _keys_for_record(record):
            records[key] = record
    return records


def parse_mpcorb_line(line: str) -> OrbitRecord | None:
    """Parse one fixed-width MPCORB row.

    Header/comment lines are ignored. Column indexes follow MPC's published
    1-based layout, converted to Python slices.
    """
    if len(line) < 103:
        return None
    packed = line[0:7].strip()
    if not packed or packed.startswith("-") or packed.lower().startswith("num"):
        return None

    flags_hex = line[161:165].strip() if len(line) >= 165 else ""
    readable = line[166:194].strip() if len(line) >= 167 else ""
    flags_value = _parse_hex(flags_hex)
    if flags_value is None:
        fallback = re.search(r"\s(?P<flags>[0-9A-Fa-f]{4})\s+(?P<readable>\(\d+\).*)$", line)
        if fallback:
            flags_hex = fallback.group("flags")
            readable = fallback.group("readable").strip()
            flags_value = _parse_hex(flags_hex)
    orbit_code = flags_value & 0x3F if flags_value is not None else 0

    orbit_type = ORBIT_TYPES.get(orbit_code)

    return OrbitRecord(
        permid_or_packed=packed,
        readable_designation=readable,
        absolute_magnitude_h=_float(line[8:13]),
        slope_g=_float(line[14:19]),
        epoch=line[20:25].strip(),
        mean_anomaly=_float(line[26:35]),
        argument_perihelion=_float(line[37:46]),
        ascending_node=_float(line[48:57]),
        inclination=_float(line[59:68]),
        eccentricity=_float(line[70:79]),
        mean_daily_motion=_float(line[80:91]),
        semimajor_axis=_float(line[92:103]),
        uncertainty=line[105:106].strip() if len(line) >= 106 else "",
        observations=_int(line[117:122]) if len(line) >= 122 else None,
        oppositions=_int(line[123:126]) if len(line) >= 126 else None,
        rms_residual=_float(line[137:141]) if len(line) >= 141 else None,
        flags_hex=flags_hex or None,
        orbit_type=orbit_type,
        is_neo=bool(flags_value is not None and flags_value & 2048),
        is_one_km_neo=bool(flags_value is not None and flags_value & 4096),
        is_pha=bool(flags_value is not None and flags_value & 32768),
    )


def parse_orbits_api_response(payload: Any) -> OrbitRecord | None:
    """Extract an OrbitRecord from the MPC Orbits API response."""
    mpc_orb = _first_mpc_orb(payload)
    if not mpc_orb:
        return None

    designation = mpc_orb.get("designation_data") or {}
    categorization = mpc_orb.get("categorization") or {}
    magnitude = mpc_orb.get("magnitude_data") or {}
    epoch = mpc_orb.get("epoch_data") or {}
    fit = mpc_orb.get("orbit_fit_statistics") or {}
    moid = mpc_orb.get("moid_data") or {}
    software = mpc_orb.get("software_data") or {}
    kep = _coefficient_map(mpc_orb.get("KEP") or {})
    com = _coefficient_map(mpc_orb.get("COM") or {})

    permid = str(designation.get("permid") or designation.get("packed_permid") or designation.get("orbfit_name") or "")
    eccentricity = _first_number(kep, com, key="e")
    semimajor_axis = _number(kep.get("a"))
    perihelion = _number(com.get("q"))
    if semimajor_axis is None and perihelion is not None and eccentricity is not None and eccentricity != 1:
        semimajor_axis = perihelion / (1 - eccentricity)
    orbit_type = _clean_orbit_type(categorization.get("orbit_type_str")) or _classify_orbit(
        semimajor_axis,
        eccentricity,
        perihelion,
        _first_number(kep, com, key="i"),
    )
    h_value = _number(magnitude.get("H"))
    earth_moid = _number(moid.get("Earth"))

    return OrbitRecord(
        permid_or_packed=permid,
        readable_designation=str(designation.get("iau_designation") or ""),
        absolute_magnitude_h=h_value,
        slope_g=_number(magnitude.get("G")),
        epoch=str(epoch.get("epoch") or ""),
        mean_anomaly=_number(kep.get("mean_anomaly")),
        argument_perihelion=_first_number(kep, com, key="argperi"),
        ascending_node=_first_number(kep, com, key="node"),
        inclination=_first_number(kep, com, key="i"),
        eccentricity=eccentricity,
        mean_daily_motion=None,
        semimajor_axis=semimajor_axis,
        uncertainty=_string_or_empty(fit.get("U_param")),
        observations=_int_from_any(fit.get("nobs_total")),
        oppositions=_int_from_any(fit.get("nopp")),
        rms_residual=_number(fit.get("not_normalized_RMS")),
        flags_hex=None,
        orbit_type=str(orbit_type) if orbit_type else None,
        is_neo=_is_neo_orbit_type(orbit_type) or bool(perihelion is not None and perihelion < 1.3),
        is_one_km_neo=bool((_is_neo_orbit_type(orbit_type) or bool(perihelion is not None and perihelion < 1.3)) and h_value is not None and h_value <= 17.75),
        is_pha=bool(earth_moid is not None and h_value is not None and earth_moid <= 0.05 and h_value <= 22.0),
    )


def _first_mpc_orb(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, list) or not payload:
        return None
    first = payload[0]
    if not isinstance(first, dict):
        return None
    mpc_orb = first.get("mpc_orb")
    if not isinstance(mpc_orb, list) or not mpc_orb or not isinstance(mpc_orb[0], dict):
        return None
    return mpc_orb[0]


def _coefficient_map(section: dict[str, Any]) -> dict[str, Any]:
    names = section.get("coefficient_names") or []
    values = section.get("coefficient_values") or []
    if not isinstance(names, list) or not isinstance(values, list):
        return {}
    return {str(name): value for name, value in zip(names, values)}


def _first_number(*maps: dict[str, Any], key: str) -> float | None:
    for values in maps:
        number = _number(values.get(key))
        if number is not None:
            return number
    return None


def _clean_orbit_type(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _classify_orbit(
    semimajor_axis: float | None,
    eccentricity: float | None,
    perihelion: float | None,
    inclination: float | None = None,
) -> str | None:
    if semimajor_axis is None or eccentricity is None:
        return None
    q = perihelion if perihelion is not None else semimajor_axis * (1 - eccentricity)
    aphelion = semimajor_axis * (1 + eccentricity)
    if semimajor_axis < 1.0 and aphelion < 0.983:
        return "Atira"
    if semimajor_axis < 1.0 and aphelion >= 0.983:
        return "Aten"
    if semimajor_axis >= 1.0 and q <= 1.017:
        return "Apollo"
    if 1.017 < q < 1.3:
        return "Amor"
    if q >= 30.0 or semimajor_axis >= 30.0:
        return "TNO"
    if 5.5 <= semimajor_axis < 30.0:
        return "Centaur"
    if 5.0 <= semimajor_axis < 5.4:
        return "Jovian Trojan"
    if 3.7 <= semimajor_axis < 4.2:
        return "Hilda"
    if (
        inclination is not None
        and 1.78 <= semimajor_axis < 2.0
        and eccentricity < 0.18
        and 16.0 <= inclination <= 34.0
    ):
        return "Hungaria"
    if 1.3 <= q < 1.666:
        return "Mars Crosser"
    if 1.666 <= q and 2.0 <= semimajor_axis < 3.7:
        return "Main Belt"
    return None


def _is_neo_orbit_type(value: Any) -> bool:
    return str(value or "") in {"Atira", "Aten", "Apollo", "Amor"}


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_from_any(value: Any) -> int | None:
    number = _number(value)
    if number is None:
        return None
    return int(number)


def _string_or_empty(value: Any) -> str:
    return "" if value is None else str(value)


def _keys_for_record(record: OrbitRecord) -> set[str]:
    keys = {record.permid_or_packed}
    readable = record.readable_designation
    if readable:
        keys.add(readable)
        stripped = readable.strip("()")
        keys.add(stripped)
        if readable.startswith("(") and ")" in readable:
            keys.add(readable[1 : readable.index(")")])
    return {key for key in keys if key}


def _parse_hex(value: str) -> int | None:
    if not value:
        return None
    try:
        return int(value, 16)
    except ValueError:
        return None


def _float(value: str) -> float | None:
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _int(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None
