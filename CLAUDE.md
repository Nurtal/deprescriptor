# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
pip install -r requirements.txt   # install NiceGUI + Polars
python main.py                    # run the app (serves on http://localhost:8080)
```

There is no test/lint tooling yet.

## Architecture

Single-file app in `main.py`:
- `load_ieps()` reads the `IEP` column from `DATA_FILE` (`test_data.csv`) via Polars.
- Persistence is **SQLite** in `DB_FILE` (`deprescriptions.db`, gitignored), created by
  `init_db()` at startup with WAL mode enabled — this makes concurrent writers safe
  (many readers + serialized writes) rather than the earlier plain-CSV append, which
  raced across processes. `_connect()` sets a 30s busy timeout. `append_rows()` inserts
  one row **per stopped medication** in a single transaction. `export_csv_str()` /
  `export_csv()` render the table to CSV (`OUTPUT_COLUMNS` order); the "Exporter CSV"
  button streams a timestamped download via `ui.download`.
- `MedicationEntry` is a reusable component (name + multi-select justifications +
  conditional detail fields). Detail fields appear only for justifications in
  `JUSTIFICATIONS_NEEDING_DETAIL` and for the free-text "Autre" option; they are
  rebuilt reactively on selection change.
- `index()` (`@ui.page("/")`) wires the form: IEP select (typeable, accepts new
  values), prescription textarea, add/remove medication entries, and a validate
  button that persists rows with `iep` + ISO `validation_date` and resets the form.

Justifications and their detail requirements are defined by the module-level
constants near the top of `main.py`.

## Original spec

See `README.md` (French). Summary:

A [NiceGUI](https://nicegui.io/) web app for recording medication deprescription
decisions ("deprescriptor"). Intended stack: NiceGUI (UI) + [Polars](https://pola.rs/)
(data loading).

Flow:
1. Load a Polars DataFrame with a single column `IEP` (patient identifier). For
   development, load from `test_data.csv`.
2. Form with:
   - An `IEP` field — free text entry *or* selection from a dropdown of loaded IEPs.
   - A text field for the prescription text (texte d'ordonnance).
   - A repeatable section to enter one or more stopped medications ("médicaments arrêtés").
   - For each stopped medication, one or more justifications (multi-select):
     - Absence d'indication (jamais indiqué)
     - Absence d'indication (n'est plus indiqué mais non arrêté)
     - Présence de contre-indication
     - Présence d'une interaction médicamenteuse
     - Survenue d'un effet indésirable
     - Autre (libre)
   - If justification is contre-indication, interaction médicamenteuse, or effet
     indésirable → show an extra text field to describe its nature.
   - A submit/validate button.
3. On validation, append the response to an output CSV including the `IEP` and the
   validation date.

`test_data.csv` is the dev data source only (a header `IEP` plus sample values).
