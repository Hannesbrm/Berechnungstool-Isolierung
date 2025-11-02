"""
Isolierung_logic.py
Berechnet die stationäre 1D-Temperaturverteilung in einer mehrschichtigen Isolierung
mit konvektiver Wärmeabgabe. Enthält Funktionen zum Speichern/Laden von Projekten in SQLite.
"""
import json
import sqlite3
from dataclasses import dataclass, field
from typing import List, Dict, Optional

@dataclass
class Layer:
    thickness_mm: float
    k: float
    thickness_m: float = field(init=False)

    def __post_init__(self):
        if self.thickness_mm <= 0:
            raise ValueError("Schichtdicke muss > 0 sein.")
        if self.k <= 0:
            raise ValueError("Wärmeleitfähigkeit muss > 0 sein.")
        self.thickness_m = self.thickness_mm / 1000.0

@dataclass
class Results:
    q: float
    resistances_cond: List[float]
    resistance_conv: float
    interface_temperatures: List[float]

@dataclass
class Project:
    name: str
    thicknesses: List[float]
    ks: List[float]
    T_left: float
    T_inf: float
    h: float
    result: Optional[Dict] = None

class MultiLayerModel:
    def __init__(self, layers: List[Layer], T_left_C: float, T_inf_C: float, h: float):
        if not layers:
            raise ValueError("Es muss mindestens eine Schicht angegeben werden.")
        if h <= 0:
            raise ValueError("Wärmeübergangskoeffizient h muss > 0 sein.")
        self.layers = layers
        self.T_left = T_left_C
        self.T_inf = T_inf_C
        self.h = h

    def _conduction_resistances(self) -> List[float]:
        return [layer.thickness_m / layer.k for layer in self.layers]

    def solve(self) -> Results:
        R_cond = self._conduction_resistances()
        R_conv = 1 / self.h
        R_total = sum(R_cond) + R_conv
        q = (self.T_left - self.T_inf) / R_total
        temps = [self.T_left]
        T_curr = self.T_left
        for R in R_cond:
            T_curr -= q * R
            temps.append(T_curr)
        temps.append(self.T_inf)
        return Results(q, R_cond, R_conv, temps)

def compute_multilayer(
    thickness_mm_list: List[float],
    k_list: List[float],
    T_left_C: float,
    T_inf_C: float,
    h: float
) -> Dict:
    if len(thickness_mm_list) != len(k_list):
        raise ValueError("Die Anzahl der Dicken und Wärmeleitwerte muss übereinstimmen.")
    if not thickness_mm_list:
        raise ValueError("Es muss mindestens eine Schicht angegeben werden.")

    layers = [Layer(t, k) for t, k in zip(thickness_mm_list, k_list)]
    model = MultiLayerModel(layers, T_left_C, T_inf_C, h)
    res = model.solve()
    positions = [0.0]
    for thickness in thickness_mm_list:
        positions.append(positions[-1] + thickness)
    positions.append(positions[-1])
    labels = ["Innenoberfläche"]
    labels.extend([f"Grenzfläche {i + 1}" for i in range(len(thickness_mm_list))])
    labels.append("Umgebung")
    return {
        "q": res.q,
        "interface_temperatures": res.interface_temperatures,
        "R_total": sum(res.resistances_cond) + res.resistance_conv,
        "temperature_positions_mm": positions,
        "temperature_labels": labels,
        "T_left": T_left_C,
        "T_inf": T_inf_C,
    }

# --- SQLite-Datenbank ---
_DB_PATH = "projects.db"
_DB_INITIALIZED = False


def _ensure_db() -> None:
    """Erstellt die Datenbank beim ersten Zugriff."""
    global _DB_INITIALIZED
    if _DB_INITIALIZED:
        return
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                name TEXT PRIMARY KEY,
                thicknesses TEXT,
                ks TEXT,
                T_left REAL,
                T_inf REAL,
                h REAL,
                result TEXT
            )
            """
        )
    _DB_INITIALIZED = True


def save_project(name: str, thicknesses: List[float], ks: List[float], T_left: float, T_inf: float, h: float, result: Dict) -> bool:
    """Speichert ein Projekt in der SQLite-Datenbank."""
    try:
        _ensure_db()
        with sqlite3.connect(_DB_PATH) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO projects
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    json.dumps(thicknesses),
                    json.dumps(ks),
                    T_left,
                    T_inf,
                    h,
                    json.dumps(result),
                ),
            )
        return True
    except Exception as e:
        print(f"Fehler beim Speichern: {e}")
        return False

def load_project(name: str) -> Optional[Project]:
    """Lädt ein Projekt aus der SQLite-Datenbank."""
    try:
        _ensure_db()
        with sqlite3.connect(_DB_PATH) as conn:
            cursor = conn.execute("SELECT * FROM projects WHERE name = ?", (name,))
            row = cursor.fetchone()
        if row:
            return Project(
                name=row[0],
                thicknesses=json.loads(row[1]),
                ks=json.loads(row[2]),
                T_left=row[3],
                T_inf=row[4],
                h=row[5],
                result=json.loads(row[6])
            )
        return None
    except Exception as e:
        print(f"Fehler beim Laden: {e}")
        return None

def delete_project(name: str) -> bool:
    """Löscht ein Projekt aus der SQLite-Datenbank."""
    try:
        _ensure_db()
        with sqlite3.connect(_DB_PATH) as conn:
            conn.execute("DELETE FROM projects WHERE name = ?", (name,))
        return True
    except Exception as e:
        print(f"Fehler beim Löschen: {e}")
        return False

def get_all_project_names() -> List[str]:
    """Gibt eine Liste aller Projektnamen zurück."""
    try:
        _ensure_db()
        with sqlite3.connect(_DB_PATH) as conn:
            cursor = conn.execute("SELECT name FROM projects")
            names = [row[0] for row in cursor.fetchall()]
        return names
    except Exception as e:
        print(f"Fehler beim Abrufen der Projekte: {e}")
        return []
