#!/usr/bin/env python3
"""Svapo Consapevole: server dell'add-on per Home Assistant.

Tiene lo stato (impostazioni, storico, ciclo in corso), fa scorrere i timer anche
a telefono bloccato e parla con te tramite notifiche con pulsanti:

    pausa finita -> "È ora della sigaretta" [Inizia]   (di notte, 23-8, si aspetta la mattina)
    sessione     -> timer
    sessione finita -> "Hai finito?" [Sì, ho finito] -> parte la pausa

I tocchi sui pulsanti arrivano dal websocket di Home Assistant (evento
mobile_app_notification_action). L'unica dipendenza esterna è websocket-client.
"""
import json
import os
import secrets
import signal
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DATA_DIR = Path(os.environ.get("SVAPO_DATA", "/data"))
WEB_DIR = Path(os.environ.get("SVAPO_WEB", Path(__file__).resolve().parent / "web"))
PORT = int(os.environ.get("SVAPO_PORT", "8099"))
HA_API = os.environ.get("SVAPO_HA_API", "http://supervisor/core/api").rstrip("/")
HA_WS = os.environ.get("SVAPO_HA_WS", "ws://supervisor/core/websocket")
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
WS_BACKOFF_MAX = float(os.environ.get("SVAPO_WS_BACKOFF_MAX", "60"))
# Dentro Home Assistant, solo il gateway ingress del Supervisor può parlare con l'add-on.
INGRESS_PEERS = {"172.30.32.2", "127.0.0.1", "::1"}
MAX_LOG = 400
TAG = "svapo-ciclo"  # una sola notifica alla volta: ogni messaggio sostituisce il precedente

DEFAULT_SETTINGS = {
    "sessionMin": 6,
    "puffSec": 35,
    "cooldownMin": 45,
    "goal": 8,
    "gradual": False,
    "gradualStep": 5,
    "gradualStart": None,
    "vibrate": True,
    "sound": True,
    "quiet": True,        # orario di riposo: niente notifiche, il ciclo aspetta la mattina
    "quietFrom": 23 * 60,  # minuti dalla mezzanotte
    "quietTo": 8 * 60,
}
LIMITS = {
    "sessionMin": (3, 15),
    "puffSec": (15, 90),
    "cooldownMin": (10, 180),
    "goal": (1, 30),
    "gradualStep": (1, 30),
    "quietFrom": (0, 1439),
    "quietTo": (0, 1439),
}
BOOLS = ("gradual", "vibrate", "sound", "quiet")

lock = threading.RLock()
stop_event = threading.Event()
state = {"settings": dict(DEFAULT_SETTINGS), "log": [], "run": None}
options = {
    "notify_services": [],
    "reminder_minutes": 3,
    "start_reminders": 3,
    "end_reminders": 10,
    "interruption_level": "time-sensitive",
}
timer = None
ws_ok = False
test_tap = {"id": None, "at": None}


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def now_ms():
    return int(time.time() * 1000)


# ---------- opzioni e stato ----------

def load_options():
    opts = dict(options)
    try:
        with open(DATA_DIR / "options.json", encoding="utf-8") as f:
            data = json.load(f)
        for k in opts:
            if k in data:
                opts[k] = data[k]
    except (OSError, ValueError):
        pass
    services = []
    for s in opts["notify_services"] or []:
        s = str(s).strip()
        if s.startswith("notify."):
            s = s[len("notify."):]
        if s:
            services.append(s)
    opts["notify_services"] = services
    for key, lo, kind in (("reminder_minutes", 0.01, float), ("start_reminders", 0, int), ("end_reminders", 0, int)):
        try:
            opts[key] = max(lo, kind(opts[key]))
        except (TypeError, ValueError):
            opts[key] = options[key]
    if opts["interruption_level"] not in ("active", "time-sensitive"):
        opts["interruption_level"] = "time-sensitive"
    return opts


def load_state():
    try:
        with open(DATA_DIR / "state.json", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        return
    if isinstance(data.get("settings"), dict):
        state["settings"] = {**DEFAULT_SETTINGS, **data["settings"]}
    if isinstance(data.get("log"), list):
        state["log"] = data["log"][-MAX_LOG:]
    run = data.get("run")
    if isinstance(run, dict) and run.get("phase") in ("session", "cooldown", "prompt_start", "prompt_end"):
        state["run"] = run


def save_state():
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = DATA_DIR / "state.json.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, DATA_DIR / "state.json")
    except OSError as e:
        log(f"Impossibile salvare lo stato: {e}")


# ---------- utilità ----------

def fmt_min(m):
    m = round(m)
    if m >= 60:
        h, r = divmod(m, 60)
        return f"{h} h" + (f" {r} min" if r else "")
    return f"{m} min"


def hhmm(ts_ms):
    return time.strftime("%H:%M", time.localtime(ts_ms / 1000))


def remind_ms():
    return int(options["reminder_minutes"] * 60000)


def cooldown_minutes(at):
    s = state["settings"]
    m = s["cooldownMin"]
    if s["gradual"] and s.get("gradualStart"):
        weeks = max(0, int((at - s["gradualStart"]) // (7 * 86_400_000)))
        m += weeks * s["gradualStep"]
    return min(m, 600)


# ---------- orario di riposo ----------

def ensure_timezone():
    """Il Supervisor di solito passa TZ all'add-on; se manca la chiedo a Home Assistant."""
    if os.environ.get("TZ") or not SUPERVISOR_TOKEN:
        return
    try:
        req = urllib.request.Request(f"{HA_API}/config", headers={"Authorization": f"Bearer {SUPERVISOR_TOKEN}"})
        with urllib.request.urlopen(req, timeout=10) as r:
            tz = json.load(r).get("time_zone")
        if tz:
            os.environ["TZ"] = tz
            time.tzset()
    except Exception as e:
        log(f"Fuso orario non letto da Home Assistant: {e}")


def is_quiet(ts_ms):
    s = state["settings"]
    if not s.get("quiet"):
        return False
    a, b = int(s["quietFrom"]), int(s["quietTo"])
    if a == b:
        return False
    lt = time.localtime(ts_ms / 1000)
    m = lt.tm_hour * 60 + lt.tm_min
    return a <= m < b if a < b else (m >= a or m < b)


def quiet_end(ts_ms):
    """Il primo momento dopo ts_ms in cui finisce la fascia di riposo."""
    b = int(state["settings"]["quietTo"])
    d = datetime.fromtimestamp(ts_ms / 1000).replace(hour=b // 60, minute=b % 60, second=0, microsecond=0)
    if d.timestamp() * 1000 <= ts_ms:
        d += timedelta(days=1)
    return int(d.timestamp() * 1000)


def cooldown_run(until):
    """Pausa che finisce a `until`; se cade nella fascia di riposo slitta alla fine della fascia."""
    if is_quiet(until):
        return {"phase": "cooldown", "until": quiet_end(until), "morning": True}
    return {"phase": "cooldown", "until": until}


# ---------- notifiche ----------

def _broadcast(payload):
    """Manda la stessa richiesta a tutti i servizi configurati. Ritorna (inviate, motivo)."""
    services = options["notify_services"]
    if not services:
        return 0, "Nessun dispositivo configurato nelle opzioni dell'add-on."
    if not SUPERVISOR_TOKEN:
        return 0, "Token del Supervisor non disponibile."
    body = json.dumps(payload).encode("utf-8")
    sent = 0
    reason = ""
    for svc in services:
        req = urllib.request.Request(
            f"{HA_API}/services/notify/{svc}",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10):
                sent += 1
        except urllib.error.HTTPError as e:
            reason = f"Servizio notify.{svc} non raggiungibile (HTTP {e.code}). Controlla il nome nelle opzioni."
            log(reason)
        except (urllib.error.URLError, OSError) as e:
            reason = f"Home Assistant non risponde: {e}"
            log(reason)
    return sent, reason


def send_notification(title, message, tag=TAG, actions=None, silent=False):
    data = {"tag": tag, "ttl": 0, "priority": "high"}
    if silent:
        data["push"] = {"sound": "none"}
    else:
        data["push"] = {"interruption-level": options["interruption_level"]}
    if actions:
        data["actions"] = actions
    return _broadcast({"title": title, "message": message, "data": data})


def clear_notification(tag=TAG):
    return _broadcast({"message": "clear_notification", "data": {"tag": tag}})


def _dispatch(msgs):
    for m in msgs:
        try:
            if m[0] == "clear":
                clear_notification(m[1])
            else:
                _, title, message, kwargs = m
                send_notification(title, message, **kwargs)
        except Exception as e:  # una notifica persa non deve fermare il ciclo
            log(f"Notifica non inviata: {e}")


def dispatch(msgs):
    if msgs:
        threading.Thread(target=_dispatch, args=(msgs,), daemon=True).start()


def prompt_msg(run, reminder=0):
    """Notifica con il pulsante per la fase di attesa in corso."""
    if run["phase"] == "prompt_start":
        title, message, label, action = (
            "Buongiorno, è ora della sigaretta" if run.get("morning") else "È ora della sigaretta",
            "Tocca Inizia quando sei pronto.", "Inizia", f"SVAPO_START:{run['id']}")
        total = options["start_reminders"]
    else:
        title, message, label, action = (
            "Sessione finita", "Hai finito?", "Sì, ho finito", f"SVAPO_END:{run['id']}")
        total = options["end_reminders"]
    if reminder:
        message = f"{message} Ti aspetto (promemoria {reminder} di {total})."
    return ("notify", title, message, {"actions": [{"action": action, "title": label}]})


# ---------- timer ----------

def next_due(run):
    ph = run["phase"]
    if ph == "session":
        return run["start"] + run["sessionMs"]
    if ph == "cooldown":
        return run["until"]
    return run.get("nextAt")


def schedule():
    """Arma il timer sul prossimo evento. Va chiamata con il lock preso."""
    global timer
    if timer:
        timer.cancel()
        timer = None
    run = state["run"]
    if not run:
        return
    due = next_due(run)
    if due is None:
        return
    timer = threading.Timer(max(0.05, (due - now_ms()) / 1000), on_timer)
    timer.daemon = True
    timer.start()


def _enter_prompt(phase, t, **extra):
    state["run"] = {"phase": phase, "id": secrets.token_hex(3), "since": t,
                    "reminders": 0, "nextAt": t + remind_ms(), **extra}
    return state["run"]


def _confirm_end_locked(t, auto=False, quiet=False):
    """Chiude la sessione in attesa di conferma e avvia la pausa da adesso."""
    run = state["run"]
    state["log"].append({"t": run["start"], "d": round(run["sessionMs"] / 1000),
                         "k": "early" if run.get("early") else "ok"})
    del state["log"][:-MAX_LOG]
    cool = cooldown_minutes(t)
    state["run"] = cooldown_run(t + int(cool * 60000))
    until = state["run"]["until"]
    why = " in orario di riposo, senza avvisi" if quiet else (" senza risposta" if auto else "")
    log(f"Sessione chiusa{why}, prossima sigaretta alle {hhmm(until)}")
    return until


def pause_msg(until, auto=False, morning=False):
    text = f"Prossima sigaretta alle {hhmm(until)}."
    if morning:
        text = f"Orario di riposo: ti riscrivo alle {hhmm(until)}."
    if auto:
        text += " Non hai risposto, ho chiuso io la sessione."
    return ("notify", "Pausa iniziata", text, {"silent": True})


def on_timer():
    msgs = []
    with lock:
        t = now_ms()
        for _ in range(8):  # un giro per ogni fase scaduta, con un tetto di sicurezza
            run = state["run"]
            if not run:
                break
            due = next_due(run)
            if due is None or due > t:
                break
            ph = run["phase"]
            if ph == "session":
                end = run["start"] + run["sessionMs"]
                new = _enter_prompt("prompt_end", t, start=run["start"], sessionMs=run["sessionMs"],
                                    early=bool(run.get("early")), endedAt=end)
                if is_quiet(t):
                    _confirm_end_locked(t, auto=True, quiet=True)
                else:
                    log("Sessione finita, aspetto la conferma")
                    msgs.append(prompt_msg(new))
            elif ph == "cooldown":
                if is_quiet(t):  # la fascia di riposo è cambiata mentre la pausa scorreva
                    state["run"] = cooldown_run(t)
                    log("Orario di riposo: aspetto la mattina")
                else:
                    new = _enter_prompt("prompt_start", t, morning=bool(run.get("morning")))
                    log("Pausa finita, aspetto che tu inizi")
                    msgs.append(prompt_msg(new))
            elif ph == "prompt_start":
                if is_quiet(t):
                    state["run"] = cooldown_run(t)
                    log("Orario di riposo: la richiesta di iniziare slitta alla mattina")
                    msgs.append(("clear", TAG))
                elif run["reminders"] >= options["start_reminders"]:
                    state["run"] = None
                    log("Nessuna risposta: la sessione non parte")
                    msgs.append(("clear", TAG))
                else:
                    run["reminders"] += 1
                    run["nextAt"] = t + remind_ms()
                    msgs.append(prompt_msg(run, run["reminders"]))
            elif ph == "prompt_end":
                if is_quiet(t):
                    _confirm_end_locked(t, auto=True, quiet=True)
                    msgs.append(("clear", TAG))
                elif run["reminders"] >= options["end_reminders"]:
                    until = _confirm_end_locked(t, auto=True)
                    msgs.append(pause_msg(until, auto=True, morning=bool(state["run"].get("morning"))))
                else:
                    run["reminders"] += 1
                    run["nextAt"] = t + remind_ms()
                    msgs.append(prompt_msg(run, run["reminders"]))
        save_state()
        schedule()
    dispatch(msgs)


# ---------- comandi ----------

def start_session(early=False, expect_id=None):
    """Ritorna None se va bene, altrimenti il motivo del rifiuto."""
    msgs = []
    with lock:
        run = state["run"]
        ph = run["phase"] if run else None
        if expect_id and (ph != "prompt_start" or run.get("id") != expect_id):
            return "Richiesta scaduta."
        if ph == "session":
            return None
        if ph == "prompt_end":
            return "Conferma prima la sessione finita."
        if ph == "cooldown" and not early:
            return "Pausa in corso."
        s = state["settings"]
        session_ms = int(s["sessionMin"] * 60000)
        puff_ms = int(s["puffSec"] * 1000)
        state["run"] = {
            "phase": "session",
            "start": now_ms(),
            "early": bool(early),
            "sessionMs": session_ms,
            "puffMs": puff_ms,
            "lastPuff": -1,
        }
        save_state()
        schedule()
        log("Sessione iniziata" + (" (fuori programma)" if early else ""))
        if ph == "prompt_start":
            puffs = max(1, session_ms // puff_ms)
            msgs.append(("notify", "Sessione iniziata",
                         f"{fmt_min(session_ms / 60000)} e circa {puffs} tiri. Con calma.", {"silent": True}))
    dispatch(msgs)
    return None


def confirm_end(expect_id=None):
    msgs = []
    with lock:
        run = state["run"]
        if not run or run["phase"] != "prompt_end":
            return "Nessuna sessione da confermare."
        if expect_id and run.get("id") != expect_id:
            return "Richiesta scaduta."
        until = _confirm_end_locked(now_ms())
        schedule()
        save_state()
        msgs.append(pause_msg(until, morning=bool(state["run"].get("morning"))))
    dispatch(msgs)
    return None


def stop_session():
    """Termina a mano una sessione in corso: la pausa parte subito, senza chiedere conferma."""
    with lock:
        run = state["run"]
        if not run or run["phase"] != "session":
            return
        t = now_ms()
        state["log"].append({"t": run["start"], "d": max(0, round((min(t, run["start"] + run["sessionMs"]) - run["start"]) / 1000)),
                             "k": "stopped"})
        del state["log"][:-MAX_LOG]
        state["run"] = cooldown_run(t + int(cooldown_minutes(t) * 60000))
        save_state()
        schedule()
        log("Sessione terminata a mano")


def handle_action(action):
    """Tocco su un pulsante di notifica, arrivato dall'evento di Home Assistant."""
    if not isinstance(action, str) or not action.startswith("SVAPO_"):
        return  # pulsanti di altre app
    kind, _, rid = action.partition(":")
    if kind == "SVAPO_START":
        err = start_session(expect_id=rid)
    elif kind == "SVAPO_END":
        err = confirm_end(expect_id=rid)
    elif kind == "SVAPO_TEST":
        with lock:
            test_tap["id"], test_tap["at"] = rid, now_ms()
        log("Tocco di prova ricevuto")
        dispatch([("notify", "Tocco ricevuto", "Il pulsante funziona.", {"silent": True})])
        return
    else:
        return
    if err:
        log(f"Tocco ignorato ({kind}): {err}")


def update_settings(patch):
    with lock:
        s = state["settings"]
        for k, (lo, hi) in LIMITS.items():
            if k in patch:
                try:
                    v = int(patch[k])
                except (TypeError, ValueError):
                    continue
                s[k] = min(hi, max(lo, v))
        for k in BOOLS:
            if k in patch and isinstance(patch[k], bool):
                if k == "gradual" and patch[k] != s["gradual"]:
                    s["gradualStart"] = now_ms() if patch[k] else None
                s[k] = patch[k]
        save_state()


def reset_log():
    with lock:
        state["log"] = []
        save_state()


def send_test():
    """Notifica di prova con un pulsante: serve a controllare tutto il giro, Watch compreso."""
    rid = secrets.token_hex(3)
    with lock:
        test_tap["id"], test_tap["at"] = None, None
    sent, reason = send_notification(
        "Prova di Svapo", "Tocca il pulsante per controllare che il giro funzioni.",
        tag="svapo-prova", actions=[{"action": f"SVAPO_TEST:{rid}", "title": "Funziona"}])
    return sent, reason


def state_json():
    with lock:
        t = now_ms()
        return json.dumps({
            "now": t,
            "settings": state["settings"],
            "log": state["log"],
            "run": state["run"],
            "cooldownMin": cooldown_minutes(t),
            "quietNow": is_quiet(t),
            "testTap": test_tap["at"],
            "notify": {
                "services": len(options["notify_services"]),
                "listening": ws_ok,
                "remindMin": options["reminder_minutes"],
                "startReminders": options["start_reminders"],
                "endReminders": options["end_reminders"],
            },
        }).encode("utf-8")


# ---------- ascolto dei tocchi (websocket di Home Assistant) ----------

def ws_loop():
    global ws_ok
    try:
        import websocket
    except ImportError:
        log("Libreria websocket-client mancante: i pulsanti delle notifiche non funzioneranno.")
        return
    backoff = 1.0
    while not stop_event.is_set():
        ws = None
        try:
            ws = websocket.create_connection(HA_WS, timeout=15)
            if json.loads(ws.recv()).get("type") != "auth_required":
                raise RuntimeError("risposta inattesa da Home Assistant")
            ws.send(json.dumps({"type": "auth", "access_token": SUPERVISOR_TOKEN}))
            if json.loads(ws.recv()).get("type") != "auth_ok":
                raise RuntimeError("autenticazione rifiutata")
            ws.send(json.dumps({"id": 1, "type": "subscribe_events", "event_type": "mobile_app_notification_action"}))
            ws.settimeout(30)
            ws_ok = True
            backoff = 1.0
            log("In ascolto dei tocchi sulle notifiche")
            ping_id = 1
            while not stop_event.is_set():
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    ping_id += 1
                    ws.send(json.dumps({"id": ping_id, "type": "ping"}))
                    continue
                if not raw:
                    raise ConnectionError("connessione chiusa")
                msg = json.loads(raw)
                if msg.get("type") == "result" and msg.get("id") == 1 and not msg.get("success"):
                    raise RuntimeError("iscrizione agli eventi rifiutata")
                if msg.get("type") == "event":
                    data = (msg.get("event") or {}).get("data") or {}
                    handle_action(data.get("action"))
        except Exception as e:
            if not stop_event.is_set():
                log(f"Connessione a Home Assistant interrotta: {e}")
        finally:
            ws_ok = False
            try:
                if ws:
                    ws.close()
            except Exception:
                pass
        stop_event.wait(backoff)
        backoff = min(backoff * 2, WS_BACKOFF_MAX)


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    server_version = "Svapo/1.0"

    def log_message(self, fmt, *args):
        pass

    def _allowed(self):
        if not SUPERVISOR_TOKEN:
            return True
        return self.client_address[0] in INGRESS_PEERS

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode("utf-8"))

    def do_GET(self):
        if not self._allowed():
            return self._json(403, {"error": "vietato"})
        path = self.path.split("?", 1)[0]
        if path == "/api/state":
            return self._send(200, state_json())
        if path in ("/", "/index.html"):
            try:
                body = (WEB_DIR / "index.html").read_bytes()
            except OSError:
                return self._json(404, {"error": "pagina non trovata"})
            return self._send(200, body, "text/html; charset=utf-8")
        return self._json(404, {"error": "non trovato"})

    def do_POST(self):
        if not self._allowed():
            return self._json(403, {"error": "vietato"})
        path = self.path.split("?", 1)[0]
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > 10_000:
            return self._json(413, {"error": "richiesta troppo grande"})
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw) if raw else {}
        except ValueError:
            return self._json(400, {"error": "JSON non valido"})
        if not isinstance(body, dict):
            body = {}

        if path == "/api/start":
            err = start_session(bool(body.get("early")))
            if err:
                return self._json(409, {"error": err})
        elif path == "/api/confirm":
            err = confirm_end()
            if err:
                return self._json(409, {"error": err})
        elif path == "/api/stop":
            stop_session()
        elif path == "/api/settings":
            update_settings(body)
        elif path == "/api/reset":
            reset_log()
        elif path == "/api/test-notify":
            sent, reason = send_test()
            return self._json(200, {"sent": sent > 0, "devices": sent, "reason": reason})
        else:
            return self._json(404, {"error": "non trovato"})
        return self._send(200, state_json())


# ---------- avvio ----------

def init():
    global options
    options = load_options()
    ensure_timezone()
    load_state()
    on_timer()  # porta avanti subito ciò che è scaduto mentre l'add-on era spento


def start_background():
    if SUPERVISOR_TOKEN:
        threading.Thread(target=ws_loop, daemon=True).start()


def make_server(port):
    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    httpd.daemon_threads = True
    return httpd


def main():
    init()
    httpd = make_server(PORT)

    def _term(*_):
        stop_event.set()
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _term)
    services = options["notify_services"]
    log(f"Svapo Consapevole 0.4 in ascolto sulla porta {PORT}. "
        f"Notifiche: {', '.join(services) if services else 'nessun dispositivo configurato'}")
    start_background()
    try:
        httpd.serve_forever()
    finally:
        with lock:
            save_state()


if __name__ == "__main__":
    main()
