# CLI Reference

The `scarlet-composer` CLI is the entry point for the `scarletcomposer`
package. It covers parsing and deploying `#scarlet` declarations from
source — it does **not** launch the operator dashboard; that's a Docker
image, see [Docker Images](../deployment/docker.md).

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
    └── compose <dir>   Parse #scarlet declarations, optionally deploy
```

---

## scarlet-composer composer compose

Parse a Python script (or directory of scripts) for `#scarlet`
declarations, and optionally deploy the resulting scarlets to Redis.

```bash
scarlet-composer composer compose [OPTIONS] DIR
```

### Options

| Option | Default | Description |
|---|---|---|
| `--deploy` | _(flag)_ | Deploy parsed scarlets to Redis after interpretation |
| `--file` | _(none)_ | Target a single file within `DIR` instead of the whole directory |

### Examples

```bash
# Parse every file in a directory, print what was found
scarlet-composer composer compose ./my_scarlets

# Parse one file and deploy immediately
scarlet-composer composer compose ./my_scarlets --file model.py --deploy
```

Reads `REDIS_HOST`/`REDIS_PORT`/`REDIS_AUTH_TOKEN` from the environment for
the `--deploy` step — see [Environment Variables](../deployment/env-vars.md).

---

## Entry Point

```
scarlet-composer = scarletcomposer.composer.scarletDriver:scarletcomposer
```

Defined via `click`. `--version` is available on the CLI and every
subcommand group.
