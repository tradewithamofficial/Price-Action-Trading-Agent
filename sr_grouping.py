"""Small shared chart lock and read-only drawing/group readbacks.

Codex owns analysis and drawing/group creation. This module never mutates charts.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import subprocess
import uuid

GROUP_NAME = "Support And Resistance Levels"
SETUP_GROUP_NAMES = tuple(f"Price Action Setup {n}" for n in range(1, 4))


def record_directory():
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "TradeWithAM" / "SupportResistanceAgent" / "runs"


def target_identity(value):
    target = json.loads(value) if isinstance(value, str) else value
    keys = {"tab_id", "url", "chart_id", "pane_index", "layout", "symbol", "chart_type"}
    if (not isinstance(target, dict) or set(target) != keys
            or not all(isinstance(target[k], str) and target[k] for k in ("tab_id", "url", "chart_id", "layout", "symbol"))
            or type(target["pane_index"]) is not int or target["pane_index"] != 0
            or type(target["chart_type"]) is not int or target["chart_type"] != 1
            or not re.fullmatch(r"[A-Za-z0-9_]+:[A-Za-z0-9_.!/-]+", target["symbol"])):
        raise ValueError("Exact approved single-chart candlestick identity is required.")
    return dict(target)


# Fixed read-only operation. No model-supplied JavaScript or drawing commands.
_SNAPSHOT = r"""(() => {
 const p = __TARGET__, api = window.TradingViewApi;
 const c = api._activeChartWidgetWV.value(), collection = api._chartWidgetCollection;
 const all = collection.getAll();
 const layout = collection._layoutType && typeof collection._layoutType.value === 'function'
   ? collection._layoutType.value() : collection._layoutType;
 if (location.href !== p.url || location.pathname.split('/')[2] !== p.chart_id
     || all.length !== 1 || all[0] !== c._chartWidget || p.pane_index !== 0
     || layout !== p.layout || c.symbol() !== p.symbol || c.chartType() !== 1)
   throw new Error('Approved chart/layout/pane/symbol mismatch');
 const g = c.shapesGroupController();
 return {target:p, resolution:c.resolution(), studies:c.getAllStudies(),
  groups:g.groups().map(id => ({id, name:g.getGroupName(id), ids:g.shapesInGroup(id).slice().sort()})),
  drawings:c.getAllShapes().map(s => { const d=c.getShapeById(s.id);
   return {id:s.id, shape:s.name, points:d.getPoints(), properties:d.getProperties()}; })};
})()"""


class ChartSession:
    def __init__(self, target, verify_chart, connector, node, *, directory=None):
        self.target = target_identity(target)
        self.verify_chart = verify_chart
        self.connector, self.node = Path(connector), node
        self.directory = Path(directory) if directory is not None else record_directory()

    @contextmanager
    def exclusive(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        lock = self.directory / "analysis.lock"
        try:
            fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            raise ValueError("Another run or unfinished run holds analysis.lock. Inspect the chart before removing a stale lock.") from None
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(uuid.uuid4().hex)
            yield
        finally:
            lock.unlink()

    def snapshot(self):
        if target_identity(self.verify_chart(self.target["symbol"])) != self.target:
            raise ValueError("Approved TradingView target changed; readback stopped.")
        script = _SNAPSHOT.replace("__TARGET__", json.dumps(self.target, ensure_ascii=True, allow_nan=False), 1)
        result = subprocess.run(
            [self.node, str(self.connector / "src" / "cli" / "index.js"), "ui", "eval", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=self.connector,
            timeout=25, stdin=subprocess.DEVNULL, shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            raise ValueError(result.stderr.strip() or "Read-only chart snapshot unavailable.")
        data = json.loads(result.stdout)
        if data.get("success") is not True or not isinstance(data.get("result"), dict):
            raise ValueError("Read-only chart snapshot unavailable.")
        if target_identity(self.verify_chart(self.target["symbol"])) != self.target:
            raise ValueError("Target changed during readback.")
        snapshot = data["result"]
        if (snapshot.get("target") != self.target or not isinstance(snapshot.get("resolution"), str)
                or any(not isinstance(snapshot.get(key), list) for key in ("drawings", "groups", "studies"))):
            raise ValueError("Incomplete read-only chart snapshot.")
        return snapshot


def verify_readbacks(before, after, *, trade, levels, response):
    """Corroborate actual objects/groups; never derive market levels or create geometry."""
    if before["target"] != after["target"] or before["resolution"] != after["resolution"]:
        raise ValueError("Chart identity or original timeframe was not restored.")
    drawings = {d["id"]: d for d in after["drawings"]}
    old = {d["id"]: d for d in before["drawings"]}
    if len(drawings) != len(after["drawings"]) or len(old) != len(before["drawings"]):
        raise ValueError("Duplicate drawing IDs make readback ambiguous.")
    changed = [key for key, value in old.items() if drawings.get(key) != value]
    if changed:
        raise ValueError("Existing drawings changed or disappeared: " + ", ".join(changed))
    if {s["id"]: s for s in before["studies"]} != {s["id"]: s for s in after["studies"]}:
        raise ValueError("Existing indicators changed.")
    groups = {g["id"]: g for g in after["groups"]}
    if len(groups) != len(after["groups"]):
        raise ValueError("Duplicate group IDs make readback ambiguous.")
    if any(groups.get(g["id"]) != g for g in before["groups"]):
        raise ValueError("An existing Object Tree group changed; operator review required.")
    new_ids = set(drawings) - set(old)
    new_groups = [g for g in after["groups"] if g["id"] not in {x["id"] for x in before["groups"]}]
    no_setup = bool(re.search(r"\bNO VALID SETUP\b|\bNO TRADE\s*/\s*WAIT\b", response, re.I))
    if trade and no_setup and not new_ids and not new_groups:
        return "No new drawings/groups; existing objects and original timeframe verified unchanged."
    if not new_ids or not new_groups:
        raise ValueError("No independently verified new drawings and groups were found.")
    if not trade:
        if len(new_groups) != 1 or new_groups[0]["name"] != GROUP_NAME:
            raise ValueError("The requested S/R group was not independently verified.")
        price_shapes = [drawings[key] for key in new_ids
                        if drawings[key]["shape"] in ("horizontal_line", "rectangle")]
        if len(price_shapes) < 2 * levels:
            raise ValueError("Not enough new S/R lines/zones were independently read back.")
    elif len(new_groups) > 3 or any(not re.match(r"^Price Action Setup [123](?:$|[ (—-])", g["name"]) for g in new_groups):
        raise ValueError("Unexpected new setup group names or count.")
    covered = set()
    for group in new_groups:
        members = set(group["ids"])
        if not members or len(members) != len(group["ids"]) or not members <= new_ids:
            raise ValueError("New group contains missing, duplicate or pre-existing objects.")
        if covered & members:
            raise ValueError("New drawing membership is ambiguous.")
        covered |= members
    if covered != new_ids:
        raise ValueError("Some new drawings are not in the expected new groups.")
    return (f"Read back {len(new_ids)} new objects in {len(new_groups)} new group(s). "
            "Existing objects/groups/indicators and original timeframe are unchanged. "
            "This verifies chart objects, not analytical quality or trade outcomes.")
