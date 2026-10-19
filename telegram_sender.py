"""Small Telegram HTML sender, adapted from AI-Trading-Desk/core/telegram_sender.py.

Verified TLS, bounded POST/response and exact acknowledgement checks only.
No callbacks, polling, outbox, scheduling, redirects or automatic retries.
Importing this module reads no configuration and performs no network operation.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import html
import http.client
import json
import math
from pathlib import Path
import re
import socket
import ssl
import sys
import time

MAX_RESPONSE_BYTES = 65536
MAX_MESSAGES = 20
MAX_HTML_UNITS = 4096
DISCLAIMER = "Conditional setup — wait for confirmation."
SETUP_FIELDS = ("rank", "direction", "strategy_type", "reasoning", "entry_area", "confirmation",
                "invalidation", "target1", "target2", "risk_reward", "cancel_conditions")


class TelegramError(ValueError):
    """Only application-owned messages, never URLs/tokens/server descriptions."""


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str = field(repr=False)
    chat_id: str = field(repr=False)

    def __post_init__(self):
        # Reuse the previous project's strict token/numeric destination checks.
        if not isinstance(self.bot_token, str) or not re.fullmatch(r"[1-9][0-9]{0,19}:[A-Za-z0-9_-]{20,200}", self.bot_token):
            raise TelegramError("Invalid bot_token in telegram_config.local.json.")
        if (not isinstance(self.chat_id, str) or not re.fullmatch(r"-?[1-9][0-9]{0,15}", self.chat_id)
                or abs(int(self.chat_id)) > 2**52 - 1):
            raise TelegramError("Set chat_id to the exact numeric destination ID as a JSON string.")


@dataclass(frozen=True)
class DeliveryOutcome:
    status: str
    accepted_parts: int = 0
    required_parts: int = 0
    message_ids: tuple = ()
    error: str = ""

    @property
    def accepted(self):
        return (self.status == "accepted" and self.required_parts > 0
                and self.accepted_parts == self.required_parts
                and len(self.message_ids) == self.required_parts
                and len(set(self.message_ids)) == self.required_parts
                and all(type(eid) is int and eid > 0 for eid in self.message_ids))


def local_config_path():
    # Never resolve relative to PyCharm, Explorer's CWD or PyInstaller _MEIPASS.
    root = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    return root / "telegram_config.local.json"


def load_config(path=None):
    try:
        data = json.loads((Path(path) if path is not None else local_config_path()).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise TelegramError("Missing telegram_config.local.json beside main.py or the EXE.") from None
    except (OSError, ValueError, UnicodeError):
        raise TelegramError("Cannot read a valid telegram_config.local.json. Check its JSON format and permissions.") from None
    if not isinstance(data, dict) or set(data) != {"bot_token", "chat_id"}:
        raise TelegramError("Telegram configuration must contain only bot_token and chat_id.")
    return TelegramConfig(data["bot_token"], data["chat_id"])


def _units(text):
    return len(text.encode("utf-16-le")) // 2


def _paragraphs(text, bold=False, limit=3000):
    """Split raw text first; escape/wrap each fragment so HTML stays balanced."""
    while text:
        low, high = 0, len(text)
        while low < high:
            mid = (low + high + 1) // 2
            if _units(html.escape(text[:mid], quote=True)) + (7 if bold else 0) <= limit:
                low = mid
            else:
                high = mid - 1
        if low == 0:
            raise TelegramError("A report character cannot be encoded within Telegram's message limit.")
        cut = low
        if cut < len(text):
            boundary = max(text.rfind("\n", 0, cut), text.rfind(" ", 0, cut))
            if boundary >= cut // 2:
                cut = boundary + 1
        escaped = html.escape(text[:cut], quote=True)
        yield f"<b>{escaped}</b>" if bold else escaped
        text = text[cut:]


def format_trade_messages(report, symbol, timeframes, *, chart_verified, timestamp=None):
    """Only the validated human fields are used; unknown/internal fields ignored."""
    if (not isinstance(report, dict) or not isinstance(report.get("final_analysis"), str)
            or len(report["final_analysis"].strip()) < 40 or not isinstance(report.get("setups"), list)
            or len(report["setups"]) > 3):
        raise TelegramError("No validated completed trade analysis is available for Telegram.")
    if not isinstance(symbol, str) or not re.fullmatch(r"[A-Za-z0-9_]+:[A-Za-z0-9_.!/-]+", symbol):
        raise TelegramError("Telegram report requires the exact exchange-qualified symbol.")
    if not isinstance(timeframes, (list, tuple)) or not timeframes or any(tf not in ("1H", "4H", "1D", "15m") for tf in timeframes):
        raise TelegramError("Telegram report has invalid analysis timeframes.")
    timestamp = datetime.now(timezone.utc) if timestamp is None else timestamp
    if not isinstance(timestamp, datetime) or timestamp.utcoffset() is None:
        raise TelegramError("An explicit timezone is required for the analysis timestamp.")
    setups = report["setups"]
    if not setups and not re.search(r"\b(?:NO TRADE|WAIT)\b", report["final_analysis"], re.I):
        raise TelegramError("Zero setups must include the final NO TRADE / WAIT assessment.")
    blocks = [(f"Symbol: {symbol}", True),
              (f"Analysis: {timestamp.isoformat(timespec='seconds')}\nTimeframes: {' / '.join(timeframes)}", False)]
    if not chart_verified:
        blocks.append(("Chart drawings/groups: NOT VERIFIED — operator review required. "
                       "Analysis and delivery do not confirm chart completion.", False))
    ranks = ("Primary", "Secondary", "Alternative")
    for index, setup in enumerate(setups, 1):
        if (not isinstance(setup, dict) or type(setup.get("rank")) is not int or setup["rank"] != index
                or setup.get("direction") not in ("LONG", "SHORT")):
            raise TelegramError("Invalid validated setup ranking or direction.")
        for key in SETUP_FIELDS[2:]:
            if key in ("target2", "risk_reward") and setup.get(key) is None:
                continue
            if not isinstance(setup.get(key), str) or not setup[key].strip():
                raise TelegramError("A required human-readable setup field is missing.")
        reasoning = setup['reasoning']
        confirmation = setup['confirmation']
        # Keep structured caveats verbatim inside the requested fields. Risk/reward
        # can contain entry restrictions, so do not guess which words are safe to drop.
        if setup.get('risk_reward') and setup['risk_reward'].strip().casefold() not in reasoning.casefold():
            reasoning += " " + setup['risk_reward']
        if setup['cancel_conditions'].strip().casefold() not in confirmation.casefold():
            confirmation += " Cancel / stand aside: " + setup['cancel_conditions']
        blocks += [(f"Setup {index} — {ranks[index-1]} | {setup['direction']}", True),
                   (f"Strategy: {setup['strategy_type']}", False), (f"Reasoning: {reasoning}", False),
                   (f"Entry area: {setup['entry_area']}", True), (f"Confirmation: {confirmation}", False),
                   (f"Stop / invalidation: {setup['invalidation']}", True), (f"Target 1: {setup['target1']}", True)]
        if setup.get("target2") is not None:
            blocks.append((f"Target 2: {setup['target2']}", True))
    if not setups:
        # No structured setup exists: its final WAIT explanation supplies the reason.
        blocks += [("NO TRADE / WAIT", True), (report["final_analysis"], False)]
    header = "<b>TRADE WITH AM — PRICE ACTION TRADING AGENT</b>\n\n"
    footer = "\n\n<i>" + DISCLAIMER + "</i>"
    # Check the complete compact message first; reserve numbering only if splitting
    # is actually necessary. Retain the conservative raw-HTML length safeguard.
    single = header + "\n\n".join(
        f"<b>{html.escape(text, quote=True)}</b>" if bold else html.escape(text, quote=True)
        for text, bold in blocks) + footer
    if _units(single) <= MAX_HTML_UNITS:
        return [single]
    budget = MAX_HTML_UNITS - _units(header + "Message 20/20\n\n" + footer)
    bodies, body = [], ""
    for text, bold in blocks:
        for piece in _paragraphs(text, bold, limit=budget):
            if body and _units(body + "\n\n" + piece) > budget:
                bodies.append(body)
                body = ""
                if len(bodies) >= MAX_MESSAGES:
                    raise TelegramError("Report exceeds the 20-message safety limit. Use Copy for manual retrieval; nothing was sent.")
            body += ("\n\n" if body else "") + piece
    if body:
        bodies.append(body)
    if not bodies or len(bodies) > MAX_MESSAGES:
        raise TelegramError("Report exceeds the 20-message safety limit. Use Copy for manual retrieval; nothing was sent.")
    messages = [header + f"Message {n}/{len(bodies)}\n\n" + body + footer for n,body in enumerate(bodies, 1)]
    if any(_units(text) > MAX_HTML_UNITS for text in messages):
        raise TelegramError("Report exceeded Telegram's message limit; nothing was sent.")
    return messages


def _request(config, message, timeout_seconds, connection_factory=None):
    """Adapted bounded HTTPS POST from the reference sender; never follows redirects."""
    connection = None
    deadline = time.monotonic() + timeout_seconds

    def remaining():
        budget = deadline - time.monotonic()
        if budget <= 0:
            raise TimeoutError()
        if connection is not None:
            connection.timeout = budget
            if connection.sock is not None:
                connection.sock.settimeout(budget)
        return budget

    try:
        factory = connection_factory or http.client.HTTPSConnection
        connection = factory("api.telegram.org", timeout=remaining(), context=ssl.create_default_context())
        connection.set_debuglevel(0)
        payload = {"chat_id": config.chat_id, "text": message, "parse_mode": "HTML",
                   "link_preview_options": {"is_disabled": True}}
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        connection.request("POST", "/bot" + config.bot_token + "/sendMessage", body=body,
                           headers={"Content-Type": "application/json", "Accept": "application/json"})
        remaining()
        response = connection.getresponse()
        chunks, size = [], 0
        while True:
            remaining()
            chunk = response.read1(min(4096, MAX_RESPONSE_BYTES + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise TelegramError("Telegram response exceeded the size limit; acceptance is unconfirmed. No retry.")
            chunks.append(chunk)
        remaining()
        try:
            data = json.loads(b"".join(chunks).decode("utf-8"))
        except (ValueError, UnicodeError):
            raise TelegramError("Telegram returned an invalid response; acceptance is unconfirmed. No retry.") from None
        if response.status != 200 or not isinstance(data, dict) or data.get("ok") is not True:
            reasons = {400:"Telegram rejected the message or destination.", 401:"Telegram rejected the bot credentials.",
                       403:"Telegram denied access; check bot membership and permissions.", 429:"Telegram rate limited the request."}
            raise TelegramError(reasons.get(response.status, "Telegram did not confirm message acceptance.") + " No automatic retry.")
        result = data.get("result")
        expected_text = html.unescape(re.sub(r"</?(?:b|i)>", "", message))
        if (not isinstance(result, dict) or type(result.get("message_id")) is not int or result["message_id"] <= 0
                or not isinstance(result.get("chat"), dict) or type(result["chat"].get("id")) is not int
                or str(result["chat"]["id"]) != config.chat_id or result.get("text") != expected_text):
            raise TelegramError("Telegram acknowledgement did not match the configured destination/message; delivery is unconfirmed. No retry.")
        return result["message_id"]
    except TelegramError:
        raise
    except (TimeoutError, socket.timeout):
        raise TelegramError("Telegram network timeout; acceptance is unknown. Inspect Telegram before any manual resend. No automatic retry.") from None
    except Exception:
        # Never expose service text, token-bearing paths or raw transport errors.
        raise TelegramError("Telegram network/TLS connection failed; acceptance is unconfirmed. No automatic retry.") from None
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def send_trade_analysis(report, symbol, timeframes, *, chart_verified, live_send_enabled=False,
                        timestamp=None, config_path=None, timeout_seconds=10, connection_factory=None):
    """One attempt per numbered part; stop on first failure, never restart/resend."""
    accepted, messages = [], []
    try:
        if live_send_enabled is not True:
            raise TelegramError("Telegram delivery is disabled; an explicit authorized call is required.")
        if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 30:
            raise TelegramError("Telegram timeout must be between zero and 30 seconds.")
        messages = format_trade_messages(report, symbol, timeframes, chart_verified=chart_verified, timestamp=timestamp)
        config = load_config(config_path)
        if any(config.bot_token in html.unescape(text) for text in messages):
            raise TelegramError("Telegram report contains credentials; delivery blocked.")
        for message in messages:
            message_id = _request(config, message, timeout_seconds, connection_factory)
            if message_id in accepted:
                raise TelegramError("Telegram repeated a previous acknowledgement; this part is unconfirmed. No retry.")
            accepted.append(message_id)
        return DeliveryOutcome("accepted", len(accepted), len(messages), tuple(accepted))
    except TelegramError as exc:
        return DeliveryOutcome("failed", len(accepted), len(messages), tuple(accepted), str(exc))
    except Exception:
        return DeliveryOutcome("failed", len(accepted), len(messages), tuple(accepted),
                               "Telegram delivery could not be confirmed. No automatic retry.")
