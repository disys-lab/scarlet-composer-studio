"""
Messenger — Agent-to-agent communication primitive built on Redis.

Each Messenger instance scopes two namespaces in Redis:
  - <scarletName>:msg   — message queue payloads
  - <scarletName>:reg   — registry / liveness records

Queue semantics:
  - <ns>:msg:tail:{agentId}  Redis counter, atomically incremented on Send
  - <ns>:msg:head:{agentId}  read cursor, advanced on Receive/ack
  - <ns>:msg:{agentId}:{n}   payload for sequence number n

All queue keys are scoped to the bus namespace (<ns> = <scarletName>:msg) so
the same agentId can safely receive on multiple campaign buses simultaneously
without counter collision — enabling a single head agent to manage several
campaigns by opening one Messenger per campaign bus.

Registry semantics:
  - <ns>:reg:{agentId}      JSON liveness/status record, refreshed by heartbeat

Typical usage (see DESIGN.md §5 for full rationale):

    # Head agent
    global_bus = Messenger("head-agent")
    global_bus.Send("data_worker_osu1", {"task": "run_anomaly_detection"})

    # Worker agent
    global_bus = Messenger("head-agent")
    local_bus  = Messenger("factory-floor")

    global_bus.Register()
    global_bus.ReportStatus({"status": "online", "capabilities": ["anomaly_detection"]})

    msg = global_bus.Receive()
    if msg:
        # process task ...
        global_bus.Send("head-agent", {"result": "...", "status": "done"})
"""

import os, uuid, time, json, threading
from scarlets.utils.RedisLogger import RedisLogger
from scarlets.utils.ScarletUtils import (
    redisConnect,
    register_scarlet_definition,
    touch_scarlet_definition,
)

# Reserved field names inside an inbox hash (see Messenger._inboxKey).
# Every other field in that hash is a sequence number, so these are
# double-underscored to keep them outside the space of values _nextSeq
# can produce - a field can be a cursor or a message, never ambiguous.
_HEAD_FIELD = "__head__"
_TAIL_FIELD = "__tail__"

# Seconds between heartbeats. Named here rather than left only as
# _startHeartbeat's default because __init__ checks the configured TTL
# against it - state renewed on this cadence must outlive the gap.
_HEARTBEAT_INTERVAL = 30


class Messenger:
    """
    Agent-to-agent messaging primitive backed by raw Redis.

    Parameters
    ----------
    scarletName : str
        Namespace for this bus. Use "head-agent" for the global coordination
        channel and the device group name for the local channel.
    agentId : str, optional
        Stable identifier for this agent. Defaults to APP_ID env var.
        Construct as APP_ID_NODE_ADDRESS when both are known.
    """

    def __init__(self, scarletName, agentId=None, description=""):
        self.scarletName  = scarletName
        app_id       = os.environ.get("APP_ID", "unknown")
        node_address = os.environ.get("NODE_ADDRESS", "")
        if agentId is not None:
            self.agentId = agentId
        else:
            if node_address:
                self.agentId = f"{app_id}_{node_address}"
            else:
                RedisLogger.warning(
                    f"NODE_ADDRESS is not set — agentId will be '{app_id}' without a node "
                    f"suffix. If multiple nodes share the same APP_ID their inboxes will "
                    f"collide. Instantiate a Mapper or RedisScarlet before Messenger "
                    f"to trigger node address resolution."
                )
                self.agentId = app_id
        # Seed RedisLogger identity if not already set by ScarletBase
        if RedisLogger.app_id == "undefined":
            RedisLogger.app_id = app_id
        if RedisLogger.nodeIp == "undefined":
            RedisLogger.nodeIp = node_address or "unknown"
        self._instanceId  = str(uuid.uuid4())
        self._msg_ns      = f"{scarletName}:msg"
        self._reg_ns      = f"{scarletName}:reg"
        self._last_status = None   # preserved across heartbeat ticks
        self._description = description   # kept for _touchState()'s recreate path
        # Same env var and default RedisScarlet/ScarletBase use for
        # scarletDataExpiry, read directly because Messenger is not in that
        # class hierarchy (it has no ScarletBase to inherit it from). One
        # value across both scarlet types, so "how long does abandoned
        # state survive" has a single answer.
        self._expiry = int(os.environ.get("SCARLET_DATA_EXPIRY", 3600))
        # This state is kept alive by the heartbeat below, so a TTL shorter
        # than the interval between beats expires it between them: a
        # perfectly healthy agent would flicker in and out of the registry
        # and lose queued messages, with nothing reporting an error. The
        # default (3600 against a 30s beat) has ample margin; this only
        # fires when SCARLET_DATA_EXPIRY has been set too low by hand.
        if self._expiry < _HEARTBEAT_INTERVAL * 2:
            RedisLogger.warning(
                f"[{scarletName}] SCARLET_DATA_EXPIRY={self._expiry}s is less than twice "
                f"the {_HEARTBEAT_INTERVAL}s heartbeat interval - registrations and inboxes "
                f"may expire between heartbeats while agents are still running"
            )
        self.Register()
        self._startHeartbeat()
        register_scarlet_definition(
            scarlet_name=scarletName,
            scarlet_type="messaging",
            description=description,
            attributes={"mode": "redis-scarlet"},
            expiry=self._expiry,
        )

    def _inboxKey(self, agentId):
        """
        Redis key of `agentId`'s inbox on this bus.

        One hash per recipient, holding every message addressed to them
        plus their own read/write cursors as reserved fields - rather than
        one Redis key per message plus two cursor keys, which is what this
        replaced.

        The reason is expiry. A TTL applies to a whole key, so with a key
        per message, expiring an inbox meant issuing one EXPIRE per
        message, and *renewing* it meant reissuing all of them on every
        heartbeat - a cost that grows with history, which is the thing the
        expiry exists to bound. As one hash it is a single EXPIRE per
        recipient regardless of how many messages it holds.

        It also removes a failure mode rather than working around it. With
        cursors in separate keys, a message that expired while its cursors
        did not left `_pollInbox` reading a sequence whose payload no
        longer existed; it returned without acking, so `__head__` never
        advanced and every later message was stranded behind it. Cursors
        living in the same key as the messages makes that unrepresentable:
        they expire together, and a reader simply finds a fresh, empty
        inbox.
        """
        return f"{self._msg_ns}:{agentId}"

    # ------------------------------------------------------------------ #
    # Public API (PascalCase — consistent with Mapper convention)         #
    # ------------------------------------------------------------------ #

    def Send(self, targetAgentId, message):
        """
        Send a message to a specific agent's inbox.

        Messages are stored under sequence-numbered keys:
            <msg_ns>:{targetAgentId}:{seqNum}
        The tail pointer (<msg_ns>:tail:{targetAgentId}) is atomically incremented.

        Parameters
        ----------
        targetAgentId : str
            `agentId` of the recipient.
        message : dict
            JSON-serializable message body.
        """
        seq = self._nextSeq(targetAgentId)
        inbox = self._inboxKey(targetAgentId)
        payload = {
            "from":        self.agentId,
            "to":          targetAgentId,
            "seq":         seq,
            "ts":          time.time(),
            "instance_id": self._instanceId,
            "body":        message,
        }
        try:
            r = redisConnect()
            r.hset(inbox, str(seq), json.dumps(payload))
            # Sending is activity on this bus, so it renews the recipient's
            # inbox the same way a heartbeat renews a registration - an
            # inbox being written to is not abandoned, even if its owner
            # has not read from it yet.
            r.expire(inbox, self._expiry)
            RedisLogger.debug(f"[{self.scarletName}] {self.agentId} → {targetAgentId} seq={seq}")
        except Exception as e:
            RedisLogger.error(f"[{self.scarletName}] Send failed: {e}")

    def Receive(self, timeout=0):
        """
        Check inbox for messages addressed to this agent.

        Non-blocking by default. Automatically acks on return. Inbox
        continuity is preserved across restarts via the head pointer in
        Redis.

        Parameters
        ----------
        timeout : float, optional
            Seconds to poll for a message before giving up. `0` (the
            default) checks once and returns immediately.

        Returns
        -------
        dict or None
            The next unread message, or `None` if the inbox is empty
            after `timeout`.
        """
        return self._pollInbox(timeout)

    def Broadcast(self, message):
        """
        Send a message to every currently registered agent (except self).

        Parameters
        ----------
        message : dict
            JSON-serializable message body.
        """
        status = self.GatherStatus()
        if not status:
            return
        for agent_id, record in status.items():
            if agent_id != self.agentId:
                self.Send(agent_id, message)

    def ReportStatus(self, status):
        """
        Write this agent's status and capabilities to the registry.

        Called at startup and periodically by the heartbeat thread.

        Parameters
        ----------
        status : dict
            Should include at minimum
            ``{"status": "online", "capabilities": [...]}``.
        """
        self._last_status = status   # preserve so heartbeat can re-publish
        record = {
            "agent_id":    self.agentId,
            "instance_id": self._instanceId,
            "scarlet_name": self.scarletName,
            "ts":          time.time(),
            **status,
        }
        try:
            r = redisConnect()
            # ex= rather than a bare SET followed by EXPIRE, and not a bare
            # SET at all: SET drops any TTL already on the key. The
            # heartbeat calls this in preference to Register() whenever a
            # status has been reported, so a plain SET here would strip the
            # expiry Register() set and leave the record permanent again -
            # silently, and on exactly the agents that are working
            # normally.
            r.set(f"{self._reg_ns}:{self.agentId}", json.dumps(record), ex=self._expiry)
        except Exception as e:
            RedisLogger.error(f"[{self.scarletName}] ReportStatus failed: {e}")

    def GatherStatus(self):
        """
        Collect registration records from every agent on this bus.

        Returns
        -------
        dict
            Registration records keyed by `agentId`.
        """
        try:
            r = redisConnect()
            pattern = f"{self._reg_ns}:*"
            result = {}
            for key in r.scan_iter(match=pattern):
                raw = r.get(key)
                if raw:
                    try:
                        record = json.loads(raw)
                        agent_id = record.get("agent_id", key.decode("utf-8").split(":")[-1])
                        result[agent_id] = record
                    except Exception:
                        pass
            return result
        except Exception as e:
            RedisLogger.error(f"[{self.scarletName}] GatherStatus exception: {e}")
            return {}

    def Register(self):
        """
        Write a liveness record to the registry.

        Called on `__init__` and by the heartbeat thread every 30 seconds.
        """
        record = {
            "agent_id":     self.agentId,
            "instance_id":  self._instanceId,
            "scarlet_name": self.scarletName,
            "ts":           time.time(),
            "status":       "online",
        }
        try:
            r = redisConnect()
            key = f"{self._reg_ns}:{self.agentId}"
            r.set(key, json.dumps(record))
            # Written with a TTL, renewed by every heartbeat. Without one a
            # dead agent's record - which says "status": "online" and only
            # stops having its ts advanced - persisted forever, so every
            # reader had to know to distrust presence and filter on ts
            # itself. They did so inconsistently (60s in the harness's
            # gather_workers, 90s in composer-api's agent_health, none at
            # all in its dashboard agent count, which therefore counted
            # long-dead agents as live). Expiring the record makes presence
            # mean what it appears to mean.
            r.expire(key, self._expiry)
            RedisLogger.debug(f"[{self.scarletName}] {self.agentId} registered (instance={self._instanceId[:8]})")
        except Exception as e:
            RedisLogger.error(f"[{self.scarletName}] Register failed: {e}")

    def clearAll(self):
        """Clear all messages and registry entries for this bus.

        The message pattern below now matches one hash per recipient
        rather than one key per message, so this deletes far fewer keys
        than it used to - and it still matches any keys left over from
        the pre-hash layout, which are deleted here too rather than
        lingering as orphans.
        """
        try:
            r = redisConnect()
            for pattern in [f"{self._msg_ns}:*", f"{self._reg_ns}:*"]:
                keys = list(r.scan_iter(match=pattern))
                if keys:
                    r.delete(*keys)
        except Exception as e:
            RedisLogger.error(f"[{self.scarletName}] clearAll failed: {e}")

    def AsTools(self):
        """
        Return MCP-compatible tool definitions and handlers.

        The returned dict can be registered with any LLM agent framework
        (LangChain, LlamaIndex, Open WebUI, etc.).

        Returns
        -------
        dict
            ``{"tools": [...], "handlers": {...}}`` - `tools` is a list of
            tool-definition dicts (`name`, `description`, `parameters`);
            `handlers` maps each tool `name` to the callable that
            implements it (`Send`/`Receive`/`Broadcast`/`ReportStatus`/
            `GatherStatus`).
        """
        tools = [
            {
                "name": "send_message",
                "description": f"Send a message to a specific agent on the {self.scarletName} bus.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target_agent_id": {"type": "string", "description": "The agentId to send to"},
                        "message":         {"type": "object", "description": "Message payload (any JSON-serialisable dict)"},
                    },
                    "required": ["target_agent_id", "message"],
                },
            },
            {
                "name": "check_inbox",
                "description": f"Check this agent's inbox on the {self.scarletName} bus for new messages.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "broadcast",
                "description": f"Send a message to all registered agents on the {self.scarletName} bus.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "object", "description": "Message payload"},
                    },
                    "required": ["message"],
                },
            },
            {
                "name": "report_status",
                "description": "Report this agent's current status and capabilities to the registry.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "object", "description": "Status dict (e.g. {status, capabilities, data_sources})"},
                    },
                    "required": ["status"],
                },
            },
            {
                "name": "gather_status",
                "description": "Gather status records from all agents currently registered on this bus.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        ]

        handlers = {
            "send_message":  lambda target_agent_id, message: self.Send(target_agent_id, message),
            "check_inbox":   lambda: self.Receive(),
            "broadcast":     lambda message: self.Broadcast(message),
            "report_status": lambda status: self.ReportStatus(status),
            "gather_status": lambda: self.GatherStatus(),
        }

        return {"tools": tools, "handlers": handlers}

    # ------------------------------------------------------------------ #
    # Private methods                                                      #
    # ------------------------------------------------------------------ #

    def _nextSeq(self, targetAgentId):
        """
        Atomically increment and return the tail sequence number for `targetAgentId`.

        Parameters
        ----------
        targetAgentId : str

        Returns
        -------
        int
            The new sequence number, or a millisecond timestamp as a
            fallback if Redis is unreachable.
        """
        try:
            r = redisConnect()
            # HINCRBY is atomic exactly as INCR was, so concurrent senders
            # still get distinct sequence numbers.
            return r.hincrby(self._inboxKey(targetAgentId), _TAIL_FIELD, 1)
        except Exception as e:
            RedisLogger.error(f"[{self.scarletName}] _nextSeq failed: {e}")
            return int(time.time() * 1000)

    def _pollInbox(self, timeout=0):
        """
        Read the next message from this agent's inbox.

        Parameters
        ----------
        timeout : float, optional
            Seconds to poll before giving up. Default `0`.

        Returns
        -------
        dict or None
        """
        try:
            r = redisConnect()
            inbox = self._inboxKey(self.agentId)

            head = int(r.hget(inbox, _HEAD_FIELD) or 0)
            tail = int(r.hget(inbox, _TAIL_FIELD) or 0)

            deadline = time.time() + timeout
            while head >= tail:
                if time.time() >= deadline:
                    return None
                time.sleep(0.1)
                tail = int(r.hget(inbox, _TAIL_FIELD) or 0)

            next_seq = head + 1
            # Retry briefly: the tail field is incremented before the
            # payload field is written, so the first read can race with the
            # sender's hset. Only that race - a payload cannot expire out
            # from under its own cursors now that both live in this one key.
            raw = r.hget(inbox, str(next_seq))
            if raw is None:
                for _ in range(50):   # up to 500 ms
                    time.sleep(0.01)
                    raw = r.hget(inbox, str(next_seq))
                    if raw is not None:
                        break
            if raw is None:
                return None

            self._ack(r, next_seq)
            return json.loads(raw)

        except Exception as e:
            RedisLogger.error(f"[{self.scarletName}] _pollInbox failed: {e}")
            return None

    def _ack(self, r, seqNum):
        """
        Advance the head pointer to mark `seqNum` as consumed.

        Parameters
        ----------
        r : redis.Redis
            Open Redis connection.
        seqNum : int
        """
        try:
            inbox = self._inboxKey(self.agentId)
            r.hset(inbox, _HEAD_FIELD, seqNum)
            # Reading is activity too - an inbox being drained is live.
            r.expire(inbox, self._expiry)
        except Exception as e:
            RedisLogger.error(f"[{self.scarletName}] _ack failed: {e}")

    def _startHeartbeat(self, interval=_HEARTBEAT_INTERVAL):
        """
        Start a background daemon thread that refreshes the registry every `interval` seconds.

        Uses `ReportStatus` with the last-known status dict when
        available, so capabilities set by the application aren't
        silently erased by the liveness tick.

        Parameters
        ----------
        interval : float, optional
            Seconds between heartbeats. Default `30`.
        """
        def _beat():
            while True:
                time.sleep(interval)
                try:
                    if self._last_status is not None:
                        self.ReportStatus(self._last_status)
                    else:
                        self.Register()
                    # This agent's own inbox, on the same tick as its
                    # registration. Without it an inbox is only renewed by
                    # a Send into it or a Receive out of it, so an agent
                    # that is alive and registered but has been quiet for
                    # longer than the TTL loses its queue - including any
                    # message already waiting in it - while its own
                    # registration says it is online. Verified directly:
                    # the inbox expired at t+60 on a bus whose definition
                    # and registrations the heartbeat had just renewed.
                    #
                    # Renewing only *this* agent's inbox, not every inbox
                    # on the bus, is what keeps the two consistent: an
                    # inbox belongs to its recipient, so it lives while
                    # that recipient does and expires with it. An inbox
                    # addressed to an agent that never registered, or has
                    # stopped, expires alongside the registration it never
                    # had or no longer refreshes.
                    r = redisConnect()
                    r.expire(self._inboxKey(self.agentId), self._expiry)
                    # The registration write above renews its own TTL; this
                    # renews the bus's definition on the same tick, so a
                    # bus's catalog entry and its members expire together
                    # rather than one outliving the other.
                    touch_scarlet_definition(
                        scarlet_name=self.scarletName,
                        expiry=self._expiry,
                        scarlet_type="messaging",
                        description=self._description,
                        attributes={"mode": "redis-scarlet"},
                    )
                except Exception as e:
                    RedisLogger.error(f"[{self.scarletName}] heartbeat failed: {e}")

        t = threading.Thread(target=_beat, name=f"Heartbeat-{self.scarletName}", daemon=True)
        t.start()
