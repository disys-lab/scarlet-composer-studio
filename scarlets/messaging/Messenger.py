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
from scarlets.utils.ScarletUtils import redisConnect, register_scarlet_definition


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
        self.Register()
        self._startHeartbeat()
        register_scarlet_definition(
            scarlet_name=scarletName,
            scarlet_type="messaging",
            description=description,
            attributes={"mode": "redis-scarlet"},
        )

    # ------------------------------------------------------------------ #
    # Public API (PascalCase — consistent with Mapper convention)         #
    # ------------------------------------------------------------------ #

    def Send(self, targetAgentId, message):
        """
        Send a message to a specific agent's inbox.

        Messages are stored under sequence-numbered keys:
            <msg_ns>:{targetAgentId}:{seqNum}
        The tail pointer (<msg_ns>:tail:{targetAgentId}) is atomically incremented.
        """
        seq = self._nextSeq(targetAgentId)
        key = f"{self._msg_ns}:{targetAgentId}:{seq}"
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
            r.set(key, json.dumps(payload))
            RedisLogger.debug(f"[{self.scarletName}] {self.agentId} → {targetAgentId} seq={seq}")
        except Exception as e:
            RedisLogger.error(f"[{self.scarletName}] Send failed: {e}")

    def Receive(self, timeout=0):
        """
        Check inbox for messages addressed to this agent.

        Non-blocking by default (timeout=0). Returns the next unread message
        as a dict, or None if the inbox is empty. Automatically acks on return.
        Inbox continuity is preserved across restarts via the head pointer in Redis.
        """
        return self._pollInbox(timeout)

    def Broadcast(self, message):
        """Send a message to all currently registered agents."""
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

        status : dict
            Should include at minimum: {"status": "online", "capabilities": [...]}
        """
        self._last_status = status   # preserve so heartbeat can re-publish
        record = {
            "agent_id":    self.agentId,
            "instance_id": self._instanceId,
            "ts":          time.time(),
            **status,
        }
        try:
            r = redisConnect()
            r.set(f"{self._reg_ns}:{self.agentId}", json.dumps(record))
        except Exception as e:
            RedisLogger.error(f"[{self.scarletName}] ReportStatus failed: {e}")

    def GatherStatus(self):
        """
        Collect registration records from all agents on this bus.
        Returns a dict keyed by agentId.
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
        Called on init and by the heartbeat thread every 30 seconds.
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
            r.set(f"{self._reg_ns}:{self.agentId}", json.dumps(record))
            RedisLogger.debug(f"[{self.scarletName}] {self.agentId} registered (instance={self._instanceId[:8]})")
        except Exception as e:
            RedisLogger.error(f"[{self.scarletName}] Register failed: {e}")

    def clearAll(self):
        """Clear all messages and registry entries for this bus."""
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
        dict with keys:
            "tools"    : list of tool definition dicts (name, description, parameters)
            "handlers" : dict of {tool_name: callable}
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
        """Atomically increment and return the tail sequence number for targetAgentId."""
        try:
            r = redisConnect()
            return r.incr(f"{self._msg_ns}:tail:{targetAgentId}")
        except Exception as e:
            RedisLogger.error(f"[{self.scarletName}] _nextSeq failed: {e}")
            return int(time.time() * 1000)

    def _pollInbox(self, timeout=0):
        """Read the next message from this agent's inbox. Returns dict or None."""
        try:
            r = redisConnect()
            head_key = f"{self._msg_ns}:head:{self.agentId}"
            tail_key = f"{self._msg_ns}:tail:{self.agentId}"

            head = int(r.get(head_key) or 0)
            tail = int(r.get(tail_key) or 0)

            deadline = time.time() + timeout
            while head >= tail:
                if time.time() >= deadline:
                    return None
                time.sleep(0.1)
                tail = int(r.get(tail_key) or 0)

            next_seq = head + 1
            msg_key = f"{self._msg_ns}:{self.agentId}:{next_seq}"
            # Retry briefly: tail is incremented before the payload is written,
            # so the first read can race with the sender's r.set() call.
            raw = r.get(msg_key)
            if raw is None:
                for _ in range(50):   # up to 500 ms
                    time.sleep(0.01)
                    raw = r.get(msg_key)
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
        """Advance the head pointer to mark seqNum as consumed."""
        try:
            r.set(f"{self._msg_ns}:head:{self.agentId}", seqNum)
        except Exception as e:
            RedisLogger.error(f"[{self.scarletName}] _ack failed: {e}")

    def _startHeartbeat(self, interval=30):
        """Start a background daemon thread that refreshes the registry every interval seconds.

        Uses ReportStatus with the last-known status dict when available so that
        capabilities set by the application are not silently erased by the liveness tick.
        """
        def _beat():
            while True:
                time.sleep(interval)
                try:
                    if self._last_status is not None:
                        self.ReportStatus(self._last_status)
                    else:
                        self.Register()
                except Exception as e:
                    RedisLogger.error(f"[{self.scarletName}] heartbeat failed: {e}")

        t = threading.Thread(target=_beat, name=f"Heartbeat-{self.scarletName}", daemon=True)
        t.start()
