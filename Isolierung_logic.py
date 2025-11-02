"""Core logic for the insulation calculation tool.

This module provides a new data model for materials, layers and projects,
implements SQLite based persistence and exposes the core solver interface.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Literal, Optional, Sequence, Tuple

_DB_PATH = "projects.db"
_DB_INITIALIZED = False


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Material:
    """Represents a material with optional temperature dependant k(T) data."""

    id: Optional[int]
    name: str
    notes: Optional[str] = None
    k_const: Optional[float] = None
    k_points: List[Tuple[float, float]] = field(default_factory=list)


@dataclass(slots=True)
class Layer:
    """Represents a single insulation layer."""

    thickness_mm: float
    mode: Literal["material", "custom"]
    material_id: Optional[int] = None
    use_kT: bool = False
    k_const: Optional[float] = None
    note: Optional[str] = None

    def __post_init__(self) -> None:
        if self.thickness_mm <= 0:
            raise ValueError("Layer thickness must be positive.")
        if self.mode not in {"material", "custom"}:
            raise ValueError("Layer mode must be either 'material' or 'custom'.")
        if self.mode == "material":
            if self.material_id is None:
                raise ValueError("Material layers require a material_id.")
            if not self.use_kT and self.k_const is not None:
                raise ValueError("Material layers must not provide k_const when use_kT is False.")
        else:  # custom layer
            if self.material_id is not None:
                raise ValueError("Custom layers must not reference a material_id.")
            if not self.use_kT:
                if self.k_const is None or self.k_const <= 0:
                    raise ValueError("Custom layers require a positive k_const value.")


@dataclass(slots=True)
class Project:
    """Represents a saved project."""

    name: str
    layers: List[Layer]
    T_left_C: float
    T_inf_C: float
    h_W_m2K: float


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _ensure_db() -> None:
    """Initialise the SQLite database if it does not yet exist."""

    global _DB_INITIALIZED
    if _DB_INITIALIZED:
        return

    Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS materials (
                id INTEGER PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                notes TEXT,
                k_const REAL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS material_k_points (
                material_id INTEGER NOT NULL,
                T_C REAL NOT NULL,
                k_W_mK REAL NOT NULL,
                UNIQUE(material_id, T_C),
                FOREIGN KEY(material_id) REFERENCES materials(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                layers_json TEXT NOT NULL,
                T_left_C REAL NOT NULL,
                T_inf_C REAL NOT NULL,
                h_W_m2K REAL NOT NULL
            )
            """
        )
    _DB_INITIALIZED = True


def _get_connection() -> sqlite3.Connection:
    _ensure_db()
    conn = sqlite3.connect(_DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------------------
# Material CRUD
# ---------------------------------------------------------------------------


def create_material(name: str, notes: Optional[str] = None, k_const: Optional[float] = None) -> int:
    """Create a new material and return its database id."""

    if not name or not name.strip():
        raise ValueError("Material name must not be empty.")
    if k_const is not None and k_const <= 0:
        raise ValueError("k_const must be positive if provided.")

    with _get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO materials (name, notes, k_const) VALUES (?, ?, ?)",
            (name.strip(), notes, k_const),
        )
        material_id = cursor.lastrowid
    return int(material_id)


def update_material(
    material_id: int,
    *,
    name: Optional[str] = None,
    notes: Optional[str] = None,
    k_const: Optional[float] = None,
) -> bool:
    """Update selected fields of a material."""

    fields: List[str] = []
    values: List[object] = []

    if name is not None:
        if not name.strip():
            raise ValueError("Material name must not be empty.")
        fields.append("name = ?")
        values.append(name.strip())
    if notes is not None:
        fields.append("notes = ?")
        values.append(notes)
    if k_const is not None:
        if k_const <= 0:
            raise ValueError("k_const must be positive if provided.")
        fields.append("k_const = ?")
        values.append(k_const)

    if not fields:
        return False

    values.append(material_id)
    with _get_connection() as conn:
        cursor = conn.execute(
            f"UPDATE materials SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        return cursor.rowcount > 0


def delete_material(material_id: int) -> bool:
    """Delete a material and its associated k(T) points."""

    with _get_connection() as conn:
        cursor = conn.execute("DELETE FROM materials WHERE id = ?", (material_id,))
        return cursor.rowcount > 0


def _fetch_material_points(conn: sqlite3.Connection, material_ids: Sequence[int]) -> Dict[int, List[Tuple[float, float]]]:
    if not material_ids:
        return {}
    placeholders = ",".join("?" for _ in material_ids)
    cursor = conn.execute(
        f"SELECT material_id, T_C, k_W_mK FROM material_k_points WHERE material_id IN ({placeholders}) ORDER BY T_C",
        tuple(material_ids),
    )
    points: Dict[int, List[Tuple[float, float]]] = {mid: [] for mid in material_ids}
    for material_id, T_C, k_W_mK in cursor.fetchall():
        points.setdefault(material_id, []).append((float(T_C), float(k_W_mK)))
    return points


def list_materials() -> List[Material]:
    """Return a list of all materials including their k(T) points."""

    with _get_connection() as conn:
        cursor = conn.execute("SELECT id, name, notes, k_const FROM materials ORDER BY name")
        rows = cursor.fetchall()
        ids = [row[0] for row in rows]
        point_map = _fetch_material_points(conn, ids)

    materials = [
        Material(
            id=row[0],
            name=row[1],
            notes=row[2],
            k_const=row[3],
            k_points=point_map.get(row[0], []),
        )
        for row in rows
    ]
    return materials


def get_material(material_id: int) -> Material:
    """Load a single material including its k(T) points."""

    with _get_connection() as conn:
        cursor = conn.execute(
            "SELECT id, name, notes, k_const FROM materials WHERE id = ?",
            (material_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise KeyError(f"Material with id {material_id} not found.")
        points = _fetch_material_points(conn, [material_id]).get(material_id, [])

    return Material(id=row[0], name=row[1], notes=row[2], k_const=row[3], k_points=points)


def upsert_k_points(material_id: int, points: Iterable[Tuple[float, float]]) -> None:
    """Replace the k(T) support points for a material."""

    cleaned: List[Tuple[float, float]] = []
    seen: set[float] = set()

    for T_C, k_W_mK in sorted(points, key=lambda item: item[0]):
        if k_W_mK <= 0:
            raise ValueError("Thermal conductivity values must be positive.")
        if T_C in seen:
            raise ValueError("Duplicate temperature values detected.")
        seen.add(T_C)
        cleaned.append((float(T_C), float(k_W_mK)))

    # Ensure material exists to avoid silent failures when deleting.
    _ = get_material(material_id)

    with _get_connection() as conn:
        conn.execute("DELETE FROM material_k_points WHERE material_id = ?", (material_id,))
        if cleaned:
            conn.executemany(
                "INSERT INTO material_k_points (material_id, T_C, k_W_mK) VALUES (?, ?, ?)",
                ((material_id, T_C, k_W_mK) for T_C, k_W_mK in cleaned),
            )


# ---------------------------------------------------------------------------
# Project persistence
# ---------------------------------------------------------------------------


def _layer_to_dict(layer: Layer) -> Dict[str, object]:
    return {
        "thickness_mm": layer.thickness_mm,
        "mode": layer.mode,
        "material_id": layer.material_id,
        "use_kT": layer.use_kT,
        "k_const": layer.k_const,
        "note": layer.note,
    }


def _layer_from_dict(data: Dict[str, object]) -> Layer:
    return Layer(
        thickness_mm=float(data["thickness_mm"]),
        mode=data["mode"],
        material_id=data.get("material_id"),
        use_kT=bool(data.get("use_kT", False)),
        k_const=data.get("k_const"),
        note=data.get("note"),
    )


def save_project(project: Project) -> None:
    """Store a project in the database."""

    if not project.name or not project.name.strip():
        raise ValueError("Project name must not be empty.")
    if not project.layers:
        raise ValueError("Projects must contain at least one layer.")
    if project.h_W_m2K <= 0:
        raise ValueError("Convective heat transfer coefficient must be positive.")

    layers_json = json.dumps([_layer_to_dict(layer) for layer in project.layers])

    with _get_connection() as conn:
        conn.execute(
            """
            INSERT INTO projects (name, layers_json, T_left_C, T_inf_C, h_W_m2K)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                layers_json = excluded.layers_json,
                T_left_C = excluded.T_left_C,
                T_inf_C = excluded.T_inf_C,
                h_W_m2K = excluded.h_W_m2K
            """,
            (
                project.name.strip(),
                layers_json,
                project.T_left_C,
                project.T_inf_C,
                project.h_W_m2K,
            ),
        )


def load_project(name: str) -> Project:
    """Load a project by name."""

    with _get_connection() as conn:
        cursor = conn.execute(
            "SELECT name, layers_json, T_left_C, T_inf_C, h_W_m2K FROM projects WHERE name = ?",
            (name,),
        )
        row = cursor.fetchone()
        if row is None:
            raise KeyError(f"Project '{name}' not found.")

    layers_data = json.loads(row[1])
    layers = [_layer_from_dict(layer_dict) for layer_dict in layers_data]

    return Project(
        name=row[0],
        layers=layers,
        T_left_C=row[2],
        T_inf_C=row[3],
        h_W_m2K=row[4],
    )


def delete_project(name: str) -> bool:
    with _get_connection() as conn:
        cursor = conn.execute("DELETE FROM projects WHERE name = ?", (name,))
        return cursor.rowcount > 0


def get_all_project_names() -> List[str]:
    with _get_connection() as conn:
        cursor = conn.execute("SELECT name FROM projects ORDER BY name")
        return [row[0] for row in cursor.fetchall()]


# ---------------------------------------------------------------------------
# Thermal conductivity interpolation
# ---------------------------------------------------------------------------


def interp_k(material: Material, T_C: float, *, mode: str = "clamp") -> float:
    """Piece-wise linear interpolation for a material's thermal conductivity."""

    if material.k_points:
        points = sorted(material.k_points, key=lambda item: item[0])
        if mode != "clamp":
            raise ValueError("Only 'clamp' interpolation mode is currently supported.")
        if len(points) == 1:
            return points[0][1]
        if T_C <= points[0][0]:
            return points[0][1]
        if T_C >= points[-1][0]:
            return points[-1][1]
        for (T0, k0), (T1, k1) in zip(points[:-1], points[1:]):
            if T0 <= T_C <= T1:
                if T1 == T0:
                    return k1
                fraction = (T_C - T0) / (T1 - T0)
                return k0 + fraction * (k1 - k0)
        return points[-1][1]

    if material.k_const is None:
        raise ValueError("Material has neither k_points nor k_const defined.")
    return material.k_const


# ---------------------------------------------------------------------------
# Solver interfaces
# ---------------------------------------------------------------------------


def compute_multilayer_layers(
    layers: Sequence[Layer],
    T_left_C: float,
    T_inf_C: float,
    h_W_m2K: float,
) -> Dict[str, List[float] | float]:
    """Compute the heat flux and temperature profile for a layer stack."""

    if not layers:
        raise ValueError("At least one layer is required for the computation.")
    if h_W_m2K <= 0:
        raise ValueError("Convective heat transfer coefficient must be positive.")

    requires_kT = any(layer.use_kT for layer in layers)
    if requires_kT:
        return solve_multilayer_kT(layers, T_left_C, T_inf_C, h_W_m2K)

    constant_k_values: List[float] = []
    material_cache: Dict[int, Material] = {}

    for layer in layers:
        if layer.mode == "material":
            assert layer.material_id is not None
            if layer.material_id not in material_cache:
                material_cache[layer.material_id] = get_material(layer.material_id)
            material = material_cache[layer.material_id]
            if material.k_const is None:
                raise ValueError(
                    f"Material '{material.name}' does not define a constant k value."
                )
            constant_k_values.append(material.k_const)
        else:  # custom
            assert layer.k_const is not None
            constant_k_values.append(layer.k_const)

    return _solve_constant_k(layers, constant_k_values, T_left_C, T_inf_C, h_W_m2K)


def _solve_constant_k(
    layers: Sequence[Layer],
    k_values: Sequence[float],
    T_left_C: float,
    T_inf_C: float,
    h_W_m2K: float,
) -> Dict[str, List[float] | float]:
    thickness_m = [layer.thickness_mm / 1000.0 for layer in layers]

    resistances = []
    for thickness, k_value in zip(thickness_m, k_values):
        if k_value <= 0:
            raise ValueError("Thermal conductivity must be positive.")
        resistances.append(thickness / k_value)

    R_conv = 1.0 / h_W_m2K
    total_resistance = sum(resistances) + R_conv
    q = (T_left_C - T_inf_C) / total_resistance

    interface_temperatures = [T_left_C]
    current_T = T_left_C
    for R in resistances:
        current_T -= q * R
        interface_temperatures.append(current_T)

    x_m = [0.0]
    for thickness in thickness_m:
        x_m.append(x_m[-1] + thickness)

    T_profile = interface_temperatures.copy()

    return {
        "q_W_m2": q,
        "interface_T_C": interface_temperatures,
        "x_m": x_m,
        "T_profile_C": T_profile,
    }


def solve_multilayer_kT(
    layers: Sequence[Layer],
    T_left_C: float,
    T_inf_C: float,
    h_W_m2K: float,
) -> Dict[str, List[float] | float]:
    raise NotImplementedError("Temperature dependent solver not yet implemented.")


__all__ = [
    "Layer",
    "Material",
    "Project",
    "compute_multilayer_layers",
    "create_material",
    "delete_material",
    "get_all_project_names",
    "get_material",
    "interp_k",
    "list_materials",
    "load_project",
    "save_project",
    "solve_multilayer_kT",
    "update_material",
    "upsert_k_points",
]
