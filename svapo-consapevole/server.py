#!/usr/bin/env python3
"""Svapo Consapevole: server dell'add-on per Home Assistant.

Tiene lo stato (impostazioni, storico, sessione in corso), fa scorrere i timer
anche a telefono bloccato e manda le notifiche tramite il servizio notify di
Home Assistant. Usa solo la libreria standard.
"""
import json
import os
import signal
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DATA_DIR = Path(os.environ.get("SVAPO_DATA", "/data"))
WEB_DIR = Path(os.environ.get("SVAPO_WEB", Path(__file__).resolve().parent / "web"))
PORT = int(os.environ.get("SVAPO_PORT", "8099"))
HA_API = os.environ.get("SVAPO_HA_API", "http://supervisor/core/api").rstrip("/")
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
# Dentro Home Assistant, solo il gateway ingress del Supervisor può parlare con l'add-on.
INGRESS_PEERS = {"172.30.32.2", "127.0.0.1", "::1"}
MAX_LOG = 400
LATE_MS = 120_000  # oltre questo ritardo non si manda più la notifica
# File statici serviti oltre alla pagina: manifest e icone per la Home dell'iPhone.
STATIC = {
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json; charset=utf-8"),
    "/icon-180.png": ("icon-180.png", "image/png"),
    "/icon-512.png": ("icon-512.png", "image/png"),
}

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
}
LIMITS = {
    "sessionMin": (3, 15),
    "puffSec": (15, 90),
    "cooldownMin": (10, 180),
    "goal": (1, 30),
    "gradualStep": (1, 30),
}
BOOLS = ("gradual", "vibrate", "sound")

lock = threading.RLock()
state = {"settings": dict(DEFAULT_SETTINGS), "log": [], "run": None}
options = {
    "direct_access": False,
    "notify_services": [],
    "notify_start": True,
    "notify_end": True,
    "notify_ready": True,
    "interruption_level": "time-sensitive",
}
timer = None


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
    opts["direct_access"] = bool(opts["direct_access"])
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
    if isinstance(data.get("run"), dict):
        state["run"] = data["run"]


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


def cooldown_minutes(at):
    s = state["settings"]
    m = s["cooldownMin"]
    if s["gradual"] and s.get("gradualStart"):
        weeks = max(0, int((at - s["gradualStart"]) // (7 * 86_400_000)))
        m += weeks * s["gradualStep"]
    return min(m, 600)


# ---------- notifiche ----------

def send_notification(title, message, tag):
    """Manda la notifica a tutti i servizi configurati. Ritorna (inviate, motivo)."""
    services = options["notify_services"]
    if not services:
        return 0, "Nessun dispositivo configurato nelle opzioni dell'add-on."
    if not SUPERVISOR_TOKEN:
        return 0, "Token del Supervisor non disponibile."
    payload = json.dumps({
        "title": title,
        "message": message,
        "data": {
            "tag": tag,
            "ttl": 0,
            "priority": "high",
            "push": {"interruption-level": options["interruption_level"]},
        },
    }).encode("utf-8")
    sent = 0
    reason = ""
    for svc in services:
        req = urllib.request.Request(
            f"{HA_API}/services/notify/{svc}",
            data=payload,
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


def notify_async(title, message, tag):
    threading.Thread(target=send_notification, args=(title, message, tag), daemon=True).start()


# ---------- timer ----------

def schedule():
    """Arma il timer sul prossimo evento. Va chiamata con il lock preso."""
    global timer
    if timer:
        timer.cancel()
        timer = None
    run = state["run"]
    if not run:
        return
    target = run["start"] + run["sessionMs"] if run["phase"] == "session" else run["until"]
    delay = max(0.05, (target - now_ms()) / 1000)
    timer = threading.Timer(delay, on_timer)
    timer.daemon = True
    timer.start()


def _finish_session_locked(stopped, at):
    run = state["run"]
    dur = max(0, min(at - run["start"], run["sessionMs"]))
    kind = "early" if run.get("early") else ("stopped" if stopped else "ok")
    state["log"].append({"t": run["start"], "d": round(dur / 1000), "k": kind})
    del state["log"][:-MAX_LOG]
    cool = cooldown_minutes(at)
    state["run"] = {"phase": "cooldown", "until": at + int(cool * 60000)}
    save_state()
    return cool


def on_timer():
    msgs = []
    with lock:
        t = now_ms()
        run = state["run"]
        if run and run["phase"] == "session":
            end = run["start"] + run["sessionMs"]
            if t >= end:
                cool = _finish_session_locked(False, end)
                log(f"Sessione finita, pausa di {fmt_min(cool)}")
                if options["notify_end"] and t - end < LATE_MS:
                    msgs.append(("Sessione finita", f"Prossima sigaretta tra {fmt_min(cool)}.", "svapo-fine"))
                run = state["run"]
        if run and run["phase"] == "cooldown" and t >= run["until"]:
            until = run["until"]
            state["run"] = None
            save_state()
            log("Pausa finita")
            if options["notify_ready"] and t - until < LATE_MS:
                msgs.append(("Nuova sigaretta", "La pausa è finita. Quando vuoi, inizia una nuova sessione.", "svapo-pronta"))
        schedule()
    for m in msgs:
        notify_async(*m)


# ---------- comandi ----------

def start_session(early=False):
    """Ritorna None se va bene, altrimenti il motivo del rifiuto."""
    msg = None
    with lock:
        run = state["run"]
        if run and run["phase"] == "session":
            return None
        if run and run["phase"] == "cooldown" and not early:
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
        puffs = max(1, session_ms // puff_ms)
        log("Sessione iniziata" + (" (fuori programma)" if early else ""))
        if options["notify_start"]:
            title = "Sessione fuori programma" if early else "Sessione iniziata"
            msg = (title, f"{fmt_min(session_ms / 60000)} e circa {puffs} tiri. Con calma.", "svapo-inizio")
    if msg:
        notify_async(*msg)
    return None


def stop_session():
    with lock:
        run = state["run"]
        if not run or run["phase"] != "session":
            return
        _finish_session_locked(True, now_ms())
        log("Sessione terminata a mano")
        schedule()


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


def state_json():
    with lock:
        t = now_ms()
        return json.dumps({
            "now": t,
            "settings": state["settings"],
            "log": state["log"],
            "run": state["run"],
            "cooldownMin": cooldown_minutes(t),
            "notify": {
                "services": len(options["notify_services"]),
                "start": options["notify_start"],
                "end": options["notify_end"],
                "ready": options["notify_ready"],
            },
        }).encode("utf-8")


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    server_version = "Svapo/1.0"

    def log_message(self, fmt, *args):
        pass

    def _allowed(self):
        if not SUPERVISOR_TOKEN:
            return True
        if self.client_address[0] in INGRESS_PEERS:
            return True
        # Accesso diretto dalla porta di rete: solo se l'hai attivato nelle opzioni.
        return bool(options.get("direct_access"))

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
        asset = STATIC.get(path)
        if asset:
            try:
                body = (WEB_DIR / asset[0]).read_bytes()
            except OSError:
                return self._json(404, {"error": "file non trovato"})
            return self._send(200, body, asset[1])
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
        elif path == "/api/stop":
            stop_session()
        elif path == "/api/settings":
            update_settings(body)
        elif path == "/api/reset":
            reset_log()
        elif path == "/api/test-notify":
            sent, reason = send_notification(
                "Prova di Svapo Consapevole", "Le notifiche funzionano.", "svapo-prova")
            return self._json(200, {"sent": sent > 0, "devices": sent, "reason": reason})
        else:
            return self._json(404, {"error": "non trovato"})
        return self._send(200, state_json())


# ---------- avvio ----------

def init():
    global options
    options = load_options()
    load_state()
    on_timer()  # chiude subito ciò che è scaduto mentre l'add-on era spento


def make_server(port):
    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    httpd.daemon_threads = True
    return httpd


def main():
    init()
    httpd = make_server(PORT)
    signal.signal(
        signal.SIGTERM,
        lambda *_: threading.Thread(target=httpd.shutdown, daemon=True).start(),
    )
    services = options["notify_services"]
    log(f"Svapo Consapevole in ascolto sulla porta {PORT}. "
        f"Notifiche: {', '.join(services) if services else 'nessun dispositivo configurato'}")
    try:
        httpd.serve_forever()
    finally:
        with lock:
            save_state()


if __name__ == "__main__":
    main()
