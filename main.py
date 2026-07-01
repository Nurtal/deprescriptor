"""Deprescriptor — NiceGUI app to record medication deprescription decisions.

Loads a list of patient identifiers (IEP) from a CSV via Polars, presents a form to
capture stopped medications with justifications, and stores each decision in a
SQLite database (WAL mode → safe for concurrent writers) together with the IEP and
validation date. The recorded data can be exported to CSV on demand.
"""

from __future__ import annotations

import csv
import io
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

import polars as pl
from nicegui import app, ui

# --- Configuration ---------------------------------------------------------

DATA_FILE = Path("test_data.csv")  # dev data source: single column 'IEP'
DB_FILE = Path("deprescriptions.db")  # persistent store (SQLite, WAL mode)
EXPORT_FILE = Path("deprescriptions_export.csv")  # default CSV export path
ASSETS_DIR = Path("assets")

# Medical blue/white palette.
BLUE = "#0a5ca8"
BLUE_DARK = "#084a87"
BLUE_LIGHT = "#e6f0fa"

app.add_static_files("/assets", str(ASSETS_DIR))


def _logo(*names: str) -> str:
    """Prefer a real logo file if present, else the SVG placeholder.

    Accepts several candidate basenames (e.g. "cdc_brest", "cdc"); the first
    matching file wins. Raster formats take priority over the SVG placeholder.
    """
    for ext in (".png", ".jpg", ".jpeg", ".svg"):
        for name in names:
            candidate = ASSETS_DIR / f"{name}{ext}"
            if candidate.exists():
                return f"/assets/{candidate.name}"
    return f"/assets/{names[0]}.svg"

# Justifications and which ones require a free-text "nature" detail.
JUSTIFICATIONS = [
    "Absence d'indication (jamais indiqué)",
    "Absence d'indication (n'est plus indiqué mais non arrêté)",
    "Présence de contre-indication",
    "Présence d'une interaction médicamenteuse",
    "Survenue d'un effet indésirable",
    "Autre (libre)",
]
JUSTIFICATIONS_NEEDING_DETAIL = {
    "Présence de contre-indication",
    "Présence d'une interaction médicamenteuse",
    "Survenue d'un effet indésirable",
}
FREE_TEXT_JUSTIFICATION = "Autre (libre)"

OUTPUT_COLUMNS = [
    "iep",
    "validation_date",
    "prescription_text",
    "medication",
    "justifications",
    "details",
]


# --- Data loading ----------------------------------------------------------


def load_ieps() -> list[str]:
    """Load the list of IEP identifiers from the data file."""
    if not DATA_FILE.exists():
        return []
    df = pl.read_csv(DATA_FILE)
    if "IEP" not in df.columns:
        return []
    return [str(v) for v in df["IEP"].to_list()]


# --- Persistence (SQLite) --------------------------------------------------


def _connect() -> sqlite3.Connection:
    """Open a SQLite connection with a generous busy timeout.

    The timeout lets concurrent writers wait for the lock instead of failing
    immediately with "database is locked".
    """
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db() -> None:
    """Create the table and enable WAL mode (idempotent)."""
    with closing(_connect()) as conn:
        # WAL allows many concurrent readers alongside a serialized writer and is
        # a persistent property of the database file (set once).
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS deprescriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                iep TEXT NOT NULL,
                validation_date TEXT NOT NULL,
                prescription_text TEXT,
                medication TEXT NOT NULL,
                justifications TEXT,
                details TEXT
            )
            """
        )


def append_rows(rows: list[dict]) -> None:
    """Insert decision rows atomically. Safe for concurrent writers (WAL)."""
    columns = ", ".join(OUTPUT_COLUMNS)
    placeholders = ", ".join(f":{c}" for c in OUTPUT_COLUMNS)
    with closing(_connect()) as conn, conn:  # inner `conn` = one transaction
        conn.executemany(
            f"INSERT INTO deprescriptions ({columns}) VALUES ({placeholders})",
            rows,
        )


def export_csv_str() -> str:
    """Return all recorded decisions as a CSV string (header + rows)."""
    with closing(_connect()) as conn:
        cursor = conn.execute(
            f"SELECT {', '.join(OUTPUT_COLUMNS)} FROM deprescriptions ORDER BY id"
        )
        rows = cursor.fetchall()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(OUTPUT_COLUMNS)
    writer.writerows(rows)
    return buffer.getvalue()


def export_csv(path: Path = EXPORT_FILE) -> Path:
    """Write all recorded decisions to a CSV file and return its path."""
    path.write_text(export_csv_str(), encoding="utf-8")
    return path


# --- UI: a single stopped-medication entry ---------------------------------


class MedicationEntry:
    """One stopped medication: name, justifications, and conditional details."""

    def __init__(self, container: ui.element, on_remove) -> None:
        self.detail_inputs: dict[str, ui.input] = {}
        with container:
            self.card = ui.card().classes("w-full")
        with self.card:
            with ui.row().classes("w-full items-center justify-between"):
                self.name = ui.input("Médicament arrêté").classes("flex-grow")
                ui.button(icon="delete", on_click=lambda: on_remove(self)).props(
                    "flat round color=negative"
                )
            self.justifications = ui.select(
                JUSTIFICATIONS,
                label="Justification(s)",
                multiple=True,
            ).classes("w-full").props("use-chips")
            self.details_container = ui.column().classes("w-full")
            self.justifications.on_value_change(self._refresh_details)

    def _refresh_details(self) -> None:
        """Show a detail field for each selected justification that needs one."""
        selected = self.justifications.value or []
        needed = [
            j
            for j in selected
            if j in JUSTIFICATIONS_NEEDING_DETAIL or j == FREE_TEXT_JUSTIFICATION
        ]
        # Drop inputs no longer needed.
        for j in list(self.detail_inputs):
            if j not in needed:
                self.detail_inputs.pop(j)
        # Rebuild the container to reflect current selection.
        self.details_container.clear()
        with self.details_container:
            for j in needed:
                existing = self.detail_inputs.get(j)
                label = "Précisez" if j == FREE_TEXT_JUSTIFICATION else f"Nature — {j}"
                inp = ui.input(label, value=existing.value if existing else "").classes(
                    "w-full"
                )
                self.detail_inputs[j] = inp

    def to_dict(self) -> dict:
        details = {
            j: inp.value for j, inp in self.detail_inputs.items() if inp.value
        }
        detail_str = "; ".join(f"{j}: {v}" for j, v in details.items())
        return {
            "medication": (self.name.value or "").strip(),
            "justifications": " | ".join(self.justifications.value or []),
            "details": detail_str,
        }


# --- UI: the page ----------------------------------------------------------


@ui.page("/")
def index() -> None:
    ieps = load_ieps()
    entries: list[MedicationEntry] = []

    # --- Theme ---
    ui.colors(primary=BLUE, secondary=BLUE_DARK)
    ui.query("body").style(f"background-color: {BLUE_LIGHT}")

    # --- Header with logos ---
    with ui.header().classes("items-center justify-between px-4 py-2").style(
        f"background: linear-gradient(90deg, {BLUE} 0%, {BLUE_DARK} 100%)"
    ):
        ui.image(_logo("chu_brest")).props("fit=contain").classes("h-20 w-40").style(
            "background:white; border-radius:10px; padding:6px"
        )
        with ui.column().classes("items-center gap-0"):
            ui.label("Deprescriptor").classes("text-2xl font-bold text-white")
            ui.label("Aide à la déprescription médicamenteuse").classes(
                "text-xs text-blue-100"
            )
        ui.image(_logo("cdc_brest", "cdc")).props("fit=contain").classes(
            "h-20 w-40"
        ).style("background:white; border-radius:10px; padding:6px")

    with ui.card().classes("w-full max-w-3xl mx-auto mt-6 shadow-lg").style(
        f"border-top: 4px solid {BLUE}"
    ):
        iep_input = ui.select(
            ieps,
            label="IEP",
            with_input=True,
            new_value_mode="add-unique",
        ).classes("w-full")

        prescription = ui.textarea("Texte de l'ordonnance").classes("w-full")

        ui.label("Médicaments arrêtés").classes("text-lg font-semibold mt-2")
        meds_container = ui.column().classes("w-full")

        def remove_entry(entry: MedicationEntry) -> None:
            entry.card.delete()
            entries.remove(entry)

        def add_entry() -> None:
            entries.append(MedicationEntry(meds_container, remove_entry))

        ui.button("Ajouter un médicament", icon="add", on_click=add_entry).props(
            "outline"
        )

        def validate() -> None:
            iep = (iep_input.value or "").strip()
            if not iep:
                ui.notify("Veuillez saisir un IEP.", type="warning")
                return
            filled = [e for e in entries if e.to_dict()["medication"]]
            if not filled:
                ui.notify("Ajoutez au moins un médicament arrêté.", type="warning")
                return
            now = datetime.now().isoformat(timespec="seconds")
            rows = [
                {
                    "iep": iep,
                    "validation_date": now,
                    "prescription_text": (prescription.value or "").strip(),
                    **e.to_dict(),
                }
                for e in filled
            ]
            append_rows(rows)
            ui.notify(f"{len(rows)} ligne(s) enregistrée(s).", type="positive")
            # Reset the form.
            iep_input.set_value(None)
            prescription.set_value("")
            for e in list(entries):
                remove_entry(e)

        ui.button("Valider", icon="check", on_click=validate).classes("mt-4").props(
            "color=primary"
        )

    with ui.row().classes("w-full max-w-3xl mx-auto mt-3 justify-end"):

        def download_export() -> None:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            ui.download(
                export_csv_str().encode("utf-8"),
                f"deprescriptions_{stamp}.csv",
                media_type="text/csv",
            )

        ui.button(
            "Exporter CSV", icon="download", on_click=download_export
        ).props("outline color=primary")

    add_entry()  # start with one empty medication entry


init_db()

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="Deprescriptor")
