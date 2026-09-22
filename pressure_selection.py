"""Stable observation identity and defensive Plotly event parsing."""
from collections.abc import Mapping
import hashlib
import math
from numbers import Integral, Real


def field(value, key, default=None):
    """Read mappings, Streamlit dict-like wrappers, or attribute-style payloads."""
    if value is None:
        return default
    try:
        return value[key]
    except (KeyError, IndexError, TypeError, AttributeError):
        if isinstance(key, str):
            try:
                return getattr(value, key)
            except (AttributeError, KeyError, TypeError):
                pass
    return default


def normalize_id(value):
    # Strings avoid JavaScript integer precision and binary-array serialization.
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        return value if value.strip() else None
    if isinstance(value, Integral):
        return str(value)
    if isinstance(value, Real) and math.isfinite(value) and float(value).is_integer():
        return str(int(value))
    return None


def ensure_pressure_ids(frame):
    """Assign identity before sorting/filtering; preserve valid supplied IDs.

    Source index plus observation content produces deterministic fallback IDs on
    reruns. Once assigned, IDs travel with each row, including duplicate readings.
    """
    out = frame.copy()
    candidates = next((out[c].tolist() for c in ("_point_id", "point_id", "row_id", "id") if c in out), [None] * len(out))
    reserved = {normalize_id(value) for value in candidates} - {None}
    used, ids = set(), []
    for (index, row), candidate in zip(out.iterrows(), candidates):
        point_id = normalize_id(candidate)
        if point_id is None or point_id in used:
            source = repr((index, row.get("well_id"), row.get("date"), row.get("pressure_psi")))
            base = "p_" + hashlib.sha256(source.encode()).hexdigest()[:24]
            point_id, suffix = base, 0
            while point_id in used or point_id in reserved:
                suffix += 1
                point_id = f"{base}_{suffix}"
        used.add(point_id)
        ids.append(point_id)
    out["_point_id"] = ids
    return out


def extract_point_id(point):
    custom = field(point, "customdata")
    # Bound nesting so malformed recursive wrappers cannot loop indefinitely.
    for _ in range(4):
        if custom is None:
            return None
        for key in ("_point_id", "point_id", "row_id", "id"):
            candidate = normalize_id(field(custom, key))
            if candidate is not None:
                return candidate
        if isinstance(custom, (list, tuple)):
            custom = custom[0] if custom else None
        elif isinstance(custom, Mapping) or hasattr(custom, "keys"):
            # Streamlit 1.62 / Plotly 7 observed payload: {'0': 1}.
            custom = field(custom, "0", field(custom, 0))
        elif callable(getattr(custom, "tolist", None)):
            try:
                custom = custom.tolist()
            except (ValueError, TypeError):
                return None
        else:
            return normalize_id(custom)
    return None


def parse_selection(event, ordered_ids, pressure_curves=(0,)):
    """Return validated IDs, whether the event is empty, and selection geometry."""
    selection = field(event, "selection")
    points = field(selection, "points")
    if not isinstance(points, (list, tuple)):
        return [], False, False
    valid = set(ordered_ids)
    selected = set()
    for point in points:
        curve = field(point, "curve_number", field(point, "curveNumber"))
        if isinstance(curve, bool) or not isinstance(curve, Integral) or curve not in pressure_curves:
            continue
        point_id = extract_point_id(point)
        if point_id in valid:
            selected.add(point_id)
    geometry = any(isinstance(field(selection, key), (list, tuple)) and len(field(selection, key)) > 0 for key in ("box", "lasso"))
    return [point_id for point_id in ordered_ids if point_id in selected], len(points) == 0, geometry


def clear_trend_selection(state, prefix, ordered_ids):
    state[prefix + "_selected_ids"] = []
    state[prefix + "_start"] = ordered_ids[0]
    state[prefix + "_end"] = ordered_ids[-1]
    state[prefix + "_chosen_pair"] = (ordered_ids[0], ordered_ids[-1])
    state[prefix + "_chart_revision"] = state.get(prefix + "_chart_revision", 0) + 1


def update_trend_selection(state, event, prefix, ordered_ids, pressure_curves=(0,)):
    ids, empty, geometry = parse_selection(event, ordered_ids, pressure_curves)
    if empty:
        clear_trend_selection(state, prefix, ordered_ids)
        return
    if not ids:
        return  # Malformed or non-pressure points must not erase a valid selection.
    if len(ids) == 1 and not geometry:
        previous = state.get(prefix + "_selected_ids", [])
        ids = [point_id for point_id in ordered_ids if point_id in set(previous + ids)]
    state[prefix + "_selected_ids"] = ids
    if len(ids) >= 2:
        state[prefix + "_start"] = ids[0]
        state[prefix + "_end"] = ids[-1]
