from flask import Flask, request, redirect, jsonify, render_template_string, url_for, abort
import os
import requests
import sqlite3
from datetime import datetime, timezone

# ---------- Config ----------
TRMNL_TOKEN_URL = "https://usetrmnl.com/oauth/token"
DEFAULT_STOPS = [
    os.getenv("DEFAULT_STOP_A", "01109"),  # Opp National Gallery
    os.getenv("DEFAULT_STOP_B", "01219"),  # Raffles City
    os.getenv("DEFAULT_STOP_C", "02151"),  # YMCA
]
LTA_API_KEY = os.getenv("LTA_API_KEY", "")
DB_PATH = os.getenv("DB_PATH", "data.sqlite3")

# ---------- App ----------
app = Flask(__name__)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            uuid TEXT PRIMARY KEY,
            access_token TEXT,
            stop_a TEXT,
            stop_b TEXT,
            stop_c TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    return conn

# ---------- Helpers ----------
def lta_arrivals(stop_code: str):
    if not stop_code:
        return {"Services": []}
    url = "https://datamall2.mytransport.sg/ltaodataservice/BusArrivalv2"
    try:
        r = requests.get(url, params={"BusStopCode": stop_code},
                         headers={"AccountKey": LTA_API_KEY},
                         timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e), "Services": []}

def fmt_time(iso_str: str):
    if not iso_str:
        return "--"
    try:
        # e.g., "2025-09-16T13:45:00+08:00"
        t = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return t.strftime("%H:%M")
    except Exception:
        # fallback to last 8..3 slice like docs example
        return iso_str[-8:-3] if len(iso_str) >= 8 else "--"

def summarize(payload: dict, limit: int = 6):
    lines = []
    for svc in payload.get("Services", [])[:limit]:
        n = svc.get("ServiceNo", "?")
        nb = svc.get("NextBus", {}) or {}
        nb2 = svc.get("NextBus2", {}) or {}
        t1 = fmt_time(nb.get("EstimatedArrival"))
        t2 = fmt_time(nb2.get("EstimatedArrival"))
        lines.append(f"{n:>3}: {t1} / {t2}")
    return "\n".join(lines) if lines else "No services."

def get_user(uuid: str):
    conn = get_db()
    cur = conn.execute("SELECT * FROM users WHERE uuid = ?", (uuid,))
    row = cur.fetchone()
    if row is None:
        # seed defaults
        conn.execute("""INSERT INTO users (uuid, stop_a, stop_b, stop_c, created_at, updated_at)
                        VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))""",
                     (uuid, DEFAULT_STOPS[0], DEFAULT_STOPS[1], DEFAULT_STOPS[2]))
        conn.commit()
        cur = conn.execute("SELECT * FROM users WHERE uuid = ?", (uuid,))
        row = cur.fetchone()
    return row

def update_user(uuid: str, **fields):
    if not fields:
        return
    keys = ", ".join([f"{k} = ?" for k in fields.keys()])
    values = list(fields.values())
    values.append(uuid)
    conn = get_db()
    conn.execute(f"UPDATE users SET {keys}, updated_at = datetime('now') WHERE uuid = ?", values)
    conn.commit()

# ---------- 1) Installation URL ----------
@app.get("/install")
def install():
    code = request.args.get("token")  # TRMNL calls this 'token' in docs
    callback = request.args.get("installation_callback_url")
    if not code or not callback:
        abort(400, "Missing token or installation_callback_url")
    # Exchange token for access_token
    body = {
        "code": code,
        "client_id": os.getenv("TRMNL_CLIENT_ID", ""),
        "client_secret": os.getenv("TRMNL_CLIENT_SECRET", ""),
        "grant_type": "authorization_code",
    }
    try:
        r = requests.post(TRMNL_TOKEN_URL, data=body, timeout=10)
        r.raise_for_status()
        # We don't yet know the user's UUID; TRMNL will POST success webhook with Authorization Bearer access_token
    except Exception as e:
        # Still redirect back so TRMNL can show an error state
        print("Token exchange failed:", e)
    return redirect(callback, code=302)

# ---------- 1b) Installation Success Webhook URL ----------
@app.post("/installed")
def installed_webhook():
    # TRMNL sends JSON { user: { uuid, plugin_setting_id, ... } } with Authorization: Bearer <access_token>
    auth = request.headers.get("Authorization", "")
    token = auth.split("Bearer")[-1].strip() if "Bearer" in auth else None
    data = request.get_json(silent=True) or {}
    user = (data or {}).get("user", {})
    uuid = user.get("uuid")
    if not uuid:
        return ("Missing uuid", 400)
    conn = get_db()
    # upsert
    conn.execute("""INSERT INTO users (uuid, access_token, stop_a, stop_b, stop_c, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                    ON CONFLICT(uuid) DO UPDATE SET access_token=excluded.access_token, updated_at=datetime('now')""",
                 (uuid, token, DEFAULT_STOPS[0], DEFAULT_STOPS[1], DEFAULT_STOPS[2]))
    conn.commit()
    return ("", 204)

# ---------- 2) Plugin Management URL ----------
@app.route("/manage", methods=["GET", "POST"])
def manage():
    uuid = request.args.get("uuid") or request.form.get("uuid")
    if not uuid:
        return "Missing uuid", 400
    if request.method == "POST":
        stop_a = (request.form.get("stop_a") or "").strip()
        stop_b = (request.form.get("stop_b") or "").strip()
        stop_c = (request.form.get("stop_c") or "").strip()
        update_user(uuid, stop_a=stop_a or None, stop_b=stop_b or None, stop_c=stop_c or None)

        back = request.form.get("back_to_trmnl")
        if back:
            # optional: if you saved plugin_setting_id, you could build a direct link
            return redirect(back, code=302)

    row = get_user(uuid)
    tmpl = """
    <link rel="stylesheet" href="https://unpkg.com/mvp.css@1.12/mvp.css">
    <main>
      <header><h1>Singapore Bus Timings — Settings</h1></header>
      <section>
        <form method="post">
          <input type="hidden" name="uuid" value="{{uuid}}"/>
          <label>Bus Stop A <input name="stop_a" value="{{a}}" placeholder="e.g., 01109" /></label>
          <label>Bus Stop B <input name="stop_b" value="{{b}}" placeholder="e.g., 01219" /></label>
          <label>Bus Stop C <input name="stop_c" value="{{c}}" placeholder="e.g., 02151" /></label>
          <details>
            <summary>Advanced</summary>
            <label>Return to TRMNL URL (optional) <input name="back_to_trmnl" placeholder="https://usetrmnl.com/plugin_settings/1234/edit" /></label>
          </details>
          <button type="submit">Save settings</button>
        </form>
        <p>Tip: Search bus stop codes on <a href="https://www.mytransport.sg/content/mytransport/home/dataMall.html" target="_blank" rel="noreferrer">LTA / MyTransport</a>.</p>
      </section>
    </main>
    """
    return render_template_string(tmpl, uuid=uuid, a=row["stop_a"], b=row["stop_b"], c=row["stop_c"])

# ---------- 3) Plugin Markup URL ----------
@app.post("/markup")
def markup():
    # Validate and load user
    auth = request.headers.get("Authorization", "")
    bearer = auth.split("Bearer")[-1].strip() if "Bearer" in auth else None
    user_uuid = request.form.get("user_uuid") or (request.json or {}).get("user_uuid")
    if not user_uuid:
        return jsonify({"error": "missing user_uuid"}), 400
    row = get_user(user_uuid)

    # (Optional) validate token matches stored one
    if row and row["access_token"] and bearer and row["access_token"] != bearer:
        # soft-warn but continue to avoid user-facing errors
        pass

    stops = [row["stop_a"] or DEFAULT_STOPS[0],
             row["stop_b"] or DEFAULT_STOPS[1],
             row["stop_c"] or DEFAULT_STOPS[2]]

    # Fetch arrivals
    payloads = [lta_arrivals(s) for s in stops]

    # Build simple HTML using TRMNL classes
    blocks = []
    for idx, (stop, data) in enumerate(zip(stops, payloads), start=1):
        blocks.append(f"""
        <div class="content">
          <span class="label label--underline">Stop {stop}</span>
          <pre class="code">{summarize(data)}</pre>
        </div>
        """)
    body_inner = "".join(blocks)

    base = f"""
    <div class="layout">
      <div class="columns">
        <div class="column">
          <div class="markdown gap--large">
            <span class="title">SG Bus Timings</span>
            {body_inner}
            <span class="caption">Updated via LTA DataMall</span>
          </div>
        </div>
      </div>
    </div>
    """
    resp = {
        "markup": f"<div class='view view--full'>{base}</div>",
        "markup_half_horizontal": f"<div class='view view--half_horizontal'>{base}</div>",
        "markup_half_vertical": f"<div class='view view--half_vertical'>{base}</div>",
        "markup_quadrant": f"<div class='view view--quadrant'>{base}</div>",
        "shared": ""
    }
    return jsonify(resp)

# ---------- 4) Uninstallation Webhook URL ----------
@app.post("/uninstalled")
def uninstalled():
    data = request.get_json(silent=True) or {}
    uuid = data.get("user_uuid")
    if uuid:
        conn = get_db()
        conn.execute("DELETE FROM users WHERE uuid = ?", (uuid,))
        conn.commit()
    return ("", 204)

# ---------- 5) Knowledge Base URL ----------
@app.get("/kb")
def kb():
    html = """
    <div class="view view--full">
      <div class="layout"><div class="columns"><div class="column">
      <div class="markdown">
        <h1>TRMNL — Singapore Bus Timings Plugin</h1>
        <p>This plugin shows upcoming arrivals for <strong>three bus stops</strong>. Set your stop codes in the Management UI.</p>
        <h3>Environment Variables</h3>
        <ul>
          <li><code>LTA_API_KEY</code> — required. Get one from LTA DataMall.</li>
          <li><code>TRMNL_CLIENT_ID</code>, <code>TRMNL_CLIENT_SECRET</code> — required for OAuth.</li>
          <li><code>DEFAULT_STOP_A</code>, <code>DEFAULT_STOP_B</code>, <code>DEFAULT_STOP_C</code> — optional defaults.</li>
        </ul>
        <h3>TRMNL URLs</h3>
        <ul>
          <li>Installation URL: <code>/install</code></li>
          <li>Installation Success Webhook URL: <code>/installed</code></li>
          <li>Plugin Management URL: <code>/manage</code></li>
          <li>Plugin Markup URL: <code>/markup</code></li>
          <li>Uninstallation Webhook URL: <code>/uninstalled</code></li>
          <li>Knowledge Base URL: <code>/kb</code></li>
        </ul>
      </div></div></div></div>
    </div>
    """
    return html

@app.get("/healthz")
def healthz():
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
