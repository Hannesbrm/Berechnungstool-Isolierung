"""
Isolierung_logic.py
Berechnet die stationäre 1D-Temperaturverteilung in einer mehrschichtigen Isolierung
mit konvektiver Wärmeabgabe. Enthält Funktionen zum Speichern/Laden von Projekten in SQLite.
"""
import json
import sqlite3
from dataclasses import dataclass, field, asdict
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
        return Results(q, R_cond, R_conv, temps)

def compute_multilayer(
    thickness_mm_list: List[float],
    k_list: List[float],
    T_left_C: float,
    T_inf_C: float,
    h: float
) -> Dict:
    layers = [Layer(t, k) for t, k in zip(thickness_mm_list, k_list)]
    model = MultiLayerModel(layers, T_left_C, T_inf_C, h)
    res = model.solve()
    return {
        "q": res.q,
        "interface_temperatures": res.interface_temperatures,
        "R_total": sum(res.resistances_cond) + res.resistance_conv
    }

# --- SQLite-Datenbank ---
def _init_db():
    """Erstellt die Datenbank und Tabelle, falls nicht vorhanden."""
    conn = sqlite3.connect("projects.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            name TEXT PRIMARY KEY,
            thicknesses TEXT,
            ks TEXT,
            T_left REAL,
            T_inf REAL,
            h REAL,
            result TEXT
        )
    """)
    conn.commit()
    conn.close()

_init_db()  # Datenbank beim Import initialisieren

def save_project(name: str, thicknesses: List[float], ks: List[float], T_left: float, T_inf: float, h: float, result: Dict) -> bool:
    """Speichert ein Projekt in der SQLite-Datenbank."""
    try:
        conn = sqlite3.connect("projects.db")
        c = conn.cursor()
        c.execute("""
            INSERT OR REPLACE INTO projects
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            name,
            json.dumps(thicknesses),
            json.dumps(ks),
            T_left,
            T_inf,
            h,
            json.dumps(result)
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Fehler beim Speichern: {e}")
        return False

def load_project(name: str) -> Optional[Project]:
    """Lädt ein Projekt aus der SQLite-Datenbank."""
    try:
        conn = sqlite3.connect("projects.db")
        c = conn.cursor()
        c.execute("SELECT * FROM projects WHERE name = ?", (name,))
        row = c.fetchone()
        conn.close()
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
        conn = sqlite3.connect("projects.db")
        c = conn.cursor()
        c.execute("DELETE FROM projects WHERE name = ?", (name,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Fehler beim Löschen: {e}")
        return False

def get_all_project_names() -> List[str]:
    """Gibt eine Liste aller Projektnamen zurück."""
    try:
        conn = sqlite3.connect("projects.db")
        c = conn.cursor()
        c.execute("SELECT name FROM projects")
        names = [row[0] for row in c.fetchall()]
        conn.close()
        return names
    except Exception as e:
        print(f"Fehler beim Abrufen der Projekte: {e}")
        return []
