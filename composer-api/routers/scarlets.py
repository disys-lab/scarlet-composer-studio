"""
/api/scarlets — replaces scarletcomposer/Scarlets.py's View + Deploy tabs
(Container Builds is its own separate page/router, not part of this one -
see composer-ui's Sidebar, which already splits them).

Reuses the existing scarletcomposer.composer.ScarletInterpreter/ScarletHandler
parsing logic (tokenize-based #scarlet comment extraction) rather than
reimplementing it - see requirements.txt for the extra local install step
this needs.

Two real fixes versus the old Streamlit page, not just a port:
- The page-level "Update Description" button called
  ScarletHandler.updateScarletsDescription(), a method that doesn't exist -
  it crashed every time. The *other*, per-scarlet "Update Description"
  button (inside each expander) worked fine, writing directly via Redis.
  This router only implements the working shape (PUT one description at a
  time) - the broken one isn't replicated.
- SCARLET_COMPILE_HOME was read from a text field and set into
  os.environ, but never actually read anywhere else in the codebase (grepped
  the whole tree to confirm) - dropped, not replicated as dead UI.

Deploy is stateless here, unlike Streamlit's session_state-held
interpreter instance: POST /interpret returns the extracted scarlet dict
to the caller for review/editing; POST /deploy takes that (possibly
edited) dict back and writes it to Redis. No server-side interpreter
state held between requests.
"""
import json
import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from scarlets.core.Mapper import Mapper
from scarlets.utils.ScarletUtils import redisConnect, register_scarlet_definition
from scarletcomposer.composer.ScarletInterpreter import ScarletInterpreter

from auth_dep import require_admin
from session import Session

router = APIRouter()


@router.get("")
async def list_scarlets():
    try:
        r = redisConnect(decode_responses=True)
        scarlets = []
        for key in r.scan_iter(match="scarlet_definition_*"):
            name = key.split("scarlet_definition_", 1)[1]
            try:
                value = r.get(key)
                if not value:
                    continue
                entry = json.loads(value)
            except Exception as exc:
                logging.error(f"list_scarlets: could not parse {key}: {exc}")
                continue
            scarlets.append({
                "name": name,
                "scarlet_type": entry.get("scarlet_type", ""),
                "mode": entry.get("scarlet_attributes", {}).get("mode", ""),
                "description": entry.get("description", ""),
                "attributes": entry.get("scarlet_attributes", {}),
                "created_by": entry.get("created_by"),
                "created_at": entry.get("created_at"),
            })
        scarlets.sort(key=lambda s: s["name"])
        return {"error": False, "response": {"scarlets": scarlets}}
    except Exception as exc:
        logging.error(f"list_scarlets failed: {exc}")
        return {"error": True, "response": str(exc)}


@router.put("/{name}/description")
async def update_description(name: str, body: dict, session: Session = Depends(require_admin)):
    description = body.get("description", "")
    try:
        r = redisConnect(decode_responses=True)
        key = f"scarlet_definition_{name}"
        raw = r.get(key)
        if not raw:
            return {"error": True, "response": f"Scarlet '{name}' not found"}
        entry = json.loads(raw)
        entry["description"] = description
        r.set(key, json.dumps(entry))
        return {"error": False, "response": {"name": name, "description": description}}
    except Exception as exc:
        logging.error(f"update_description failed: {exc}")
        return {"error": True, "response": str(exc)}


@router.delete("/{name}")
async def delete_scarlet(name: str, session: Session = Depends(require_admin)):
    try:
        r = redisConnect(decode_responses=True)
        deleted = []
        for key in (f"scarlet_definition_{name}", f"scarletdoc:{name}"):
            if r.exists(key):
                r.delete(key)
                deleted.append(key)
        return {"error": False, "response": {"deleted": deleted}}
    except Exception as exc:
        logging.error(f"delete_scarlet failed: {exc}")
        return {"error": True, "response": str(exc)}


@router.post("/{name}/reset")
async def reset_scarlet(name: str, session: Session = Depends(require_admin)):
    """Clears the scarlet's *data* (Mapper.clearAll()), not its definition -
    same distinction the old Streamlit page's separate Delete/Reset buttons made."""
    try:
        success_chunks, exception = Mapper(name).clearAll()
        if exception:
            return {"error": True, "response": str(exception)}
        return {"error": False, "response": {"cleared_chunks": len(success_chunks)}}
    except Exception as exc:
        logging.error(f"reset_scarlet failed: {exc}")
        return {"error": True, "response": str(exc)}


def _interpret_path(target: Path, interpreter: ScarletInterpreter) -> None:
    if target.is_file():
        interpreter.scarletExtractor(str(target))
    elif target.is_dir():
        for f in target.rglob("*"):
            if f.is_file():
                try:
                    interpreter.scarletExtractor(str(f))
                except Exception:
                    # Non-Python / non-UTF8 files under the directory can't be
                    # tokenized - skip them rather than aborting the whole scan,
                    # same tolerance the old Streamlit page's per-file try/except had.
                    continue


@router.post("/interpret")
async def interpret_scarlets(body: dict, session: Session = Depends(require_admin)):
    """
    body: {"path": "<server-side file or directory path>"} - composer-api's
    own filesystem, same model the old Streamlit page used (it ran on the
    same machine as the operator's browser session; here it's wherever
    composer-api itself runs, e.g. a mounted volume).
    """
    path_str = body.get("path", "")
    if not path_str:
        return {"error": True, "response": "path is required"}
    target = Path(path_str)
    if not target.exists():
        return {"error": True, "response": f"'{path_str}' does not exist"}

    try:
        interpreter = ScarletInterpreter()
        _interpret_path(target, interpreter)
        return {"error": False, "response": {"scarlets": interpreter.scarletContent}}
    except Exception as exc:
        logging.error(f"interpret_scarlets failed: {exc}")
        return {"error": True, "response": str(exc)}


@router.post("/interpret/upload")
async def interpret_scarlets_upload(file: UploadFile = File(...), session: Session = Depends(require_admin)):
    """
    Same extraction as POST /interpret, but for a file the operator's
    browser uploads directly - the path-based endpoint above only works
    when the script already sits on composer-api's own filesystem, which
    is almost never the same machine as the operator's browser in a real
    deployment. Written to a throwaway temp file only so
    ScarletInterpreter.scarletExtractor() (tokenize-based, file-path only)
    can read it - never persisted past this request.
    """
    try:
        content = await file.read()
        suffix = Path(file.filename or "upload").suffix or ".py"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            interpreter = ScarletInterpreter()
            interpreter.scarletExtractor(str(tmp_path))
            return {"error": False, "response": {"scarlets": interpreter.scarletContent}}
        finally:
            tmp_path.unlink(missing_ok=True)
    except Exception as exc:
        logging.error(f"interpret_scarlets_upload failed: {exc}")
        return {"error": True, "response": str(exc)}


@router.post("/deploy")
async def deploy_scarlets(body: dict, session: Session = Depends(require_admin)):
    """
    body: {"scarlets": {<name>: {scarlet_type, scarlet_attributes, description, ...}, ...}}
    - the (possibly user-edited) object POST /interpret returned. Deploy
    always overwrites, same as ScarletHandler.deployScarlets() - a CLI/UI
    deploy takes precedence over whatever an agent may have already
    self-registered.
    """
    scarlets = body.get("scarlets", {})
    if not scarlets:
        return {"error": True, "response": "scarlets is required and must be non-empty"}

    deployed = []
    try:
        for name, entry in scarlets.items():
            attrs = entry.get("scarlet_attributes", {})
            expiry = int(attrs["expiry"]) if "expiry" in attrs else None
            register_scarlet_definition(
                scarlet_name=name,
                scarlet_type=entry.get("scarlet_type", ""),
                description=entry.get("description", ""),
                attributes=attrs,
                expiry=expiry,
                overwrite=True,
            )
            deployed.append(name)
        return {"error": False, "response": {"deployed": deployed}}
    except Exception as exc:
        logging.error(f"deploy_scarlets failed: {exc}")
        return {"error": True, "response": str(exc)}
