"""
Isolierung_ui.py
Enthält die Tkinter-Oberfläche mit integrierter matplotlib-Grafik
und einem zweiten Tab für die Projektverwaltung.
"""

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, List, Optional, Tuple
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.figure import Figure
from Isolierung_logic import (
    compute_multilayer,
    save_project,
    load_project,
    delete_project,
    get_all_project_names
)


def run_ui(calculate_callback: Optional[Callable[[List[float], List[float], float, float, float], dict]] = None):
    # --- Hilfsfunktionen ---
    last_inputs: dict = {"value": None}
    last_result: dict = {"value": None}

    def _parse_inputs() -> Tuple[List[float], List[float], float, float, float]:
        n = int(entry_layers.get())
        thicknesses = [float(x.strip()) for x in entry_thickness.get().split(',') if x.strip() != ""]
        ks = [float(x.strip()) for x in entry_k.get().split(',') if x.strip() != ""]

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

    def calculate():
        try:
            thicknesses, ks, T_left, T_inf, h = _parse_inputs()
            result = _calculate_with_callback(thicknesses, ks, T_left, T_inf, h)
            last_inputs["value"] = (tuple(thicknesses), tuple(ks), T_left, T_inf, h)
            last_result["value"] = result
            display_result(result)
            plot_temperature_profile(
                thicknesses,
                result['interface_temperatures'],
                result.get('temperature_positions_mm'),
                result.get('temperature_labels'),
            )

        except Exception as e:
            last_result["value"] = None
            messagebox.showerror("Fehler", str(e))

    def display_result(result: dict):
        output.delete('1.0', tk.END)
        try:
            output.insert(tk.END, f"Wärmestromdichte q = {result['q']:.3f} W/m²\n")
            output.insert(tk.END, f"Gesamtwiderstand = {result['R_total']:.5f} m²K/W\n\n")
            output.insert(tk.END, "Temperaturen entlang des Pfades (°C):\n")
            labels = result.get('temperature_labels')
            for i, T in enumerate(result['interface_temperatures']):
                label = labels[i] if labels and i < len(labels) else f"Grenzfläche {i}"
                output.insert(tk.END, f"  {label}: {T:.2f}\n")
        except Exception as e:
            output.insert(tk.END, f"Fehler beim Anzeigen des Ergebnisses: {e}\n")

    def save_current_project(name_entry: tk.Entry) -> Tuple[bool, str]:
        name = name_entry.get().strip()
        if not name:
            return False, "Bitte einen Projektnamen eingeben."

        try:
            thicknesses, ks, T_left, T_inf, h = _parse_inputs()
        except ValueError as ve:
            return False, f"Ungültige Eingabe: {ve}"
        except Exception as e:
            return False, str(e)

        inputs_signature = (tuple(thicknesses), tuple(ks), T_left, T_inf, h)

        if last_inputs["value"] == inputs_signature and last_result.get("value"):
            result = last_result["value"]
        else:
            try:
                result = _calculate_with_callback(thicknesses, ks, T_left, T_inf, h)
            except Exception as e:
                last_result["value"] = None
                return False, str(e)

            display_result(result)
            try:
                plot_temperature_profile(
                    thicknesses,
                    result['interface_temperatures'],
                    result.get('temperature_positions_mm'),
                    result.get('temperature_labels'),
                )
            except Exception as plot_error:
                last_result["value"] = None
                return False, str(plot_error)

            last_inputs["value"] = inputs_signature
            last_result["value"] = result

        if save_project(name, thicknesses, ks, T_left, T_inf, h, result):
            update_project_list()
            last_inputs["value"] = inputs_signature
            last_result["value"] = result
            return True, f"Projekt '{name}' gespeichert."

        return False, "Speichern fehlgeschlagen."

    def load_selected_project():
        # sichere Abfrage des aktuell markierten Eintrags
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

            # project.result kann None sein — prüfen
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
                # Schnittstellen-Temperaturen prüfen
                if 'interface_temperatures' in project.result and project.result['interface_temperatures']:
                    try:
                        plot_temperature_profile(
                            project.thicknesses,
                            project.result['interface_temperatures'],
                            project.result.get('temperature_positions_mm'),
                            project.result.get('temperature_labels'),
                        )
                    except Exception as e:
                        messagebox.showerror("Fehler", str(e))
            else:
                last_inputs["value"] = None
                last_result["value"] = None
                output.delete('1.0', tk.END)
                output.insert(tk.END, "Kein Ergebnis im Projekt gespeichert.\n")

    def delete_selected_project():
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

    def update_project_list():
        project_listbox.delete(0, tk.END)
        for name in get_all_project_names():
            project_listbox.insert(tk.END, name)

    def plot_temperature_profile(
        thicknesses: List[float],
        temperatures: List[float],
        positions_mm: Optional[List[float]] = None,
        labels: Optional[List[str]] = None,
    ):
        if positions_mm is None:
            positions_mm = [0.0]
            for t in thicknesses:
                positions_mm.append(positions_mm[-1] + t)
            if len(temperatures) > len(positions_mm):
                positions_mm.append(positions_mm[-1])

        if len(positions_mm) != len(temperatures):
            raise ValueError("Positions- und Temperaturlisten müssen gleich lang sein.")

        colors = ["#e81919", "#fce6e6"]
        cmap = LinearSegmentedColormap.from_list("custom_cmap", colors, N=256)

        fig = Figure(figsize=(6, 4), dpi=100)
        ax = fig.add_subplot(111)
        ax.plot(positions_mm, temperatures, linewidth=2, marker='o')

        x_pos = 0.0
        for i, t in enumerate(thicknesses):
            color_value = i / (len(thicknesses) - 1) if len(thicknesses) > 1 else 0.5
            color = cmap(color_value)
            ax.axvspan(x_pos, x_pos + t, color=color, alpha=0.4)
            x_pos += t

        last_index = len(temperatures) - 1
        for idx, (x, T) in enumerate(zip(positions_mm, temperatures)):
            label = labels[idx] if labels and idx < len(labels) else ""
            text = f"{T:.0f}°C"
            if label and (idx == 0 or idx == last_index):
                text = f"{label}\n{text}"
            ax.text(x, T, text, ha='center', va='bottom', fontsize=8)

        ax.set_xlabel('Dicke [mm]')
        ax.set_ylabel('Temperatur [°C]')
        ax.set_title('Temperaturverlauf durch die Isolierung')
        ax.grid(True, linestyle='--', alpha=0.6)
        fig.tight_layout()

        # Canvas im frame_plot ersetzen
        for widget in frame_plot.winfo_children():
            widget.destroy()
        canvas = FigureCanvasTkAgg(fig, master=frame_plot)
        canvas.draw()
        canvas.get_tk_widget().pack(fill='both', expand=True)

    def save_dialog(parent):
        dialog = tk.Toplevel(parent)
        dialog.title("Projekt speichern")

        tk.Label(dialog, text="Projektname:").pack(pady=5)
        name_entry = tk.Entry(dialog)
        name_entry.pack(pady=5)
        name_entry.focus_set()

        status_var = tk.StringVar(value="")
        status_label = tk.Label(dialog, textvariable=status_var, fg="red")
        status_label.pack(pady=(0, 5))

        def on_save():
            success, message = save_current_project(name_entry)
            status_var.set(message)
            status_label.configure(fg="green" if success else "red")
            if success:
                dialog.after(1500, dialog.destroy)

        tk.Button(dialog, text="Speichern", command=on_save).pack(pady=5)
        tk.Button(dialog, text="Abbrechen", command=dialog.destroy).pack(pady=(0, 5))

    # --- Hauptelemente der UI ---
    root = tk.Tk()
    root.title("Heatrix - Isolierung - Temperaturberechnung")

    notebook = ttk.Notebook(root)
    notebook.pack(fill='both', expand=True)

    # Tab 1: Berechnung
    tab1 = ttk.Frame(notebook)
    notebook.add(tab1, text="Berechnung")

    tk.Label(tab1, text="Anzahl Schichten:").grid(row=0, column=0, sticky='w')
    entry_layers = tk.Entry(tab1)
    entry_layers.grid(row=0, column=1)

    tk.Label(tab1, text="Dicken [mm] (kommagetrennt):").grid(row=1, column=0, sticky='w')
    entry_thickness = tk.Entry(tab1, width=40)
    entry_thickness.grid(row=1, column=1)

    tk.Label(tab1, text="Wärmeleitwerte k [W/mK] (kommagetrennt):").grid(row=2, column=0, sticky='w')
    entry_k = tk.Entry(tab1, width=40)
    entry_k.grid(row=2, column=1)

    tk.Label(tab1, text="T_links [°C]:").grid(row=3, column=0, sticky='w')
    entry_T_left = tk.Entry(tab1)
    entry_T_left.grid(row=3, column=1)

    tk.Label(tab1, text="T_∞ [°C]:").grid(row=4, column=0, sticky='w')
    entry_T_inf = tk.Entry(tab1)
    entry_T_inf.grid(row=4, column=1)

    tk.Label(tab1, text="h [W/m²K]:").grid(row=5, column=0, sticky='w')
    entry_h = tk.Entry(tab1)
    entry_h.grid(row=5, column=1)

    tk.Button(tab1, text="Berechnen", command=calculate).grid(row=6, column=0, pady=5)
    tk.Button(tab1, text="Speichern", command=lambda: save_dialog(tab1)).grid(row=6, column=1, pady=5)

    output = tk.Text(tab1, height=10, width=60)
    output.grid(row=7, column=0, columnspan=2, pady=5)

    frame_plot = tk.Frame(tab1, width=600, height=400)
    frame_plot.grid(row=8, column=0, columnspan=2, sticky='nsew', pady=10)

    # mache die Spalten/Zeilen anpassbar (wichtig für Resize)
    tab1.grid_columnconfigure(1, weight=1)
    tab1.grid_rowconfigure(8, weight=1)

    # Tab 2: Projekte
    tab2 = ttk.Frame(notebook)
    notebook.add(tab2, text="Projekte")

    project_listbox = tk.Listbox(tab2, width=40, height=10)
    project_listbox.pack(pady=10)
    update_project_list()

    button_frame = tk.Frame(tab2)
    button_frame.pack(pady=5)

    tk.Button(button_frame, text="Laden", command=load_selected_project).pack(side=tk.LEFT, padx=5)
    tk.Button(button_frame, text="Löschen", command=delete_selected_project).pack(side=tk.LEFT, padx=5)

    root.mainloop()
