"""Fixed, application-owned TradingView operations. No model-supplied JavaScript."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import subprocess
import uuid

GROUP_NAME = "Support and Resistance Levels"
SETUP_GROUP_NAMES = tuple(f"Price Action Setup {n}" for n in range(1, 4))
SETUP_COLORS = ("#1565c0", "#7b1fa2", "#ef6c00")


def _field_differences(before, after, path=""):
    """Describe the existing strict comparison; do not normalize/ignore fields."""
    if isinstance(before, dict) and isinstance(after, dict):
        changes = []
        for key in sorted(before.keys() | after.keys()):
            field = f"{path}.{key}" if path else key
            if key not in before or key not in after:
                changes.append({"field": field, "before_present": key in before,
                                "after_present": key in after, "before": before.get(key), "after": after.get(key)})
            else:
                changes.extend(_field_differences(before[key], after[key], field))
        return changes
    if isinstance(before, list) and isinstance(after, list):
        changes = []
        if len(before) != len(after):
            changes.append({"field": path + ".length", "before": len(before), "after": len(after)})
        for index in range(min(len(before), len(after))):
            changes.extend(_field_differences(before[index], after[index], f"{path}[{index}]"))
        return changes
    return [] if before == after else [{"field": path or "$drawing", "before": before, "after": after}]


def record_directory():
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "TradeWithAM" / "SupportResistanceAgent" / "runs"


def target_identity(value):
    target = json.loads(value) if isinstance(value, str) else value
    keys = {"tab_id", "url", "chart_id", "pane_index", "layout", "symbol", "chart_type"}
    if (not isinstance(target, dict) or set(target) != keys
            or not all(isinstance(target[k], str) and target[k] for k in ("tab_id", "url", "chart_id", "layout", "symbol"))
            or target["pane_index"] != 0 or type(target["pane_index"]) is not int
            or target["chart_type"] != 1 or type(target["chart_type"]) is not int
            or not re.fullmatch(r"[A-Za-z0-9_]+:[A-Za-z0-9_.!/-]+", target["symbol"])):
        raise ValueError("Exact approved single-chart identity is required for grouping.")
    return dict(target)


# JSON data is substituted once, never interpreted as code. The operations are
# synchronous so target/object checks precede mutations in the same evaluation.
_SCRIPT = r"""(() => {
 const p = __PAYLOAD__;
 const fail = m => { throw new Error(m); };
 const stable = v => JSON.stringify(v, function(k, x) {
   return x && !Array.isArray(x) && typeof x === 'object'
     ? Object.keys(x).sort().reduce((o,k) => (o[k]=x[k],o), {}) : x;
 });
 const api = window.TradingViewApi;
 const c = api._activeChartWidgetWV.value(), collection = api._chartWidgetCollection;
 const all = collection.getAll();
 const layout = collection._layoutType && typeof collection._layoutType.value === 'function'
   ? collection._layoutType.value() : collection._layoutType;
 if (location.href !== p.target.url || location.pathname.split('/')[2] !== p.target.chart_id
     || all.length !== 1 || all[0] !== c._chartWidget || p.target.pane_index !== 0
     || layout !== p.target.layout || c.symbol() !== p.target.symbol || c.chartType() !== 1)
   fail('Approved chart/layout/pane/symbol mismatch');
 const g = c.shapesGroupController();
 for (const name of ['groups','getGroupName','shapesInGroup','createGroup','setGroupName'])
   if (typeof g[name] !== 'function') fail('Required group API unavailable: '+name);
 const groups = () => g.groups().map(id => ({id, name:g.getGroupName(id), ids:g.shapesInGroup(id).slice().sort()}));
 const shapes = () => c.getAllShapes().map(s => {
   const d = c.getShapeById(s.id);
   return {id:s.id, shape:s.name, points:d.getPoints(), properties:d.getProperties()};
 });
 if (p.operation === 'snapshot') return {target:p.target, resolution:c.resolution(),
   drawings:shapes(), groups:groups(), studies:c.getAllStudies()};
 if (p.operation !== 'create') fail('Unsupported fixed operation');
 if (groups().some(x => x.name === p.name)) fail('Group already exists; operator review required');
 const current = shapes(), members = groups().flatMap(x => x.ids);
 for (const expected of p.drawings) {
   const actual = current.find(x => x.id === expected.id);
   if (!actual || stable(actual) !== stable(expected) || members.includes(expected.id))
     fail('Drawing changed, unavailable or already grouped: '+expected.id);
 }
 const ids = p.drawings.map(x => x.id);
 // This is the sole mutation: new group from this run's verified objects, then
 // naming that returned group ID. Never rename an existing group or move members.
 const id = g.createGroup(ids);
 if (!id) fail('Group creation returned no ID; inspect partial changes');
 try { g.setGroupName(id, p.name); }
 catch (e) { return {id, name:g.getGroupName(id), ids:g.shapesInGroup(id).slice().sort(),
   error:'Group created but naming failed: '+e.message}; }
 return {id, name:g.getGroupName(id), ids:g.shapesInGroup(id).slice().sort()};
})()"""


def fixed_operation(operation, target, *, drawings=None, group_name=GROUP_NAME):
    """Only two operations are accepted. Strings are JSON data, not expressions."""
    target = target_identity(target)
    if operation not in ("snapshot", "create"):
        raise ValueError("Unsupported fixed grouping operation.")
    if group_name not in (GROUP_NAME, *SETUP_GROUP_NAMES):
        raise ValueError("Unsupported application group name.")
    payload = {"operation": operation, "target": target, "name": group_name}
    if operation == "create":
        if not isinstance(drawings, list) or not 1 <= len(drawings) <= 40:
            raise ValueError("A verified nonempty drawing list is required.")
        ids = [x.get("id") for x in drawings]
        if any(not isinstance(x, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", x) for x in ids) or len(set(ids)) != len(ids):
            raise ValueError("Invalid or duplicate drawing IDs.")
        payload["drawings"] = drawings
    # Ensure neither NaN nor executable interpolations can enter the expression.
    return _SCRIPT.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=True, allow_nan=False), 1)


class GroupingSession:
    def __init__(self, target, verify_chart, connector, node, *, directory=None):
        self.target = target_identity(target)
        self.verify_chart = verify_chart
        self.connector, self.node = Path(connector), node
        self.directory = Path(directory) if directory is not None else record_directory()
        self.run_id = uuid.uuid4().hex
        self.path = self.directory / (self.run_id + ".json")
        self.record = {"schema": 1, "run_id": self.run_id, "target": self.target,
                       "created_at": datetime.now(timezone.utc).isoformat(),
                       "drawing_ids": [], "group_id": None, "last_verification_status": "not_started"}

    @contextmanager
    def exclusive(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        lock = self.directory / "analysis.lock"
        try:
            fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            raise ValueError("Another run or an unfinished run holds analysis.lock. Inspect TradingView and the ownership records before operator review/removal of that lock.") from None
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(self.run_id)
            yield
        finally:
            lock.unlink()

    def save(self, status, **values):
        self.record.update(values, last_verification_status=status,
                           verified_at=datetime.now(timezone.utc).isoformat())
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.record, indent=2, allow_nan=False), encoding="utf-8")
        temporary.replace(self.path)

    def call(self, operation, drawings=None, *, group_name=GROUP_NAME):
        # CLI target IDs are not exposed inside page JS. Verify them immediately
        # before/after, and verify page URL/pane/symbol inside the fixed script.
        if target_identity(self.verify_chart(self.target["symbol"])) != self.target:
            raise ValueError("Approved TradingView target changed; grouping stopped.")
        script = fixed_operation(operation, self.target, drawings=drawings, group_name=group_name)
        command = [self.node, str(self.connector / "src" / "cli" / "index.js"), "ui", "eval", script]
        if len(subprocess.list2cmdline(command)) > 30000:
            raise ValueError("Verification payload exceeds Windows command limit; no operation attempted.")
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                cwd=self.connector, timeout=25, stdin=subprocess.DEVNULL, shell=False,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise ValueError(result.stderr.strip() or "Grouping connector failed.")
        data = json.loads(result.stdout)
        if not isinstance(data, dict) or data.get("success") is not True or not isinstance(data.get("result"), dict):
            raise ValueError("Grouping connector returned no verified result.")
        if target_identity(self.verify_chart(self.target["symbol"])) != self.target:
            raise ValueError("Target changed during grouping; inspect partial changes.")
        return data["result"]

    def prepare(self):
        self.before = self.call("snapshot")
        self._snapshot(self.before)
        named = [g for g in self.before["groups"] if g["name"] == GROUP_NAME]
        if named:
            owned = False
            for path in self.directory.glob("*.json"):
                try:
                    record = json.loads(path.read_text(encoding="utf-8"))
                    owned |= (record.get("last_verification_status") == "verified"
                              and record.get("target") == self.target and len(named) == 1
                              and record.get("group_id") == named[0]["id"]
                              and sorted(record.get("drawing_ids", [])) == sorted(named[0]["ids"])
                              and sorted(record.get("drawings", []), key=lambda d:d["id"])
                              == sorted([d for d in self.before["drawings"] if d["id"] in named[0]["ids"]], key=lambda d:d["id"]))
                except (OSError, ValueError, TypeError):
                    continue
            raise ValueError(("An existing owned group was verified. " if owned else "Existing group ownership is ambiguous. ")
                             + "No duplicate analysis or regrouping started; operator review required.")
        self.save("prepared")

    def _snapshot(self, data):
        if (data.get("target") != self.target or not isinstance(data.get("drawings"), list)
                or not isinstance(data.get("groups"), list) or not isinstance(data.get("studies"), list)
                or not isinstance(data.get("resolution"), str)):
            raise ValueError("Incomplete chart snapshot; verification unavailable.")
        ids = [d["id"] for d in data["drawings"]]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate IDs in chart snapshot.")

    def finish(self, response, levels_per_side):
        completion = json.loads(response)
        if (not isinstance(completion, dict) or completion.get("schema") != 1 or completion.get("run_id") != self.run_id
                or completion.get("status") != "complete" or completion.get("errors") != []
                or completion.get("target") != self.target):
            raise ValueError("Missing or mismatched machine-readable completion record.")
        planned = completion.get("drawings")
        if not isinstance(planned, list) or len(planned) != levels_per_side * 2:
            raise ValueError("Completion does not contain every requested support/resistance drawing.")
        ids = [d["id"] for d in planned]
        if len(set(ids)) != len(ids) or any(not isinstance(x, str) for x in ids):
            raise ValueError("Duplicate or invalid completion drawing IDs.")
        if any(sum(d.get("role") == role for d in planned) != levels_per_side for role in ("support", "resistance")):
            raise ValueError("Incomplete support/resistance counts.")
        current = self.call("snapshot")
        self._snapshot(current)
        self._preserved(current)
        if current["groups"] != self.before["groups"]:
            raise ValueError("Groups changed during analysis; no grouping attempted. Operator review required.")
        old = {d["id"] for d in self.before["drawings"]}
        new = {d["id"] for d in current["drawings"]} - old
        if new != set(ids) or old.intersection(ids):
            raise ValueError("Returned IDs do not exactly match this run's new chart objects.")
        verified = []
        for expected in planned:
            actual = next(d for d in current["drawings"] if d["id"] == expected["id"])
            self._drawing(expected, actual)
            verified.append(actual)
        self.save("drawings_verified", drawing_ids=ids, drawings=verified)
        group = self.call("create", verified)  # Exactly once. Never retry/undo.
        self.save("group_created_unverified", group_id=group.get("id"))
        if group.get("error"):
            raise ValueError(group["error"])
        after = self.call("snapshot")
        self._snapshot(after)
        self._preserved(after)
        expected_group = {"id": group.get("id"), "name": GROUP_NAME, "ids": sorted(ids)}
        # Group ordering is not meaningful in the Object Tree API.
        if (not expected_group["id"] or group != expected_group
                or sorted(after["groups"], key=lambda x:x["id"]) != sorted(self.before["groups"] + [expected_group], key=lambda x:x["id"])):
            raise ValueError("Group name or exact membership was not verified.")
        if {d["id"]:d for d in after["drawings"]} != {d["id"]:d for d in current["drawings"]}:
            raise ValueError("Drawings changed during grouping.")
        self.save("verified")
        return self.path

    def _preserved(self, current, allowed_new_names=(GROUP_NAME,)):
        by_id = {d["id"]: d for d in current["drawings"]}
        changed = []
        for drawing in self.before["drawings"]:
            actual = by_id.get(drawing["id"])
            if actual != drawing:  # Preserve the guard's exact original comparison.
                changed.append({"drawing_id": drawing["id"], "missing": actual is None,
                                "groups_before": [g for g in self.before["groups"] if drawing["id"] in g["ids"]],
                                "fields": _field_differences(drawing, actual)})
        if changed:
            evidence = {"comparison": "strict existing drawing equality; no fields ignored",
                        "differences": changed, "before_snapshot": self.before, "after_snapshot": current}
            try:
                # Use the two snapshots already read; never retry or query/mutate
                # the chart to obtain different evidence after a mismatch.
                self.save("preservation_failed", preservation_failure=evidence)
                saved = f" Before/after evidence saved in {self.path}."
            except (OSError, ValueError, TypeError) as exc:
                saved = f" Could not save before/after evidence: {exc}."
            details = "; ".join(item["drawing_id"] + ": " + ("missing" if item["missing"] else
                                ", ".join(field["field"] for field in item["fields"])) for item in changed)
            raise ValueError("An existing drawing changed or disappeared; operator review required. "
                             + "Exact differences: " + details + "." + saved)
        if current["resolution"] != self.before["resolution"] or current["studies"] != self.before["studies"]:
            raise ValueError("Original timeframe or indicators were not preserved.")
        groups = {g["id"]: g for g in current["groups"]}
        if any(groups.get(g["id"]) != g for g in self.before["groups"]):
            raise ValueError("An existing group changed; operator review required.")
        if any(g["id"] not in {x["id"] for x in self.before["groups"]} and g["name"] not in allowed_new_names for g in current["groups"]):
            raise ValueError("Unexpected new group; operator review required.")

    @staticmethod
    def _geometry(expected, actual):
        shape, points, props = expected.get("shape"), expected.get("points"), expected.get("properties")
        if shape not in ("horizontal_line", "rectangle") or actual["shape"] != shape:
            raise ValueError("Drawing geometry mismatch.")
        if not isinstance(points, list) or len(points) != (1 if shape == "horizontal_line" else 2):
            raise ValueError("Incomplete drawing geometry.")
        for point in points:
            if set(point) != {"time", "price"} or any(type(v) not in (int, float) or not math.isfinite(v) for v in point.values()):
                raise ValueError("Invalid drawing coordinates.")
        if points != actual["points"] or not isinstance(props, dict) or not props or any(actual["properties"].get(k) != v for k,v in props.items()):
            raise ValueError("Drawing coordinates/properties do not match readback.")
        if not isinstance(props.get("text"), str) or not props["text"].strip():
            raise ValueError("Drawing label verification missing.")

    @staticmethod
    def _drawing(expected, actual):
        GroupingSession._geometry(expected, actual)
        shape, points, props = expected["shape"], expected["points"], expected["properties"]
        color = "#008000" if expected["role"] == "support" else "#ff0000"
        if props.get("color" if shape == "rectangle" else "linecolor") != color or not isinstance(props.get("text"), str) or not props["text"]:
            raise ValueError("Drawing color/label verification missing.")
        if shape == "rectangle" and ("backgroundColor" not in props or points[0]["price"] == points[1]["price"]):
            raise ValueError("Zone boundary/fill verification missing.")


def read_trade_completion(response, run_id, target):
    """Accept only a completed final-message envelope, never CLI logs."""
    data = json.loads(response)
    if (not isinstance(data, dict) or data.get("schema") != 1 or data.get("run_id") != run_id
            or data.get("target") != target or data.get("status") != "complete" or data.get("errors") != []):
        raise ValueError("Missing or incomplete trade setup final-message record.")
    text, setups, sr_drawings = data.get("final_analysis"), data.get("setups"), data.get("sr_drawings")
    if not isinstance(text, str) or len(text.strip()) < 40:
        raise ValueError("A meaningful final Astra explanation is required.")
    if not isinstance(setups, list) or len(setups) > 3 or not isinstance(sr_drawings, list) or len(sr_drawings) > 6:
        raise ValueError("Expected zero to three setups and at most six optional S/R drawings.")
    if data.get("decision") != ("setups" if setups else "wait"):
        raise ValueError("Trade setup decision and setup count disagree.")
    if not setups and not re.search(r"\b(?:NO TRADE|WAIT)\b", text, re.I):
        raise ValueError("An empty setup result must explain NO TRADE / WAIT.")
    for rank, setup in enumerate(setups, 1):
        if (not isinstance(setup, dict) or type(setup.get("rank")) is not int or setup["rank"] != rank
                or setup.get("direction") not in ("LONG", "SHORT")):
            raise ValueError("Setup ranks must be consecutive and direction must be LONG or SHORT.")
        for field in ("strategy_type", "reasoning", "entry_area", "confirmation", "invalidation", "target1", "cancel_conditions"):
            if not isinstance(setup.get(field), str) or not setup[field].strip():
                raise ValueError("Missing setup explanation field: " + field)
        for field in ("target2", "risk_reward"):
            if field not in setup or (setup[field] is not None and (not isinstance(setup[field], str) or not setup[field].strip())):
                raise ValueError("Unsupported target/R:R must be null, otherwise explained.")
        drawings = setup.get("drawings")
        if not isinstance(drawings, list) or not 4 <= len(drawings) <= 8:
            raise ValueError("Each supported setup needs four to eight real drawings.")
        roles = [d.get("role") for d in drawings]
        if not {"entry", "confirmation", "invalidation", "target1"}.issubset(roles) or any(
                role not in {"entry", "confirmation", "invalidation", "target1", "target2"} for role in roles):
            raise ValueError("Setup drawings must identify entry, confirmation, invalidation and targets.")
    for drawing in sr_drawings:
        if drawing.get("role") not in ("support", "resistance"):
            raise ValueError("Invalid optional S/R drawing role.")
    if any(sum(d["role"] == role for d in sr_drawings) > 3 for role in ("support", "resistance")):
        raise ValueError("At most three new levels per side are permitted.")
    planned = sr_drawings + [d for setup in setups for d in setup["drawings"]]
    ids = [d.get("id") for d in planned]
    if any(not isinstance(eid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", eid) for eid in ids) or len(set(ids)) != len(ids):
        raise ValueError("Invalid or duplicate trade setup drawing IDs.")
    return data


class TradeSetupSession(GroupingSession):
    """Same lock/transport and identity guards; only new named setup groups."""
    def prepare(self):
        self.analysis_completed, self.final_analysis = False, ""
        self.completed_report = None
        self.before = self.call("snapshot")
        self._snapshot(self.before)
        # S/R is context, not an object to adopt or refresh in this workflow.
        # Any setup-name collision stops even when a local record matches.
        for group in self.before["groups"]:
            if group["name"] not in SETUP_GROUP_NAMES:
                continue
            owned = False
            for path in self.directory.glob("*.json"):
                try:
                    record = json.loads(path.read_text(encoding="utf-8"))
                    owned |= (record.get("last_verification_status") == "verified" and record.get("target") == self.target
                              and group in record.get("groups", [])
                              and sorted([d for d in record.get("drawings", []) if d["id"] in group["ids"]], key=lambda d:d["id"])
                              == sorted([d for d in self.before["drawings"] if d["id"] in group["ids"]], key=lambda d:d["id"]))
                except (OSError, ValueError, KeyError, TypeError):
                    continue
            raise ValueError(f"{group['name']}: " + ("existing ownership verified" if owned else "ambiguous ownership")
                             + "; operator review required. No overwrite, adoption or duplicate analysis started.")
        self.save("prepared", kind="trade_setups", groups=[])

    def finish(self, response):
        data = read_trade_completion(response, self.run_id, self.target)
        self.final_analysis = data["final_analysis"].strip()
        self.analysis_completed = True
        # Retain only validated human fields for downstream delivery. No raw
        # completion JSON, drawing metadata, diagnostics or model prompts.
        fields = ("rank", "direction", "strategy_type", "reasoning", "entry_area", "confirmation",
                  "invalidation", "target1", "target2", "risk_reward", "cancel_conditions")
        self.completed_report = {"run_id": self.run_id, "final_analysis": self.final_analysis,
                                 "setups": [{key:setup[key] for key in fields} for setup in data["setups"]]}
        current = self.call("snapshot")
        self._snapshot(current)
        allowed_names = (GROUP_NAME, *SETUP_GROUP_NAMES)
        self._preserved(current, allowed_names)
        by_id = {d["id"]: d for d in current["drawings"]}
        old_ids = {d["id"] for d in self.before["drawings"]}
        batches = []
        if data["sr_drawings"]:
            if any(g["name"] == GROUP_NAME for g in self.before["groups"]):
                raise ValueError("Existing S/R group must be preserved; no new S/R grouping permitted.")
            batches.append((GROUP_NAME, data["sr_drawings"]))
        batches += [(SETUP_GROUP_NAMES[s["rank"] - 1], s["drawings"]) for s in data["setups"]]
        planned = [d for _,drawings in batches for d in drawings]
        ids = [d["id"] for d in planned]
        if set(by_id) - old_ids != set(ids) or old_ids.intersection(ids):
            raise ValueError("Setup completion IDs do not exactly match this run's new objects.")
        if sorted(current["groups"], key=lambda g:g["id"]) != sorted(self.before["groups"], key=lambda g:g["id"]):
            raise ValueError("Groups changed during analysis; grouping stopped.")
        # Validate ALL drawings before creating the first group.
        for name, drawings in batches:
            for drawing in drawings:
                actual = by_id[drawing["id"]]
                if name == GROUP_NAME:
                    self._drawing(drawing, actual)
                else:
                    self._geometry(drawing, actual)
                    props, shape = drawing["properties"], drawing["shape"]
                    if props.get("color" if shape == "rectangle" else "linecolor") != SETUP_COLORS[SETUP_GROUP_NAMES.index(name)]:
                        raise ValueError("Setup drawing color does not match its scenario.")
                    if shape == "rectangle" and ("backgroundColor" not in props or drawing["points"][0]["price"] == drawing["points"][1]["price"]):
                        raise ValueError("Setup area boundaries/fill were not verified.")
        verified = [by_id[eid] for eid in ids]
        created = []
        self.save("drawings_verified", drawing_ids=ids, drawings=verified, groups=created)
        for name, drawings in batches:
            group = self.call("create", [by_id[d["id"]] for d in drawings], group_name=name)
            if group.get("id"):
                created.append({"id": group["id"], "name": group.get("name"), "ids": group.get("ids")})
            self.save("group_created_unverified", groups=created)
            if group.get("error"):
                raise ValueError(group["error"])
            expected = {"id": group.get("id"), "name": name, "ids": sorted(d["id"] for d in drawings)}
            if not expected["id"] or group != expected:
                raise ValueError("Setup group name or membership was not verified.")
            after = self.call("snapshot")
            self._check_result(after, current, created, allowed_names)
        # Also verifies a zero-setup / WAIT result without making any group.
        self._check_result(self.call("snapshot"), current, created, allowed_names)
        self.save("verified", setup_count=len(data["setups"]))
        return len(data["setups"])

    def _check_result(self, after, current, created, allowed_names):
        self._snapshot(after)
        self._preserved(after, allowed_names)
        if (sorted(after["groups"], key=lambda g:g["id"]) != sorted(self.before["groups"] + created, key=lambda g:g["id"])
                or {d["id"]:d for d in after["drawings"]} != {d["id"]:d for d in current["drawings"]}):
            raise ValueError("Setup group membership or drawing preservation verification failed.")


def completion_instructions(session):
    return ("\nAPPLICATION COMPLETION PROTOCOL\n"
            "Do not group drawings yourself. The application will independently verify and group only this run's new drawings "
            f"under '{GROUP_NAME}' using its fixed helper. Do not request ui_evaluate or other tools. "
            "Your final message must be ONLY a JSON object (no Markdown fences), with schema=1, "
            f"run_id={json.dumps(session.run_id)}, target={json.dumps(session.target)}, status='complete' ONLY if "
            "all requested drawings have succeeded and the original timeframe has been restored; otherwise status='incomplete'. "
            "Include summary (brief text), errors (array), and drawings (array). Each drawing must contain id (returned new ID), "
            "role ('support'/'resistance'), shape ('horizontal_line'/'rectangle'), points (actual readback [{time,price}]), "
            "and properties (actual readback style subset including text and linecolor for lines, or text, color and backgroundColor "
            "for rectangles). Include all requested levels exactly once. Never invent IDs/properties. "
            "If a readback is unsupported or a call fails, report incomplete; do not retry or clean up partial changes.\n")
