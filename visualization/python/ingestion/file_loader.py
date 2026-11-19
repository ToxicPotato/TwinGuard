"""Excel loading, robot detection, and typed field helpers."""

import pandas as pd


def load_all_sheets(path: str) -> dict:
    """Read every sheet from an Excel file into a DataFrame mapping."""
    workbook = pd.read_excel(path, sheet_name=None)
    sheets = {}
    for sheet_name, dataframe in workbook.items():
        sheets[sheet_name] = dataframe.loc[:, ~dataframe.columns.str.match(r"^time\.\d+$")]
    return sheets


def detect_robots(dataframe: pd.DataFrame) -> list[str]:
    """Return robot IDs in first-seen order from DataFrame columns."""
    seen_ids: set[str] = set()
    robot_ids: list[str] = []
    for column_name in dataframe.columns:
        parts = str(column_name).split(".", 1)
        if len(parts) != 2:
            continue

        robot_id = parts[0].strip()
        if not robot_id or robot_id == "time" or robot_id in seen_ids:
            continue

        seen_ids.add(robot_id)
        robot_ids.append(robot_id)
    return robot_ids


def _cell_value(row, column_name: str):
    """Return a raw cell value when the column exists."""
    if column_name not in row.index:
        return None

    value = row[column_name]
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return value


def _float_value(row, column_name: str) -> float | None:
    """Extract a float from a DataFrame row."""
    value = _cell_value(row, column_name)
    if value is None:
        return None

    try:
        return round(float(value), 5)
    except (TypeError, ValueError):
        return None


def _int_value(row, column_name: str) -> int | None:
    """Extract an int from a DataFrame row."""
    value = _cell_value(row, column_name)
    if value is None:
        return None

    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _string_value(row, column_name: str) -> str | None:
    """Extract a normalized string value from a DataFrame row."""
    value = _cell_value(row, column_name)
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    lowered = text.lower()
    if lowered in ("0", "0.0", "none", "nan"):
        return None

    return text


def _bool_value(row, column_name: str) -> bool | None:
    """Extract a bool from a DataFrame row."""
    value = _cell_value(row, column_name)
    if value is None:
        return None

    if isinstance(value, bool):
        return value

    try:
        return float(value) > 0.5
    except (TypeError, ValueError):
        lowered = str(value).strip().lower()
        if lowered in ("true", "1", "yes"):
            return True
        if lowered in ("false", "0", "no"):
            return False
        return None
