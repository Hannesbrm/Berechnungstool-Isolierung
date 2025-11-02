"""Tkinter based user interface for the insulation tool."""

from __future__ import annotations

import csv
import io
import math
import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, messagebox, ttk
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.colors import LinearSegmentedColormap

from matplotlib import cm
from matplotlib.patches import Patch
from matplotlib.figure import Figure

from Isolierung_logic import (
    Layer,
    Material,
    Project,
    compute_multilayer_layers,
    create_material,
    delete_material,
    get_all_project_names,
    get_material,
    list_materials,
    load_project,
    save_project,
    solve_multilayer_kT,
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



def run_ui() -> None:
    class CalculationTab:
        """Encapsulates the interactive calculation tab."""

        def __init__(self, notebook: ttk.Notebook):
            self.root = notebook.winfo_toplevel()
            self.frame = ttk.Frame(notebook)
            notebook.add(self.frame, text="Berechnung")

            self.layer_rows: List[Dict[str, object]] = []
            self.materials: List[Material] = []
            self.material_lookup: Dict[int, Material] = {}
            self.material_names: List[str] = []
            self.mode_display: Dict[str, str] = {"material": "Material", "custom": "Custom"}
            self.mode_internal: Dict[str, str] = {v: k for k, v in self.mode_display.items()}
            self.selected_index: Optional[int] = None
            self.form_updating = False
            self.form_enabled = False
            self.tree_items: List[str] = []

            self._build_layout()
            self.refresh_material_options()
            self.refresh_tree()

        # ------------------------------------------------------------------
        # UI setup
        # ------------------------------------------------------------------

        def _build_layout(self) -> None:
            self.frame.columnconfigure(0, weight=3)
            self.frame.columnconfigure(1, weight=2)
            self.frame.rowconfigure(0, weight=1)
            self.frame.rowconfigure(1, weight=1)

            layers_frame = ttk.LabelFrame(self.frame, text="Schichten")
            layers_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

            tree_container = ttk.Frame(layers_frame)
            tree_container.pack(fill="both", expand=True)

            columns = ("order", "mode", "material", "use_kT", "k_const", "thickness", "note")
            self.tree = ttk.Treeview(
                tree_container,
                columns=columns,
                show="headings",
                selectmode="browse",
                height=12,
            )
            self.tree.heading("order", text="#")
            self.tree.heading("mode", text="Modus")
            self.tree.heading("material", text="Material")
            self.tree.heading("use_kT", text="k(T) nutzen")
            self.tree.heading("k_const", text="k_const [W/mK]")
            self.tree.heading("thickness", text="Dicke [mm]")
            self.tree.heading("note", text="Notiz")

            self.tree.column("order", width=40, anchor=tk.CENTER)
            self.tree.column("mode", width=90, anchor=tk.CENTER)
            self.tree.column("material", width=140, anchor=tk.W)
            self.tree.column("use_kT", width=90, anchor=tk.CENTER)
            self.tree.column("k_const", width=110, anchor=tk.CENTER)
            self.tree.column("thickness", width=100, anchor=tk.CENTER)
            self.tree.column("note", width=180, anchor=tk.W)

            self.tree.pack(side=tk.LEFT, fill="both", expand=True)

            scrollbar = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree.yview)
            scrollbar.pack(side=tk.RIGHT, fill="y")
            self.tree.configure(yscrollcommand=scrollbar.set)
            self.tree.tag_configure("error", background="#f8d7da")
            self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

            layer_button_frame = ttk.Frame(layers_frame)
            layer_button_frame.pack(fill="x", pady=(6, 0))

            self.btn_add = ttk.Button(layer_button_frame, text="+ Hinzufügen", command=self.add_layer)
            self.btn_add.pack(side=tk.LEFT, padx=2)

            self.btn_remove = ttk.Button(layer_button_frame, text="- Entfernen", command=self.remove_layer)
            self.btn_remove.pack(side=tk.LEFT, padx=2)

            self.btn_up = ttk.Button(layer_button_frame, text="↑", width=3, command=lambda: self.move_layer(-1))
            self.btn_up.pack(side=tk.LEFT, padx=2)

            self.btn_down = ttk.Button(layer_button_frame, text="↓", width=3, command=lambda: self.move_layer(1))
            self.btn_down.pack(side=tk.LEFT, padx=2)

            self.btn_clear = ttk.Button(layer_button_frame, text="Leeren", command=self.clear_layers)
            self.btn_clear.pack(side=tk.LEFT, padx=8)

            control_frame = ttk.Frame(self.frame)
            control_frame.grid(row=0, column=1, sticky="nsew", padx=(0, 10), pady=10)
            control_frame.columnconfigure(0, weight=1)
            control_frame.rowconfigure(3, weight=1)

            editor_frame = ttk.LabelFrame(control_frame, text="Schicht bearbeiten")
            editor_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
            editor_frame.columnconfigure(1, weight=1)

            ttk.Label(editor_frame, text="Modus:").grid(row=0, column=0, sticky="w", padx=4, pady=2)
            self.mode_var = tk.StringVar()
            self.mode_combo = ttk.Combobox(
                editor_frame,
                textvariable=self.mode_var,
                values=list(self.mode_display.values()),
                state="disabled",
            )
            self.mode_combo.grid(row=0, column=1, sticky="ew", padx=4, pady=2)
            self.mode_combo.bind("<<ComboboxSelected>>", lambda _event: self._on_mode_change())

            ttk.Label(editor_frame, text="Material:").grid(row=1, column=0, sticky="w", padx=4, pady=2)
            self.material_var = tk.StringVar()
            self.material_combo = ttk.Combobox(
                editor_frame,
                textvariable=self.material_var,
                state="disabled",
            )
            self.material_combo.grid(row=1, column=1, sticky="ew", padx=4, pady=2)
            self.material_combo.bind("<<ComboboxSelected>>", lambda _event: self._on_material_selected())

            self.use_kT_var = tk.BooleanVar(value=False)
            self.use_kT_check = ttk.Checkbutton(
                editor_frame,
                text="k(T) nutzen",
                variable=self.use_kT_var,
                command=self._on_use_kT_toggle,
            )
            self.use_kT_check.grid(row=2, column=0, columnspan=2, sticky="w", padx=4, pady=2)

            ttk.Label(editor_frame, text="k_const [W/mK]:").grid(row=3, column=0, sticky="w", padx=4, pady=2)
            self.k_const_var = tk.StringVar()
            self.k_const_entry = ttk.Entry(editor_frame, textvariable=self.k_const_var, state="disabled")
            self.k_const_entry.grid(row=3, column=1, sticky="ew", padx=4, pady=2)
            self.k_const_var.trace_add("write", lambda *_: self._on_value_change("k_const"))

            ttk.Label(editor_frame, text="Dicke [mm]:").grid(row=4, column=0, sticky="w", padx=4, pady=2)
            self.thickness_var = tk.StringVar()
            self.thickness_entry = ttk.Entry(editor_frame, textvariable=self.thickness_var, state="disabled")
            self.thickness_entry.grid(row=4, column=1, sticky="ew", padx=4, pady=2)
            self.thickness_var.trace_add("write", lambda *_: self._on_value_change("thickness"))

            ttk.Label(editor_frame, text="Notiz:").grid(row=5, column=0, sticky="w", padx=4, pady=2)
            self.note_var = tk.StringVar()
            self.note_entry = ttk.Entry(editor_frame, textvariable=self.note_var, state="disabled")
            self.note_entry.grid(row=5, column=1, sticky="ew", padx=4, pady=2)
            self.note_var.trace_add("write", lambda *_: self._on_value_change("note"))

            boundary_frame = ttk.LabelFrame(control_frame, text="Randbedingungen")
            boundary_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
            boundary_frame.columnconfigure(1, weight=1)

            self.T_left_var = tk.StringVar()
            ttk.Label(boundary_frame, text="T_links [°C]:").grid(row=0, column=0, sticky="w", padx=4, pady=2)
            ttk.Entry(boundary_frame, textvariable=self.T_left_var).grid(row=0, column=1, sticky="ew", padx=4, pady=2)

            self.T_inf_var = tk.StringVar()
            ttk.Label(boundary_frame, text="T_∞ [°C]:").grid(row=1, column=0, sticky="w", padx=4, pady=2)
            ttk.Entry(boundary_frame, textvariable=self.T_inf_var).grid(row=1, column=1, sticky="ew", padx=4, pady=2)

            self.h_var = tk.StringVar()
            ttk.Label(boundary_frame, text="h [W/m²K]:").grid(row=2, column=0, sticky="w", padx=4, pady=2)
            ttk.Entry(boundary_frame, textvariable=self.h_var).grid(row=2, column=1, sticky="ew", padx=4, pady=2)

            action_frame = ttk.Frame(control_frame)
            action_frame.grid(row=2, column=0, sticky="ew", pady=(0, 10))

            self.btn_calculate = ttk.Button(action_frame, text="Berechnen", command=self.calculate)
            self.btn_calculate.pack(side=tk.LEFT, padx=4)

            ttk.Button(action_frame, text="Aus Projekt laden", command=self.open_load_dialog).pack(side=tk.LEFT, padx=4)
            ttk.Button(action_frame, text="Als Projekt speichern", command=self.open_save_dialog).pack(side=tk.LEFT, padx=4)

            self.output_text = tk.Text(control_frame, height=12, wrap="word")
            self.output_text.grid(row=3, column=0, sticky="nsew")
            self.output_text.configure(state="disabled")

            self.plot_frame = ttk.Frame(self.frame)
            self.plot_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=10, pady=(0, 10))

            self.plot_figure = Figure(figsize=(6, 3))
            self.plot_ax = self.plot_figure.add_subplot(111)
            self.plot_ax.set_xlabel("x [m]")
            self.plot_ax.set_ylabel("T [°C]")
            self.plot_ax.set_title("Temperaturprofil")
            self.plot_ax.grid(True, linestyle="--", alpha=0.4)

            self.plot_canvas = FigureCanvasTkAgg(self.plot_figure, master=self.plot_frame)
            self.plot_canvas.draw()
            self.plot_canvas.get_tk_widget().pack(fill="both", expand=True)

            self._update_button_states()

        # ------------------------------------------------------------------
        # Layer management
        # ------------------------------------------------------------------

        def refresh_material_options(self) -> None:
            try:
                materials = list_materials()
            except Exception as exc:
                messagebox.showerror("Fehler", f"Materialien konnten nicht geladen werden: {exc}")
                materials = []

            self.materials = materials
            self.material_lookup = {m.id: m for m in materials if m.id is not None}
            self.material_names = [m.name for m in materials]
            self.material_combo.configure(values=self.material_names)

            for row in self.layer_rows:
                material_id = row.get("material_id")
                if isinstance(material_id, int) and material_id in self.material_lookup:
                    row["material_name"] = self.material_lookup[material_id].name

            for index in range(len(self.layer_rows)):
                self._update_tree_row(index)

        def add_layer(self) -> None:
            if not self.materials:
                row: Dict[str, object] = {
                    "mode": "custom",
                    "material_id": None,
                    "material_name": "",
                    "use_kT": False,
                    "k_const": "",
                    "thickness": "10",
                    "note": "",
                }
            else:
                material = self.materials[0]
                row = {
                    "mode": "material",
                    "material_id": material.id,
                    "material_name": material.name,
                    "use_kT": False,
                    "k_const": "",
                    "thickness": "10",
                    "note": "",
                }

            self.layer_rows.append(row)
            self.refresh_tree(select_index=len(self.layer_rows) - 1)

        def remove_layer(self) -> None:
            if self.selected_index is None:
                return
            del self.layer_rows[self.selected_index]
            new_index = None
            if self.layer_rows:
                new_index = min(self.selected_index, len(self.layer_rows) - 1)
            self.refresh_tree(select_index=new_index)

        def move_layer(self, direction: int) -> None:
            if self.selected_index is None:
                return
            new_index = self.selected_index + direction
            if not (0 <= new_index < len(self.layer_rows)):
                return
            self.layer_rows[self.selected_index], self.layer_rows[new_index] = (
                self.layer_rows[new_index],
                self.layer_rows[self.selected_index],
            )
            self.refresh_tree(select_index=new_index)

        def clear_layers(self) -> None:
            self.layer_rows.clear()
            self.refresh_tree(select_index=None)

        # ------------------------------------------------------------------
        # Tree and form synchronisation
        # ------------------------------------------------------------------

        def refresh_tree(self, select_index: Optional[int] = None) -> None:
            self.tree.delete(*self.tree.get_children())
            self.tree_items = []

            for index in range(len(self.layer_rows)):
                item = self.tree.insert("", tk.END, values=self._row_to_tree_values(index))
                self.tree_items.append(item)

            self._clear_error_highlights()

            if select_index is None and self.layer_rows:
                select_index = min(self.selected_index or 0, len(self.layer_rows) - 1)

            if select_index is not None and 0 <= select_index < len(self.layer_rows):
                item_id = self.tree_items[select_index]
                self.tree.selection_set(item_id)
                self.tree.focus(item_id)
                self.selected_index = select_index
                self._load_row_into_form(select_index)
            else:
                self.tree.selection_remove(self.tree.selection())
                self.selected_index = None
                self._load_row_into_form(None)

            self._update_button_states()

        def _update_tree_row(self, index: int) -> None:
            if 0 <= index < len(self.tree_items):
                self.tree.item(self.tree_items[index], values=self._row_to_tree_values(index))

        def _row_to_tree_values(self, index: int) -> Tuple[str, ...]:
            row = self.layer_rows[index]
            mode = str(row.get("mode", "material"))
            material_text = row.get("material_name", "") if mode == "material" else ""
            use_kT_text = "Ja" if row.get("use_kT") else "Nein"
            k_const_text = row.get("k_const", "") if mode == "custom" else ""
            thickness_text = row.get("thickness", "")
            note_text = row.get("note", "")
            return (
                str(index + 1),
                self.mode_display.get(mode, mode),
                material_text,
                use_kT_text,
                k_const_text,
                thickness_text,
                note_text,
            )

        def _on_tree_select(self, _event: tk.Event) -> None:
            selection = self.tree.selection()
            if not selection:
                self.selected_index = None
                self._load_row_into_form(None)
                self._update_button_states()
                return
            item = selection[0]
            index = self.tree.index(item)
            self.selected_index = index
            self._load_row_into_form(index)
            self._update_button_states()

        def _load_row_into_form(self, index: Optional[int]) -> None:
            self.form_updating = True
            if index is None:
                self.form_enabled = False
                self.mode_var.set("")
                self.material_var.set("")
                self.use_kT_var.set(False)
                self.k_const_var.set("")
                self.thickness_var.set("")
                self.note_var.set("")
            else:
                row = self.layer_rows[index]
                self.form_enabled = True
                mode_text = self.mode_display.get(str(row.get("mode", "material")), "Material")
                self.mode_var.set(mode_text)
                self.material_var.set(row.get("material_name", ""))
                self.use_kT_var.set(bool(row.get("use_kT", False)))
                self.k_const_var.set(str(row.get("k_const", "")))
                self.thickness_var.set(str(row.get("thickness", "")))
                self.note_var.set(str(row.get("note", "")))

            self.form_updating = False
            self._update_form_state()

        def _update_form_state(self) -> None:
            if not self.form_enabled:
                self.mode_combo.configure(state="disabled")
                self.material_combo.configure(state="disabled")
                self.use_kT_check.state(["disabled"])
                self.k_const_entry.configure(state="disabled")
                self.thickness_entry.configure(state="disabled")
                self.note_entry.configure(state="disabled")
                return

            mode_text = self.mode_var.get()
            mode = self.mode_internal.get(mode_text, "material")

            self.mode_combo.configure(state="readonly")
            self.thickness_entry.configure(state="normal")
            self.note_entry.configure(state="normal")

            if mode == "material":
                state = "readonly" if self.material_names else "disabled"
                self.material_combo.configure(state=state)
                self.use_kT_check.state(["!disabled"])
                self.k_const_entry.configure(state="disabled")
            else:
                self.material_combo.configure(state="disabled")
                self.use_kT_check.state(["disabled"])
                self.k_const_entry.configure(state="normal")

        def _on_mode_change(self) -> None:
            if self.form_updating or self.selected_index is None:
                return
            mode_text = self.mode_var.get()
            mode = self.mode_internal.get(mode_text)
            if mode is None:
                return
            row = self.layer_rows[self.selected_index]
            row["mode"] = mode
            if mode == "material":
                if not isinstance(row.get("material_id"), int) and self.materials:
                    material = self.materials[0]
                    row["material_id"] = material.id
                    row["material_name"] = material.name
                self.k_const_var.set("")
                row["k_const"] = ""
            else:
                row["material_id"] = None
                row["material_name"] = ""
                row["use_kT"] = False
                self.use_kT_var.set(False)

            self._update_form_state()
            self._clear_error_highlights()
            self._update_tree_row(self.selected_index)

        def _on_material_selected(self) -> None:
            if self.selected_index is None or self.form_updating:
                return
            name = self.material_var.get()
            material = next((m for m in self.materials if m.name == name), None)
            if material is None:
                return
            row = self.layer_rows[self.selected_index]
            row["mode"] = "material"
            row["material_id"] = material.id
            row["material_name"] = material.name
            if self.mode_var.get() != self.mode_display["material"]:
                self.mode_var.set(self.mode_display["material"])
            self._update_form_state()
            self._clear_error_highlights()
            self._update_tree_row(self.selected_index)

        def _on_use_kT_toggle(self) -> None:
            if self.selected_index is None or self.form_updating:
                return
            row = self.layer_rows[self.selected_index]
            row["use_kT"] = bool(self.use_kT_var.get())
            self._clear_error_highlights()
            self._update_tree_row(self.selected_index)

        def _on_value_change(self, field: str) -> None:
            if self.selected_index is None or self.form_updating:
                return
            if field == "k_const":
                value = self.k_const_var.get().strip()
            elif field == "thickness":
                value = self.thickness_var.get().strip()
            elif field == "note":
                value = self.note_var.get()
            else:
                return
            self.layer_rows[self.selected_index][field] = value
            self._clear_error_highlights()
            self._update_tree_row(self.selected_index)

        def _update_button_states(self) -> None:
            has_selection = self.selected_index is not None
            has_rows = bool(self.layer_rows)
            self.btn_remove.configure(state="normal" if has_selection else "disabled")
            self.btn_up.configure(
                state="normal" if has_selection and self.selected_index and self.selected_index > 0 else "disabled"
            )
            self.btn_down.configure(
                state="normal"
                if has_selection and self.selected_index is not None and self.selected_index < len(self.layer_rows) - 1
                else "disabled"
            )
            self.btn_clear.configure(state="normal" if has_rows else "disabled")

        def _clear_error_highlights(self) -> None:
            for item in self.tree_items:
                tags = set(self.tree.item(item, "tags"))
                if "error" in tags:
                    tags.remove("error")
                    self.tree.item(item, tags=tuple(tags))

        def _highlight_errors(self, indices: Sequence[int]) -> None:
            for index in indices:
                if 0 <= index < len(self.tree_items):
                    tags = set(self.tree.item(self.tree_items[index], "tags"))
                    tags.add("error")
                    self.tree.item(self.tree_items[index], tags=tuple(tags))

        # ------------------------------------------------------------------
        # Validation and calculation
        # ------------------------------------------------------------------

        def _parse_float(self, value: str, field: str) -> float:
            try:
                return float(value.replace(",", "."))
            except ValueError as exc:
                raise ValueError(f"{field} muss eine Zahl sein.") from exc

        def _parse_boundary_conditions(self) -> Tuple[float, float, float]:
            T_left = self._parse_float(self.T_left_var.get().strip(), "T_links")
            T_inf = self._parse_float(self.T_inf_var.get().strip(), "T_∞")
            h_value = self._parse_float(self.h_var.get().strip(), "h")
            if h_value <= 0:
                raise ValueError("h muss größer als 0 sein.")
            return T_left, T_inf, h_value

        def _collect_layers(self) -> Tuple[List[Layer], List[str], List[int]]:
            if not self.layer_rows:
                return [], ["Mindestens eine Schicht ist erforderlich."], []

            layers: List[Layer] = []
            errors: List[str] = []
            error_indices: List[int] = []

            for index, row in enumerate(self.layer_rows):
                mode = str(row.get("mode", "material"))

                thickness_raw = str(row.get("thickness", "")).strip()
                if not thickness_raw:
                    errors.append(f"Zeile {index + 1}: Dicke muss angegeben werden.")
                    error_indices.append(index)
                    continue
                try:
                    thickness = self._parse_float(thickness_raw, "Dicke")
                except ValueError as exc:
                    errors.append(f"Zeile {index + 1}: {exc}")
                    error_indices.append(index)
                    continue
                if thickness <= 0:
                    errors.append(f"Zeile {index + 1}: Dicke muss größer als 0 sein.")
                    error_indices.append(index)
                    continue

                note = (str(row.get("note", "")).strip() or None)

                if mode == "material":
                    material_id = row.get("material_id")
                    if not isinstance(material_id, int):
                        errors.append(f"Zeile {index + 1}: Bitte ein Material auswählen.")
                        error_indices.append(index)
                        continue
                    material = self.material_lookup.get(material_id)
                    if material is None:
                        try:
                            material = get_material(material_id)
                            self.material_lookup[material_id] = material
                        except Exception:
                            errors.append(
                                f"Zeile {index + 1}: Material mit ID {material_id} ist nicht verfügbar."
                            )
                            error_indices.append(index)
                            continue
                    row["material_name"] = material.name
                    use_kT = bool(row.get("use_kT", False))
                    if use_kT and not material.k_points and material.k_const is None:
                        errors.append(
                            f"Zeile {index + 1}: Material '{material.name}' enthält keine k(T)-Daten."
                        )
                        error_indices.append(index)
                        continue
                    if not use_kT and material.k_const is None:
                        errors.append(
                            f"Zeile {index + 1}: Material '{material.name}' hat keinen konstanten k-Wert."
                        )
                        error_indices.append(index)
                        continue
                    try:
                        layer_obj = Layer(
                            thickness_mm=thickness,
                            mode="material",
                            material_id=material_id,
                            use_kT=use_kT,
                            k_const=None,
                            note=note,
                        )
                    except ValueError as exc:
                        errors.append(f"Zeile {index + 1}: {exc}")
                        error_indices.append(index)
                        continue
                    layers.append(layer_obj)
                else:
                    if row.get("use_kT"):
                        errors.append(f"Zeile {index + 1}: Custom-Schichten unterstützen kein k(T).")
                        error_indices.append(index)
                        continue
                    k_const_raw = str(row.get("k_const", "")).strip()
                    if not k_const_raw:
                        errors.append(f"Zeile {index + 1}: k_const muss angegeben werden.")
                        error_indices.append(index)
                        continue
                    try:
                        k_const = self._parse_float(k_const_raw, "k_const")
                    except ValueError as exc:
                        errors.append(f"Zeile {index + 1}: {exc}")
                        error_indices.append(index)
                        continue
                    if k_const <= 0:
                        errors.append(f"Zeile {index + 1}: k_const muss größer als 0 sein.")
                        error_indices.append(index)
                        continue
                    try:
                        layer_obj = Layer(
                            thickness_mm=thickness,
                            mode="custom",
                            material_id=None,
                            use_kT=False,
                            k_const=k_const,
                            note=note,
                        )
                    except ValueError as exc:
                        errors.append(f"Zeile {index + 1}: {exc}")
                        error_indices.append(index)
                        continue
                    layers.append(layer_obj)

            return layers, errors, error_indices

        def calculate(self) -> None:
            self._clear_error_highlights()
            try:
                T_left, T_inf, h_value = self._parse_boundary_conditions()
            except ValueError as exc:
                messagebox.showerror("Validierungsfehler", str(exc))
                return

            self.refresh_material_options()
            layers, errors, error_indices = self._collect_layers()
            if errors:
                self._highlight_errors(error_indices)
                messagebox.showerror("Validierungsfehler", "\n".join(errors))
                return

            try:
                if any(layer.use_kT for layer in layers):
                    result = solve_multilayer_kT(layers, T_left, T_inf, h_value)
                else:
                    result = compute_multilayer_layers(layers, T_left, T_inf, h_value)
            except Exception as exc:
                messagebox.showerror("Berechnungsfehler", str(exc))
                return

            self._display_result(layers, result, T_inf)
            self._update_plot(layers, result)

        def _display_result(
            self, layers: Sequence[Layer], result: Dict[str, object], T_inf: float
        ) -> None:
            lines: List[str] = []
            q_value = result.get("q_W_m2")
            if isinstance(q_value, (int, float)):
                lines.append(f"Wärmestromdichte q = {q_value:.3f} W/m²")

            interface_T = result.get("interface_T_C")
            if isinstance(interface_T, Sequence):
                lines.append("")
                lines.append("Grenzflächentemperaturen:")
                for idx, temp in enumerate(interface_T):
                    if not isinstance(temp, (int, float)):
                        continue
                    if idx == 0:
                        label = "T_links"
                    elif idx == len(interface_T) - 1:
                        label = "Oberfläche"
                    else:
                        label = self._layer_label(layers[idx - 1], idx - 1)
                    lines.append(f"  {label}: {temp:.2f} °C")

            lines.append(f"T_∞: {T_inf:.2f} °C")
            self._set_output_text("\n".join(lines))

        def _layer_label(self, layer: Layer, index: int) -> str:
            note = (layer.note or "").strip()
            if note:
                return note
            if layer.mode == "material" and layer.material_id is not None:
                material = self.material_lookup.get(layer.material_id)
                if material:
                    return material.name
                try:
                    material = get_material(layer.material_id)
                    self.material_lookup[layer.material_id] = material
                    return material.name
                except Exception:
                    return f"Material {layer.material_id}"
            return f"Schicht {index + 1}"

        def _update_plot(self, layers: Sequence[Layer], result: Dict[str, object]) -> None:
            x_values = result.get("x_m")
            temps = result.get("T_profile_C")
            if not isinstance(x_values, Sequence) or not isinstance(temps, Sequence):
                return

            self.plot_ax.clear()
            self.plot_ax.set_xlabel("x [m]")
            self.plot_ax.set_ylabel("T [°C]")
            self.plot_ax.grid(True, linestyle="--", alpha=0.4)

            (line,) = self.plot_ax.plot(x_values, temps, color="tab:red", label="Temperaturprofil")

            boundaries = [0.0]
            for layer in layers:
                boundaries.append(boundaries[-1] + layer.thickness_mm / 1000.0)

            for boundary in boundaries[1:-1]:
                self.plot_ax.axvline(boundary, color="gray", linestyle="--", alpha=0.6)

            cmap = cm.get_cmap("tab20", max(len(layers), 1))
            legend_handles = [line]
            for idx, layer in enumerate(layers):
                color = cmap(idx)
                left = boundaries[idx]
                right = boundaries[idx + 1]
                self.plot_ax.axvspan(left, right, color=color, alpha=0.15)
                legend_handles.append(
                    Patch(facecolor=color, edgecolor="none", label=self._layer_label(layer, idx))
                )

            self.plot_ax.legend(handles=legend_handles, loc="best")
            self.plot_figure.tight_layout()
            self.plot_canvas.draw_idle()

        def _set_output_text(self, text: str) -> None:
            self.output_text.configure(state="normal")
            self.output_text.delete("1.0", tk.END)
            self.output_text.insert(tk.END, text)
            self.output_text.configure(state="disabled")

        # ------------------------------------------------------------------
        # Project handling
        # ------------------------------------------------------------------

        def open_load_dialog(self) -> None:
            try:
                project_names = get_all_project_names()
            except Exception as exc:
                messagebox.showerror("Fehler", f"Projekte konnten nicht geladen werden: {exc}")
                return
            if not project_names:
                messagebox.showinfo("Projekte", "Keine gespeicherten Projekte vorhanden.")
                return

            dialog = tk.Toplevel(self.root)
            dialog.title("Projekt laden")
            dialog.transient(self.root)
            dialog.grab_set()

            ttk.Label(dialog, text="Projekt:").pack(padx=10, pady=(10, 0))

            name_var = tk.StringVar(value=project_names[0])
            combo = ttk.Combobox(dialog, textvariable=name_var, values=project_names, state="readonly")
            combo.pack(padx=10, pady=5, fill="x")
            combo.focus_set()

            status_var = tk.StringVar()
            status_label = ttk.Label(dialog, textvariable=status_var, foreground="red")
            status_label.pack(padx=10, pady=(0, 5), fill="x")

            def on_load() -> None:
                name = name_var.get().strip()
                if not name:
                    status_var.set("Bitte ein Projekt wählen.")
                    return
                try:
                    project = load_project(name)
                except Exception as exc:
                    status_var.set(str(exc))
                    return
                dialog.destroy()
                self._apply_project(project)

            ttk.Button(dialog, text="Laden", command=on_load).pack(padx=10, pady=(0, 5))
            ttk.Button(dialog, text="Abbrechen", command=dialog.destroy).pack(padx=10, pady=(0, 10))

        def _apply_project(self, project: Project) -> None:
            self.refresh_material_options()

            self.T_left_var.set(f"{project.T_left_C:g}")
            self.T_inf_var.set(f"{project.T_inf_C:g}")
            self.h_var.set(f"{project.h_W_m2K:g}")

            rows: List[Dict[str, object]] = []
            for layer in project.layers:
                row: Dict[str, object] = {
                    "mode": layer.mode,
                    "material_id": layer.material_id,
                    "material_name": "",
                    "use_kT": layer.use_kT,
                    "k_const": "",
                    "thickness": f"{layer.thickness_mm:g}",
                    "note": layer.note or "",
                }
                if layer.mode == "material" and layer.material_id is not None:
                    material = self.material_lookup.get(layer.material_id)
                    if material is None:
                        try:
                            material = get_material(layer.material_id)
                            self.material_lookup[layer.material_id] = material
                        except Exception:
                            material = None
                    if material is not None:
                        row["material_name"] = material.name
                else:
                    if layer.k_const is not None:
                        row["k_const"] = f"{layer.k_const:g}"
                rows.append(row)

            self.layer_rows = rows
            self.refresh_tree(select_index=0 if self.layer_rows else None)

        def open_save_dialog(self) -> None:
            dialog = tk.Toplevel(self.root)
            dialog.title("Als Projekt speichern")
            dialog.transient(self.root)
            dialog.grab_set()

            ttk.Label(dialog, text="Projektname:").pack(padx=10, pady=(10, 0))

            name_var = tk.StringVar()
            entry = ttk.Entry(dialog, textvariable=name_var)
            entry.pack(padx=10, pady=5, fill="x")
            entry.focus_set()

            status_var = tk.StringVar()
            status_label = ttk.Label(dialog, textvariable=status_var, foreground="red")
            status_label.pack(padx=10, pady=(0, 5), fill="x")

            def on_save() -> None:
                name = name_var.get().strip()
                if not name:
                    status_var.set("Bitte einen Projektnamen eingeben.")
                    return
                try:
                    T_left, T_inf, h_value = self._parse_boundary_conditions()
                except ValueError as exc:
                    status_var.set(str(exc))
                    messagebox.showerror("Validierungsfehler", str(exc))
                    return

                self.refresh_material_options()
                layers, errors, error_indices = self._collect_layers()
                if errors:
                    self._highlight_errors(error_indices)
                    messagebox.showerror("Validierungsfehler", "\n".join(errors))
                    status_var.set(errors[0])
                    return

                project = Project(
                    name=name,
                    layers=layers,
                    T_left_C=T_left,
                    T_inf_C=T_inf,
                    h_W_m2K=h_value,
                )

                try:
                    save_project(project)
                except Exception as exc:
                    status_var.set(str(exc))
                    messagebox.showerror("Fehler", str(exc))
                    return

                status_label.configure(foreground="green")
                status_var.set(f"Projekt '{name}' gespeichert.")
                dialog.after(1500, dialog.destroy)

            ttk.Button(dialog, text="Speichern", command=on_save).pack(padx=10, pady=(0, 5))
            ttk.Button(dialog, text="Abbrechen", command=dialog.destroy).pack(padx=10, pady=(0, 10))

        def on_tab_changed(self, event: tk.Event) -> None:
            selected = event.widget.select()
            if selected == str(self.frame):
                self.refresh_material_options()

    root = tk.Tk()
    root.title("Heatrix - Isolierung - Temperaturberechnung")

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)

    calculation_tab = CalculationTab(notebook)
    notebook.bind("<<NotebookTabChanged>>", calculation_tab.on_tab_changed)

    MaterialTab(notebook)

    root.mainloop()

