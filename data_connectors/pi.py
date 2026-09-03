"""
PiConnector — adapts the real, already-existing PITalk package
(dockerApps/PITalk, https://github.com/blockalytics/PITalk), not a
reimplementation: same PI Web API AF-server attribute/stream read path
(PIServer + PIAttribute.read_attribute_stream()).

Unlike MssqlConnector's open-ended raw-SQL query, PITalk's own config
format (PITALK_CONFIG_FILE, read once by PITalk.__init__) pre-declares
exactly which tags/element/database/AF-server this broker is allowed to
read - see PITalk/pitalk_config.yaml for the real shape (AF server URL,
security method/credential, and a tag/element/database list per group).
So a query payload here only ever selects among tags this broker's own
deployment already declared in that file, plus an optional start_time/
end_time override (PI relative-time syntax, e.g. "*-1h"/"*") - it can
never read an arbitrary, un-configured tag. This narrower query surface
is a real security property, not a limitation carried over by accident.
Same "credential lives entirely in this broker's own deployment, never in
composer-api" pattern as MssqlConnector's Kerberos keytab: the mounted
pitalk_config.yaml holds the AF server's own basic/kerberos/token
credential.

query() returns {"columns": [...], "rows": [[...], ...]} - same shape
MssqlConnector returns - built from PIAttribute.read_attribute_stream()'s
own DataFrame (columns: Timestamp, Value). Verified (this session) that
that DataFrame's values are already plain Python str/float, not numpy
scalars, since it's built straight from a parsed JSON list of dicts - the
same defensive coercion MssqlConnector uses for pyodbc's non-native types
is kept here anyway as a cheap safety net, not because it was observed to
be needed.

PITalk's own setup.py pins pandas==1.3.2/pyYAML==5.4.1/etc. - versions
with no installable wheel for a modern Python (confirmed this session).
This connector installs the real `pitalk` package itself with --no-deps
(mirroring PITalk's own Dockerfile, which already does exactly this) and
lets broker/requirements.txt supply modern, compatible versions instead -
verified (this session) that PIAttribute/PIServer/PITalk import and run
unchanged against pandas 3.x/pyyaml 6.x/requests-kerberos 0.15.x.
"""
import os

from data_connectors.base import Connector


def _json_safe(v):
    """
    Coerce one PI attribute-stream value to something JSON-serializable.

    Parameters
    ----------
    v : object
        A single cell value from `PIAttribute.read_attribute_stream`'s
        result `DataFrame`.

    Returns
    -------
    str, int, float, bool, or None
        `v` unchanged if already a JSON-safe scalar type; `None` if `v`
        was `None`; `str(v)` otherwise. Kept as a cheap safety net even
        though this DataFrame's values were confirmed to already be
        plain Python types, not numpy scalars.
    """
    if v is None:
        return None
    if hasattr(v, "item"):  # a numpy scalar, if pandas ever returns one here
        v = v.item()
    return v if isinstance(v, (str, int, float, bool)) else str(v)


class PiConnector(Connector):
    """
    `Connector` for OSIsoft PI via the `pitalk` package (PI Web API).

    Unlike the SQL connectors' open-ended raw-SQL query, `pitalk`'s own
    config file (``PITALK_CONFIG_FILE``) pre-declares exactly which
    tags/element/database/AF-server this connector is allowed to read -
    see `pitalk`'s ``pitalk_config.yaml`` for the shape (AF server URL,
    security method/credential, and a tag/element/database list per
    group). A query here only ever selects among tags already declared
    in that file, plus an optional ``start_time``/``end_time`` override -
    it can never read an arbitrary, un-configured tag. This narrower
    query surface is a real security property, not an incidental
    limitation. The AF server's own basic/kerberos/token credential lives
    entirely in the mounted `pitalk_config.yaml`, never in composer-api.

    Parameters
    ----------
    config : dict or None, optional
        Per-instance config dict (`local_config.py`, `mode: local`
        entries) with an optional ``pitalk_config_file`` key. When given,
        ``PITALK_CONFIG_FILE`` is set to that path for the duration of
        construction only, then restored to its previous value (not left
        clobbered, since a single worker can hold more than one local PI
        entry). When `None` (the broker's own usage), `pitalk.PITalk` is
        constructed against whatever ``PITALK_CONFIG_FILE`` is already
        set process-wide.

    Attributes
    ----------
    _pitalk : pitalk.PITalk.PITalk
        The underlying `PITalk` instance, holding the declared
        tag/attribute list this connector is allowed to query.
    """

    def __init__(self, config: dict | None = None):
        # PITalk() itself only ever reads PITALK_CONFIG_FILE from
        # os.environ - it has no constructor argument for this at all
        # (real, external code, not something to modify here). When a
        # config dict is given (local_config.build_connector()), its
        # `pitalk_config_file` value is set as that env var just for the
        # duration of this one construction, then the previous value (if
        # any) is restored - not left clobbered, since a single worker
        # could hold more than one local PI entry. No config dict (the
        # broker's own construction, unchanged) just uses whatever
        # PITALK_CONFIG_FILE is already set process-wide, exactly as
        # before.
        from pitalk.PITalk import PITalk

        pitalk_config_file = (config or {}).get("pitalk_config_file")
        if pitalk_config_file:
            previous = os.environ.get("PITALK_CONFIG_FILE")
            os.environ["PITALK_CONFIG_FILE"] = pitalk_config_file
            try:
                self._pitalk = PITalk()
            finally:
                if previous is None:
                    os.environ.pop("PITALK_CONFIG_FILE", None)
                else:
                    os.environ["PITALK_CONFIG_FILE"] = previous
        else:
            self._pitalk = PITalk()

    def query(self, payload: dict) -> dict:
        """
        Read a declared PI attribute's data stream.

        Parameters
        ----------
        payload : dict
            Must include a ``tag_name`` key naming a tag already declared
            in this connector's ``pitalk_config.yaml``. Optional
            ``start_time``/``end_time`` keys (PI relative-time syntax,
            e.g. ``"*-1h"``) override the tag's own config-declared
            range.

        Returns
        -------
        dict
            ``{"columns": [...], "rows": [[...], ...]}``, built from
            `PIAttribute.read_attribute_stream`'s result `DataFrame`
            (columns: ``Timestamp``, ``Value``).

        Raises
        ------
        ValueError
            If `payload` has no ``tag_name`` key, or names a tag not
            declared in this connector's config.
        RuntimeError
            If the PI Web API call itself fails (non-200 response).
        """
        tag_name = payload.get("tag_name")
        if not tag_name:
            raise ValueError("payload must include a 'tag_name' string")
        if tag_name not in self._pitalk.attribute_list:
            raise ValueError(
                f"tag {tag_name!r} is not declared in this broker's pitalk_config.yaml "
                f"(available: {sorted(self._pitalk.attribute_list.keys())})"
            )

        attribute = self._pitalk.attribute_list[tag_name]
        # Optional per-request time-range override, PI relative-time syntax
        # (e.g. "*-1h") - falls back to the tag's own config-declared
        # start_time/end_time if not given.
        attribute.start_time = payload.get("start_time", attribute.start_time)
        attribute.end_time = payload.get("end_time", attribute.end_time)

        df, status_code = attribute.read_attribute_stream()
        if status_code != 200 or df is None:
            raise RuntimeError(f"PI Web API returned HTTP {status_code} for tag {tag_name!r}")

        columns = list(df.columns)
        rows = [[_json_safe(v) for v in row] for row in df.values.tolist()]
        return {"columns": columns, "rows": rows}

    def list_tags(self) -> list:
        """
        List declared PI tags.

        The declared tag list itself, already in memory from `__init__` -
        no query against PI Web API needed at all, unlike every other
        connector's `list_tags`.

        Returns
        -------
        list of str
            Sorted tag names this connector is allowed to query.
        """
        return sorted(self._pitalk.attribute_list.keys())
