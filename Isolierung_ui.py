"""Tkinter based user interface for the insulation tool."""

from __future__ import annotations

import csv
import io
import math
import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.figure import Figure

from Isolierung_logic import (
    Material,
    compute_multilayer,
    create_material,
    delete_material,
    delete_project,
    get_all_project_names,
    get_material,
    list_materials,
    load_project,
    save_project,
    update_material,
    upsert_k_points,
)


# ---------------------------------------------------------------------------
# Helper dataclasses
# ---------------------------------------------------------------------------


@dataclass
class _MaterialFormData:
    name: str
    notes: str
    k_const: Optional[float]
    k_points: List[Tuple[float, float]]


# ---------------------------------------------------------------------------
# Material management tab
# ---------------------------------------------------------------------------


class MaterialTab:
    """Encapsulates all widgets and behaviour for the materials tab."""

    def __init__(self, notebook: ttk.Notebook):
        self.root = notebook.winfo_toplevel()
        self.frame = ttk.Frame(notebook)
        notebook.add(self.frame, text="Materialien")

        self.materials: List[Material] = []
        self.material_by_id: Dict[int, Material] = {}
        self.current_material_id: Optional[int] = None

        self._build_layout()
        self.refresh_materials(preserve_selection=False)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_layout(self) -> None:
        main_pane = ttk.PanedWindow(self.frame, orient=tk.HORIZONTAL)
        main_pane.pack(fill="both", expand=True)

        left_frame = ttk.Frame(main_pane, padding=10)
        right_frame = ttk.Frame(main_pane, padding=10)
        main_pane.add(left_frame, weight=1)
        main_pane.add(right_frame, weight=2)

        # Left side: search + treeview + CRUD buttons
        search_frame = ttk.Frame(left_frame)
        search_frame.pack(fill="x", pady=(0, 6))
        ttk.Label(search_frame, text="Suche:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        search_entry.pack(side=tk.LEFT, fill="x", expand=True, padx=(5, 0))
        self.search_var.trace_add("write", lambda *_: self.refresh_materials())

        columns = ("name", "k_const", "points")
        self.tree = ttk.Treeview(
            left_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=18,
        )
        self.tree.heading("name", text="Name")
        self.tree.heading("k_const", text="k_const [W/mK]")
        self.tree.heading("points", text="# Punkte")
        self.tree.column("name", width=180, anchor=tk.W)
        self.tree.column("k_const", width=100, anchor=tk.CENTER)
        self.tree.column("points", width=80, anchor=tk.CENTER)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._on_tree_select())

        btn_frame = ttk.Frame(left_frame)
        btn_frame.pack(fill="x", pady=(6, 0))
        ttk.Button(btn_frame, text="Neu", command=self.prepare_new_material).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(btn_frame, text="Bearbeiten", command=self.edit_selected).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(btn_frame, text="Duplizieren", command=self.duplicate_selected).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(btn_frame, text="Löschen", command=self.delete_selected).pack(
            side=tk.LEFT, padx=2
        )

        # Right side: editor form
        form_frame = ttk.Frame(right_frame)
        form_frame.pack(fill="both", expand=True)

        name_row = ttk.Frame(form_frame)
        name_row.pack(fill="x", pady=2)
        ttk.Label(name_row, text="Name:").pack(side=tk.LEFT)
        self.name_var = tk.StringVar()
        name_entry = ttk.Entry(name_row, textvariable=self.name_var)
        name_entry.pack(side=tk.LEFT, fill="x", expand=True, padx=(5, 0))

        k_row = ttk.Frame(form_frame)
        k_row.pack(fill="x", pady=2)
        ttk.Label(k_row, text="k_const [W/mK]:").pack(side=tk.LEFT)
        self.k_const_var = tk.StringVar()
        k_entry = ttk.Entry(k_row, textvariable=self.k_const_var)
        k_entry.pack(side=tk.LEFT, fill="x", expand=True, padx=(5, 0))
        self.k_const_var.trace_add("write", lambda *_: self.update_plot())

        ttk.Label(form_frame, text="Notizen:").pack(anchor="w")
        self.notes_text = tk.Text(form_frame, height=4)
        self.notes_text.pack(fill="both", expand=False, pady=(0, 6))

        points_frame = ttk.LabelFrame(form_frame, text="(T, k)-Punkte")
        points_frame.pack(fill="both", expand=True)

        self.points_tree = ttk.Treeview(
            points_frame,
            columns=("T", "k"),
            show="headings",
            selectmode="extended",
            height=8,
        )
        self.points_tree.heading("T", text="T [°C]")
        self.points_tree.heading("k", text="k [W/mK]")
        self.points_tree.column("T", width=80, anchor=tk.CENTER)
        self.points_tree.column("k", width=80, anchor=tk.CENTER)
        self.points_tree.pack(fill="both", expand=True, padx=4, pady=4)
        self.points_tree.bind("<Double-1>", self._edit_point_cell)

        point_button_frame = ttk.Frame(points_frame)
        point_button_frame.pack(fill="x", padx=4, pady=(0, 4))
        ttk.Button(point_button_frame, text="Zeile +", command=self.add_point_row).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(point_button_frame, text="Zeile −", command=self.remove_point_rows).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(
            point_button_frame,
            text="Aus Zwischenablage",
            command=self.paste_points,
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(point_button_frame, text="CSV import", command=self.import_csv).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(point_button_frame, text="CSV export", command=self.export_csv).pack(
            side=tk.LEFT, padx=2
        )

        # Plot
        plot_frame = ttk.LabelFrame(form_frame, text="k(T) Verlauf")
        plot_frame.pack(fill="both", expand=True, pady=(6, 0))
        self.plot_figure = Figure(figsize=(5, 3), dpi=100)
        self.plot_ax = self.plot_figure.add_subplot(111)
        self.plot_canvas = FigureCanvasTkAgg(self.plot_figure, master=plot_frame)
        self.plot_canvas.get_tk_widget().pack(fill="both", expand=True)

        # Save/Reset buttons
        action_frame = ttk.Frame(form_frame)
        action_frame.pack(fill="x", pady=6)
        ttk.Button(action_frame, text="Speichern", command=self.save_material).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(action_frame, text="Zurücksetzen", command=self.reset_editor).pack(
            side=tk.LEFT, padx=2
        )

    # ------------------------------------------------------------------
    # Tree handling
    # ------------------------------------------------------------------

    def refresh_materials(self, preserve_selection: bool = True) -> None:
        search_term = self.search_var.get().strip().lower()
        previous_id = self.current_material_id if preserve_selection else None

        try:
            self.materials = list_materials()
        except Exception as exc:  # pragma: no cover - GUI feedback only
            messagebox.showerror("Fehler", f"Materialien konnten nicht geladen werden: {exc}")
            self.materials = []

        self.material_by_id = {mat.id: mat for mat in self.materials if mat.id is not None}

        for item in self.tree.get_children():
            self.tree.delete(item)

        for material in self.materials:
            if search_term and search_term not in material.name.lower():
                continue
            k_const_display = (
                f"{material.k_const:.4g}" if material.k_const is not None else ""
            )
            item_id = str(material.id) if material.id is not None else ""
            self.tree.insert(
                "",
                tk.END,
                iid=item_id or material.name,
                values=(material.name, k_const_display, len(material.k_points)),
            )

        if previous_id is not None and str(previous_id) in self.tree.get_children(""):
            self.tree.selection_set(str(previous_id))
            self.tree.focus(str(previous_id))
        elif self.tree.get_children(""):
            first = self.tree.get_children("")[0]
            self.tree.selection_set(first)
            self.tree.focus(first)
            self._on_tree_select()
        else:
            self.prepare_new_material()

    def _on_tree_select(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        iid = selection[0]
        material = self.material_by_id.get(int(iid)) if iid.isdigit() else None
        if material is None and iid:
            try:
                material = get_material(int(iid))
            except Exception as exc:  # pragma: no cover - GUI feedback only
                messagebox.showerror("Fehler", f"Material konnte nicht geladen werden: {exc}")
                return
        if material is None:
            return
        self.load_material(material)

    # ------------------------------------------------------------------
    # Editor handling
    # ------------------------------------------------------------------

    def load_material(self, material: Material) -> None:
        self.current_material_id = material.id
        self.name_var.set(material.name)
        self.k_const_var.set("" if material.k_const is None else str(material.k_const))
        self.notes_text.delete("1.0", tk.END)
        if material.notes:
            self.notes_text.insert("1.0", material.notes)
        self._fill_points(material.k_points)
        self.update_plot()

    def _fill_points(self, points: Sequence[Tuple[float, float]]) -> None:
        for item in self.points_tree.get_children():
            self.points_tree.delete(item)
        for T, k in points:
            self.points_tree.insert("", tk.END, values=(str(T), str(k)))

    def prepare_new_material(self) -> None:
        self.current_material_id = None
        self.name_var.set("")
        self.k_const_var.set("")
        self.notes_text.delete("1.0", tk.END)
        self._fill_points([])
        self.update_plot()
        self.tree.selection_remove(self.tree.selection())

    def edit_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("Hinweis", "Bitte ein Material auswählen.")
            return
        self._on_tree_select()

    def duplicate_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("Hinweis", "Bitte ein Material auswählen.")
            return
        iid = selection[0]
        if not iid.isdigit():
            messagebox.showerror("Fehler", "Ungültige Auswahl für Duplikation.")
            return
        try:
            material = get_material(int(iid))
        except Exception as exc:  # pragma: no cover - GUI feedback only
            messagebox.showerror("Fehler", f"Material konnte nicht geladen werden: {exc}")
            return

        existing_names = {mat.name for mat in self.materials}
        base_name = f"{material.name} Kopie"
        new_name = base_name
        counter = 2
        while new_name in existing_names:
            new_name = f"{base_name} {counter}"
            counter += 1

        try:
            new_id = create_material(new_name, material.notes, material.k_const)
            if material.k_points:
                upsert_k_points(new_id, material.k_points)
        except Exception as exc:  # pragma: no cover - GUI feedback only
            messagebox.showerror("Fehler", f"Duplizieren fehlgeschlagen: {exc}")
            return

        self.refresh_materials(preserve_selection=False)
        if str(new_id) in self.tree.get_children(""):
            self.tree.selection_set(str(new_id))
            self.tree.focus(str(new_id))
            self._on_tree_select()

    def delete_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("Hinweis", "Bitte ein Material auswählen.")
            return
        iid = selection[0]
        if not iid.isdigit():
            messagebox.showerror("Fehler", "Ungültige Auswahl zum Löschen.")
            return
        if not messagebox.askyesno(
            "Bestätigung", "Soll das Material wirklich gelöscht werden?"
        ):
            return
        try:
            if delete_material(int(iid)):
                messagebox.showinfo("Erfolg", "Material gelöscht.")
            else:
                messagebox.showwarning("Hinweis", "Material konnte nicht gelöscht werden.")
        except Exception as exc:  # pragma: no cover - GUI feedback only
            messagebox.showerror("Fehler", f"Löschen fehlgeschlagen: {exc}")
            return

        self.refresh_materials(preserve_selection=False)
        self.prepare_new_material()

    def reset_editor(self) -> None:
        if self.current_material_id is None:
            self.prepare_new_material()
            return
        material = self.material_by_id.get(self.current_material_id)
        if material is None:
            try:
                material = get_material(self.current_material_id)
            except Exception as exc:  # pragma: no cover - GUI feedback only
                messagebox.showerror("Fehler", f"Material konnte nicht geladen werden: {exc}")
                return
        self.load_material(material)

    # ------------------------------------------------------------------
    # Point table helpers
    # ------------------------------------------------------------------

    def add_point_row(self) -> None:
        self.points_tree.insert("", tk.END, values=("", ""))

    def remove_point_rows(self) -> None:
        selection = self.points_tree.selection()
        for iid in selection:
            self.points_tree.delete(iid)
        self.update_plot()

    def _edit_point_cell(self, event: tk.Event) -> None:  # pragma: no cover - UI only
        region = self.points_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        row_id = self.points_tree.identify_row(event.y)
        column = self.points_tree.identify_column(event.x)
        if not row_id or column not in {"#1", "#2"}:
            return
        x, y, width, height = self.points_tree.bbox(row_id, column)
        value = self.points_tree.set(row_id, column)

        entry = ttk.Entry(self.points_tree)
        entry.insert(0, value)
        entry.select_range(0, tk.END)
        entry.focus()
        entry.place(x=x, y=y, width=width, height=height)

        def commit(event: tk.Event | None = None) -> None:
            new_value = entry.get().strip()
            self.points_tree.set(row_id, column, new_value)
            entry.destroy()
            self.update_plot()

        entry.bind("<Return>", commit)
        entry.bind("<FocusOut>", commit)

    def paste_points(self) -> None:
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            messagebox.showwarning("Hinweis", "Keine Daten in der Zwischenablage.")
            return
        reader = csv.reader(io.StringIO(text), delimiter="\t")
        added = False
        for row in reader:
            if not row:
                continue
            if len(row) == 1:
                parts = list(csv.reader([row[0]], delimiter=","))[0]
            else:
                parts = row
            if len(parts) < 2:
                continue
            self.points_tree.insert("", tk.END, values=(parts[0].strip(), parts[1].strip()))
            added = True
        if added:
            self.update_plot()

    def import_csv(self) -> None:
        file_path = filedialog.askopenfilename(
            title="CSV importieren",
            filetypes=(("CSV", "*.csv"), ("Alle Dateien", "*.*")),
        )
        if not file_path:
            return
        try:
            with open(file_path, newline="", encoding="utf-8") as csvfile:
                reader = csv.reader(csvfile)
                rows = list(reader)
        except Exception as exc:  # pragma: no cover - file IO
            messagebox.showerror("Fehler", f"CSV konnte nicht gelesen werden: {exc}")
            return

        self._fill_points(
            [
                (row[0].strip(), row[1].strip())
                for row in rows
                if len(row) >= 2 and row[0].strip() and row[1].strip()
            ]
        )
        self.update_plot()

    def export_csv(self) -> None:
        file_path = filedialog.asksaveasfilename(
            title="CSV exportieren",
            defaultextension=".csv",
            filetypes=(("CSV", "*.csv"), ("Alle Dateien", "*.*")),
        )
        if not file_path:
            return
        try:
            with open(file_path, "w", newline="", encoding="utf-8") as csvfile:
                writer = csv.writer(csvfile)
                for T_str, k_str in self._iter_point_strings():
                    writer.writerow([T_str, k_str])
        except Exception as exc:  # pragma: no cover - file IO
            messagebox.showerror("Fehler", f"CSV konnte nicht gespeichert werden: {exc}")

    def _iter_point_strings(self) -> Iterable[Tuple[str, str]]:
        for iid in self.points_tree.get_children():
            values = self.points_tree.item(iid, "values")
            if len(values) >= 2:
                yield str(values[0]).strip(), str(values[1]).strip()

    # ------------------------------------------------------------------
    # Saving and validation
    # ------------------------------------------------------------------

    def _collect_form_data(self) -> Optional[_MaterialFormData]:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("Fehler", "Der Name darf nicht leer sein.")
            return None

        notes = self.notes_text.get("1.0", tk.END).strip()
        k_const_str = self.k_const_var.get().strip()
        k_const_value: Optional[float]
        if k_const_str:
            try:
                k_const_value = float(k_const_str)
            except ValueError:
                messagebox.showerror("Fehler", "k_const muss eine Zahl sein.")
                return None
            if k_const_value <= 0:
                messagebox.showerror("Fehler", "k_const muss positiv sein.")
                return None
        else:
            k_const_value = None

        points: List[Tuple[float, float]] = []
        seen_T: set[float] = set()
        for T_str, k_str in self._iter_point_strings():
            if not T_str and not k_str:
                continue
            try:
                T_val = float(T_str)
            except ValueError:
                messagebox.showerror("Fehler", f"Temperatur '{T_str}' ist ungültig.")
                return None
            try:
                k_val = float(k_str)
            except ValueError:
                messagebox.showerror("Fehler", f"k-Wert '{k_str}' ist ungültig.")
                return None
            if k_val <= 0:
                messagebox.showerror("Fehler", "k-Werte müssen positiv sein.")
                return None
            if T_val in seen_T:
                messagebox.showerror("Fehler", "Keine doppelten Temperaturwerte erlaubt.")
                return None
            seen_T.add(T_val)
            points.append((T_val, k_val))

        points.sort(key=lambda item: item[0])

        return _MaterialFormData(name=name, notes=notes, k_const=k_const_value, k_points=points)

    def save_material(self) -> None:
        data = self._collect_form_data()
        if data is None:
            return

        try:
            if self.current_material_id is None:
                new_id = create_material(
                    data.name,
                    data.notes if data.notes else None,
                    data.k_const,
                )
                if data.k_points:
                    upsert_k_points(new_id, data.k_points)
                self.current_material_id = new_id
                messagebox.showinfo("Erfolg", "Material angelegt.")
            else:
                update_kwargs = {
                    "name": data.name,
                    "notes": data.notes,
                }
                if data.k_const is not None:
                    update_kwargs["k_const"] = data.k_const
                update_material(self.current_material_id, **update_kwargs)
                upsert_k_points(self.current_material_id, data.k_points)
                messagebox.showinfo("Erfolg", "Material gespeichert.")
        except ValueError as exc:
            messagebox.showerror("Fehler", str(exc))
            return
        except Exception as exc:  # pragma: no cover - GUI feedback only
            messagebox.showerror("Fehler", f"Speichern fehlgeschlagen: {exc}")
            return

        self.refresh_materials()
        if self.current_material_id is not None:
            iid = str(self.current_material_id)
            if iid in self.tree.get_children(""):
                self.tree.selection_set(iid)
                self.tree.focus(iid)
        self.update_plot()

    # ------------------------------------------------------------------
    # Plot rendering
    # ------------------------------------------------------------------

    def update_plot(self) -> None:
        points: List[Tuple[float, float]] = []
        for T_str, k_str in self._iter_point_strings():
            try:
                T_val = float(T_str)
                k_val = float(k_str)
            except ValueError:
                continue
            if k_val <= 0:
                continue
            points.append((T_val, k_val))
        points.sort(key=lambda item: item[0])

        try:
            k_const_value = float(self.k_const_var.get()) if self.k_const_var.get() else None
        except ValueError:
            k_const_value = None

        self.plot_ax.clear()
        self.plot_ax.set_xlabel("Temperatur [°C]")
        self.plot_ax.set_ylabel("k [W/mK]")
        self.plot_ax.grid(True, linestyle="--", alpha=0.6)

        if points:
            temps, ks = zip(*points)
            self.plot_ax.plot(temps, ks, marker="o", linewidth=2)
        elif k_const_value is not None and not math.isnan(k_const_value):
            temps = [0.0, 100.0]
            ks = [k_const_value, k_const_value]
            self.plot_ax.plot(temps, ks, linestyle="--")
        else:
            self.plot_ax.text(0.5, 0.5, "Keine Daten", ha="center", va="center", transform=self.plot_ax.transAxes)

        self.plot_figure.tight_layout()
        self.plot_canvas.draw_idle()


# ---------------------------------------------------------------------------
# Main application UI
# ---------------------------------------------------------------------------


def run_ui(
    calculate_callback: Optional[
        Callable[[List[float], List[float], float, float, float], dict]
    ] = None
) -> None:
    # --- Hilfsfunktionen ---
    last_inputs: Dict[str, Optional[Tuple]] = {"value": None}
    last_result: Dict[str, Optional[dict]] = {"value": None}

    def _parse_inputs() -> Tuple[List[float], List[float], float, float, float]:
        n = int(entry_layers.get())
        thicknesses = [float(x.strip()) for x in entry_thickness.get().split(",") if x.strip()]
        ks = [float(x.strip()) for x in entry_k.get().split(",") if x.strip()]

        if len(thicknesses) != n or len(ks) != n:
            raise ValueError("Anzahl der Werte muss der Schichtanzahl entsprechen.")
        if any(t <= 0 for t in thicknesses):
            raise ValueError("Alle Dicken müssen > 0 sein.")
        if any(k <= 0 for k in ks):
            raise ValueError("Alle Wärmeleitwerte müssen > 0 sein.")

        T_left = float(entry_T_left.get())
        T_inf = float(entry_T_inf.get())
        h_value = float(entry_h.get())
        return thicknesses, ks, T_left, T_inf, h_value

    def _calculate_with_callback(thicknesses, ks, T_left, T_inf, h_value):
        callback = calculate_callback or compute_multilayer
        return callback(thicknesses, ks, T_left, T_inf, h_value)

    def calculate() -> None:
        try:
            thicknesses, ks, T_left, T_inf, h = _parse_inputs()
            result = _calculate_with_callback(thicknesses, ks, T_left, T_inf, h)
            last_inputs["value"] = (tuple(thicknesses), tuple(ks), T_left, T_inf, h)
            last_result["value"] = result
            display_result(result)
            plot_temperature_profile(
                thicknesses,
                result["interface_temperatures"],
                result.get("temperature_positions_mm"),
                result.get("temperature_labels"),
            )
        except Exception as exc:
            last_result["value"] = None
            messagebox.showerror("Fehler", str(exc))

    def display_result(result: dict) -> None:
        output.delete("1.0", tk.END)
        try:
            output.insert(tk.END, f"Wärmestromdichte q = {result['q']:.3f} W/m²\n")
            output.insert(tk.END, f"Gesamtwiderstand = {result['R_total']:.5f} m²K/W\n\n")
            output.insert(tk.END, "Temperaturen entlang des Pfades (°C):\n")
            labels = result.get("temperature_labels")
            for i, temperature in enumerate(result["interface_temperatures"]):
                label = labels[i] if labels and i < len(labels) else f"Grenzfläche {i}"
                output.insert(tk.END, f"  {label}: {temperature:.2f}\n")
        except Exception as exc:
            output.insert(tk.END, f"Fehler beim Anzeigen des Ergebnisses: {exc}\n")

    def save_current_project(name_entry: tk.Entry) -> Tuple[bool, str]:
        name = name_entry.get().strip()
        if not name:
            return False, "Bitte einen Projektnamen eingeben."

        try:
            thicknesses, ks, T_left, T_inf, h = _parse_inputs()
        except ValueError as ve:
            return False, f"Ungültige Eingabe: {ve}"
        except Exception as exc:
            return False, str(exc)

        inputs_signature = (tuple(thicknesses), tuple(ks), T_left, T_inf, h)

        if last_inputs["value"] == inputs_signature and last_result.get("value"):
            result = last_result["value"]
        else:
            try:
                result = _calculate_with_callback(thicknesses, ks, T_left, T_inf, h)
            except Exception as exc:
                last_result["value"] = None
                return False, str(exc)

            display_result(result)
            try:
                plot_temperature_profile(
                    thicknesses,
                    result["interface_temperatures"],
                    result.get("temperature_positions_mm"),
                    result.get("temperature_labels"),
                )
            except Exception as plot_error:
                last_result["value"] = None
                return False, str(plot_error)

            last_inputs["value"] = inputs_signature
            last_result["value"] = result

        try:
            save_project(
                name,
                thicknesses,
                ks,
                T_left,
                T_inf,
                h,
                result,
            )
        except Exception as exc:
            return False, str(exc)

        update_project_list()
        return True, f"Projekt '{name}' gespeichert."

    def load_selected_project() -> None:
        try:
            selection = project_listbox.curselection()
            if not selection:
                return
            name = project_listbox.get(selection[0])
        except Exception:
            return

        project = load_project(name)
        if project:
            entry_layers.delete(0, tk.END)
            entry_layers.insert(0, str(len(project.thicknesses)))
            entry_thickness.delete(0, tk.END)
            entry_thickness.insert(0, ", ".join(map(str, project.thicknesses)))
            entry_k.delete(0, tk.END)
            entry_k.insert(0, ", ".join(map(str, project.ks)))
            entry_T_left.delete(0, tk.END)
            entry_T_left.insert(0, str(project.T_left))
            entry_T_inf.delete(0, tk.END)
            entry_T_inf.insert(0, str(project.T_inf))
            entry_h.delete(0, tk.END)
            entry_h.insert(0, str(project.h))

            if project.result:
                last_inputs["value"] = (
                    tuple(project.thicknesses),
                    tuple(project.ks),
                    project.T_left,
                    project.T_inf,
                    project.h,
                )
                last_result["value"] = project.result
                display_result(project.result)
                if "interface_temperatures" in project.result and project.result[
                    "interface_temperatures"
                ]:
                    try:
                        plot_temperature_profile(
                            project.thicknesses,
                            project.result["interface_temperatures"],
                            project.result.get("temperature_positions_mm"),
                            project.result.get("temperature_labels"),
                        )
                    except Exception as exc:
                        messagebox.showerror("Fehler", str(exc))
            else:
                last_inputs["value"] = None
                last_result["value"] = None
                output.delete("1.0", tk.END)
                output.insert(tk.END, "Kein Ergebnis im Projekt gespeichert.\n")

    def delete_selected_project() -> None:
        try:
            selection = project_listbox.curselection()
            if not selection:
                return
            name = project_listbox.get(selection[0])
        except Exception:
            return

        if delete_project(name):
            messagebox.showinfo("Erfolg", f"Projekt '{name}' gelöscht.")
            update_project_list()
        else:
            messagebox.showerror("Fehler", "Löschen fehlgeschlagen.")

    def update_project_list() -> None:
        project_listbox.delete(0, tk.END)
        for name in get_all_project_names():
            project_listbox.insert(tk.END, name)

    def plot_temperature_profile(
        thicknesses: Sequence[float],
        temperatures: Sequence[float],
        positions_mm: Optional[Sequence[float]] = None,
        labels: Optional[Sequence[str]] = None,
    ) -> None:
        if positions_mm is None:
            pos = [0.0]
            for thickness in thicknesses:
                pos.append(pos[-1] + thickness)
            if len(temperatures) > len(pos):
                pos.append(pos[-1])
            positions = pos
        else:
            positions = list(positions_mm)

        if len(positions) != len(temperatures):
            raise ValueError("Positions- und Temperaturlisten müssen gleich lang sein.")

        colors = ["#e81919", "#fce6e6"]
        cmap = LinearSegmentedColormap.from_list("custom_cmap", colors, N=256)

        fig = Figure(figsize=(6, 4), dpi=100)
        ax = fig.add_subplot(111)
        ax.plot(positions, temperatures, linewidth=2, marker="o")

        x_pos = 0.0
        for index, thickness in enumerate(thicknesses):
            color_value = index / (len(thicknesses) - 1) if len(thicknesses) > 1 else 0.5
            color = cmap(color_value)
            ax.axvspan(x_pos, x_pos + thickness, color=color, alpha=0.4)
            x_pos += thickness

        last_index = len(temperatures) - 1
        for idx, (x_val, temperature) in enumerate(zip(positions, temperatures)):
            label = labels[idx] if labels and idx < len(labels) else ""
            text = f"{temperature:.0f}°C"
            if label and (idx == 0 or idx == last_index):
                text = f"{label}\n{text}"
            ax.text(x_val, temperature, text, ha="center", va="bottom", fontsize=8)

        ax.set_xlabel("Dicke [mm]")
        ax.set_ylabel("Temperatur [°C]")
        ax.set_title("Temperaturverlauf durch die Isolierung")
        ax.grid(True, linestyle="--", alpha=0.6)
        fig.tight_layout()

        for widget in frame_plot.winfo_children():
            widget.destroy()
        canvas = FigureCanvasTkAgg(fig, master=frame_plot)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

    def save_dialog(parent: tk.Misc) -> None:
        dialog = tk.Toplevel(parent)
        dialog.title("Projekt speichern")

        ttk.Label(dialog, text="Projektname:").pack(pady=5)
        name_entry = ttk.Entry(dialog)
        name_entry.pack(pady=5)
        name_entry.focus_set()

        status_var = tk.StringVar(value="")
        status_label = ttk.Label(dialog, textvariable=status_var, foreground="red")
        status_label.pack(pady=(0, 5))

        def on_save() -> None:
            success, message = save_current_project(name_entry)
            status_var.set(message)
            status_label.configure(foreground="green" if success else "red")
            if success:
                dialog.after(1500, dialog.destroy)

        ttk.Button(dialog, text="Speichern", command=on_save).pack(pady=5)
        ttk.Button(dialog, text="Abbrechen", command=dialog.destroy).pack(pady=(0, 5))

    # --- Hauptelemente der UI ---
    root = tk.Tk()
    root.title("Heatrix - Isolierung - Temperaturberechnung")

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)

    # Tab 1: Berechnung
    tab1 = ttk.Frame(notebook)
    notebook.add(tab1, text="Berechnung")

    ttk.Label(tab1, text="Anzahl Schichten:").grid(row=0, column=0, sticky="w")
    entry_layers = ttk.Entry(tab1)
    entry_layers.grid(row=0, column=1)

    ttk.Label(tab1, text="Dicken [mm] (kommagetrennt):").grid(row=1, column=0, sticky="w")
    entry_thickness = ttk.Entry(tab1, width=40)
    entry_thickness.grid(row=1, column=1)

    ttk.Label(tab1, text="Wärmeleitwerte k [W/mK] (kommagetrennt):").grid(
        row=2, column=0, sticky="w"
    )
    entry_k = ttk.Entry(tab1, width=40)
    entry_k.grid(row=2, column=1)

    ttk.Label(tab1, text="T_links [°C]:").grid(row=3, column=0, sticky="w")
    entry_T_left = ttk.Entry(tab1)
    entry_T_left.grid(row=3, column=1)

    ttk.Label(tab1, text="T_∞ [°C]:").grid(row=4, column=0, sticky="w")
    entry_T_inf = ttk.Entry(tab1)
    entry_T_inf.grid(row=4, column=1)

    ttk.Label(tab1, text="h [W/m²K]:").grid(row=5, column=0, sticky="w")
    entry_h = ttk.Entry(tab1)
    entry_h.grid(row=5, column=1)

    ttk.Button(tab1, text="Berechnen", command=calculate).grid(row=6, column=0, pady=5)
    ttk.Button(tab1, text="Speichern", command=lambda: save_dialog(tab1)).grid(
        row=6, column=1, pady=5
    )

    output = tk.Text(tab1, height=10, width=60)
    output.grid(row=7, column=0, columnspan=2, pady=5)

    frame_plot = ttk.Frame(tab1, width=600, height=400)
    frame_plot.grid(row=8, column=0, columnspan=2, sticky="nsew", pady=10)

    tab1.grid_columnconfigure(1, weight=1)
    tab1.grid_rowconfigure(8, weight=1)

    # Tab 2: Projekte
    tab2 = ttk.Frame(notebook)
    notebook.add(tab2, text="Projekte")

    project_listbox = tk.Listbox(tab2, width=40, height=10)
    project_listbox.pack(pady=10, fill="both", expand=True)
    update_project_list()

    button_frame = ttk.Frame(tab2)
    button_frame.pack(pady=5)

    ttk.Button(button_frame, text="Laden", command=load_selected_project).pack(
        side=tk.LEFT, padx=5
    )
    ttk.Button(button_frame, text="Löschen", command=delete_selected_project).pack(
        side=tk.LEFT, padx=5
    )

    # Tab 3: Materialien
    MaterialTab(notebook)

    root.mainloop()

