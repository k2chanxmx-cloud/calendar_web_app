import os
import json
import calendar
from datetime import date, datetime, timedelta

import psycopg2
from psycopg2.extras import RealDictCursor, Json
from pywebpush import webpush, WebPushException

from flask import (
    Flask,
    request,
    redirect,
    session,
    render_template,
    url_for,
    jsonify,
    send_from_directory,
    make_response,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "secret")

DATABASE_URL = os.environ.get("DATABASE_URL")
PASSWORD = os.environ.get("APP_PASSWORD", "1234")

VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:test@example.com")

TAGS = ["撮影会", "通院", "生理", "デート", "飲み会", "邂逅", "休日", "その他"]
OWNERS = ["まき", "亮太", "二人"]

HOURS = [f"{h:02d}" for h in range(24)]
MINUTES = ["00", "15", "30", "45"]


# ---------------- DB ----------------
def get_conn():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS events (
        id BIGSERIAL PRIMARY KEY,
        start_date DATE,
        end_date DATE,
        title TEXT,
        tag TEXT,
        owner TEXT,
        location TEXT,
        memo TEXT,
        url TEXT,
        start_time TEXT,
        end_time TEXT
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS push_subscriptions (
        id BIGSERIAL PRIMARY KEY,
        endpoint TEXT UNIQUE,
        subscription JSONB
    );
    """)

    conn.commit()
    conn.close()


init_db()


# ---------------- 共通 ----------------
def login_required():
    return session.get("login")


def parse_date(v):
    if isinstance(v, date):
        return v
    return datetime.strptime(str(v), "%Y-%m-%d").date()


def date_range(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def build_events_by_date(events):
    result = {}
    for ev in events:
        try:
            s = parse_date(ev["start_date"])
            e = parse_date(ev["end_date"])
        except:
            continue

        for d in date_range(s, e):
            key = d.strftime("%Y-%m-%d")
            result.setdefault(key, []).append(ev)

    return result


# ---------------- 通知 ----------------
def notify_all(event):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("SELECT id, subscription FROM push_subscriptions")
    subs = cur.fetchall()

    # 👇 リッチ通知
    body = f"📅 {event['start_date']}\n📝 {event['title']}"
    if event.get("location"):
        body += f"\n📍 {event['location']}"
    if event.get("owner"):
        body += f"\n👤 {event['owner']}"

    payload = json.dumps({
        "title": "予定追加",
        "body": body,
        "url": "/calendar"
    }, ensure_ascii=False)

    for s in subs:
        try:
            webpush(
                subscription_info=s["subscription"],
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_SUBJECT},
            )
        except WebPushException:
            cur.execute("DELETE FROM push_subscriptions WHERE id=%s", (s["id"],))

    conn.commit()
    conn.close()


# ---------------- ルーティング ----------------
@app.route("/")
def root():
    return redirect("/calendar")


@app.route("/calendar")
def calendar_view():
    if not login_required():
        return redirect("/login")

    today = date.today()
    year = int(request.args.get("year", today.year))
    month = int(request.args.get("month", today.month))

    cal = calendar.Calendar(firstweekday=6)
    weeks = cal.monthdatescalendar(year, month)

    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("SELECT * FROM events")
    events = cur.fetchall()
    conn.close()

    events_by_date = build_events_by_date(events)

    return render_template(
        "calendar.html",
        year=year,
        month=month,
        today=today,
        weeks=weeks,
        events_by_date=events_by_date,
        tags=TAGS,
        vapid_public_key=VAPID_PUBLIC_KEY,
    )


@app.route("/add", methods=["POST"])
def add():
    conn = get_conn()
    cur = conn.cursor()

    data = dict(request.form)

    cur.execute("""
    INSERT INTO events (start_date,end_date,title,tag,owner,location,memo,url)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        data.get("start_date"),
        data.get("end_date"),
        data.get("title"),
        data.get("tag"),
        data.get("owner"),
        data.get("location"),
        data.get("memo"),
        data.get("url"),
    ))

    conn.commit()
    conn.close()

    notify_all(data)

    return redirect("/calendar")


@app.route("/subscribe", methods=["POST"])
def subscribe():
    sub = request.get_json()

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO push_subscriptions (endpoint, subscription)
    VALUES (%s,%s)
    ON CONFLICT (endpoint)
    DO UPDATE SET subscription=EXCLUDED.subscription
    """, (sub["endpoint"], Json(sub)))

    conn.commit()
    conn.close()

    return jsonify({"ok": True})


@app.route("/test-notification", methods=["POST"])
def test():
    notify_all({
        "start_date": str(date.today()),
        "title": "テスト通知",
        "owner": "",
        "location": ""
    })
    return jsonify({"ok": True})


@app.route("/sw.js")
def sw():
    return send_from_directory("static", "sw.js")


# ---------------- ログイン ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("pw") == PASSWORD:
            session["login"] = True
            return redirect("/calendar")
    return """
    <form method="post">
      <input name="pw">
      <button>ログイン</button>
    </form>
    """


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ---------------- 起動 ----------------
if __name__ == "__main__":
    app.run()