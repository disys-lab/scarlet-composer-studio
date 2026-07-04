# CLI Reference

The `scarlet-composer` CLI is the entry point for the `scarletcomposer` package.

---

## Installation

```bash
pip install scarletcomposer
scarlet-composer --help
```

---

## Command Tree

```
scarlet-composer
└── composer
    ├── gui          Launch the Streamlit UI + Tornado background server
    └── version      Print the package version
```

---

## scarlet-composer composer gui

Launch the Composer UI.

```bash
scarlet-composer composer gui [OPTIONS]
```

### Options

| Option | Default | Description |
|---|---|---|
| `--port`, `-p` | `8501` | Streamlit port |
| `--lport` | `9099` | Tornado background server port |
| `--no-background` | _(flag)_ | Skip starting the Tornado server |

### Examples

```bash
# Default launch
scarlet-composer composer gui

# Custom ports
scarlet-composer composer gui --port 8502 --lport 9100

# UI only (no background server)
scarlet-composer composer gui --no-background
```

### What it starts

1. **Tornado BackgroundServer** on `--lport` — provides `/api/v2/getNodeInfo`
2. **Streamlit** on `--port` — serves `Scarlets.py` (the main UI)

Both processes run in the same Python process. Ctrl-C stops both.

---

## scarlet-composer composer version

```bash
scarlet-composer composer version
# scarletcomposer 0.5.0
```

---

## Environment Variables

The CLI itself reads no environment variables. The Streamlit process it launches reads all the standard Scarlet env vars at runtime — see [Environment Variables](../deployment/env-vars.md).

---

## Entry Point

The CLI is registered in `pyproject.toml` / `setup.py` as:

```
scarlet-composer = scarletcomposer.cli.scarletDriver:main
```

The `scarletDriver` module uses `click` to define the command tree. The `composer gui` command calls `subprocess.Popen(["streamlit", "run", ...])` after starting the Tornado server in a background thread.
