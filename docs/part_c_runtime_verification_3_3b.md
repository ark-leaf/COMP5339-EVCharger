# Step 3.3B runtime verification record

Date: 2026-10-28. No MQTT event was published and no DuckDB database was
opened for writing during this verification attempt.

## Environment result

`py -0p` reported no registered Python installations. The old virtual
environment refers to a missing Python 3.13 executable. A discovered
`C:\Users\aimer\miniconda3\python.exe` runs Python 3.9.25, but its pip and
ensurepip both fail before installation: pip cannot resolve the Windows local
application-data registry location and ensurepip fails to load `_ctypes`.

Creating a fresh isolated `.venv_step3_3b` consequently failed to bootstrap
pip. The incomplete virtual environment was removed. No project source,
protected Yeh dependency file, or database was changed.

## Runtime status

Automated tests, test database preparation, NiceGUI startup, MQTT lifecycle,
and browser acceptance are **NOT EXECUTED**. They require a healthy supported
Windows Python installation and a fresh virtual environment in this isolated
project.

## Recovery procedure

Install a supported 64-bit Python (3.11 or 3.12 is recommended) and select it
in VS Code. Then, from this isolated project:

```powershell
py -3.12 -m venv .venv_step3_3b
.\.venv_step3_3b\Scripts\python.exe -m pip install --upgrade pip
.\.venv_step3_3b\Scripts\python.exe -m pip install -r requirements.txt
.\.venv_step3_3b\Scripts\python.exe -m pip install -r requirements-dashboard.txt
```

Only after those commands succeed should the isolated Assignment 1 database be
created or copied while all writers are stopped, the event schema applied to
that isolated copy, and the automated tests run.
