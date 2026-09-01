"""
/api/logs — live tail of RedisLogger's own log stream.

Every RedisLogger.info()/warning()/error()/etc. call (scarlets/utils/
RedisLogger.py) - used throughout the scarlets package internals and
scarlet-agentic-harness's head.py/worker.py dispatch logging - writes a
structured entry to a logs_{uuid} Redis hash with a 10-minute TTL
(RedisLogger.expiry_time). This replaces scarletcomposer/pages/Logging.py's
own hand-rolled scan of the same logs_* keys with a real API endpoint -
same data source, not a new logging mechanism.

Deliberately a live tail, not durable history, by design: RedisLogger's
10-minute TTL means anything older is already gone from Redis by the time
anyone would look - actual retention would mean shipping logs somewhere
durable (Loki, etc.), a different piece entirely, not something this
endpoint can add after the fact.

Filtering (by app/node/level) is done client-side in composer-ui, same as
the old Streamlit page's own filter UI - but fixed here: that page combined
two filters with OR ("matches this app OR this node"), so selecting both
showed anything matching *either* rather than both. Returning the full set
and filtering correctly in the UI avoids repeating that bug.
"""
import logging

from fastapi import APIRouter
from scarlets.utils.ScarletUtils import redisConnect

router = APIRouter()


@router.get("")
async def list_logs():
    try:
        r = redisConnect(decode_responses=True)
        entries = []
        for key in r.scan_iter(match="logs_*"):
            try:
                entry = r.hgetall(key)
                if not entry:
                    continue
                entries.append({
                    "id": key,
                    "time": float(entry.get("time", 0)),
                    "app": entry.get("app", ""),
                    "node": entry.get("node", ""),
                    "level": entry.get("level", "INFO"),
                    "msg": entry.get("msg", ""),
                    "filename": entry.get("filename", ""),
                    "line": entry.get("line", ""),
                })
            except Exception as exc:
                logging.error(f"list_logs: could not read {key}: {exc}")
                continue
        entries.sort(key=lambda e: e["time"], reverse=True)
        return {"error": False, "response": {"logs": entries}}
    except Exception as exc:
        logging.error(f"list_logs failed: {exc}")
        return {"error": True, "response": str(exc)}
