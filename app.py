import os
import json
import calendar
from datetime import date, datetime, timedelta

import psycopg2
from psycopg2.extras import RealDictCursor, Json
from pywebpush import webpush, WebPushException

from flask import (
    Flask, request, redirect, session, render_template, url_for,
    jsonify, send_from_directory, make_response
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret")

DATABASE_URL = os.environ.get("DATABASE_URL")
PASSWORD = os.environ.get("APP_PASSWORD", "1234")

VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:test@example.com")

TAGS = ["撮影会", "通院", "生理", "デート", "飲み会", "邂逅", "休日", "その他"]
OWNERS = ["まき", "亮太", "二人"]
HOURS = [f"{h:02d}" for h in range(24)]
MINUTES = ["00", "15", "30", "45"]


def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL が設定されていません")
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id BIGSERIAL PRIMARY KEY,
            start_date DATE NOT NULL,
            end_date DATE NOT NULL,
            title TEXT NOT NULL,
            tag TEXT,
            owner TEXT,
            location TEXT,
            memo TEXT,
            url TEXT,
            start_time TEXT,
            end_time TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id BIGSERIAL PRIMARY KEY,
            endpoint TEXT UNIQUE NOT NULL,
            subscription JSONB NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    conn.commit()
    conn.close()


init_db()


def login_required():
    return session.get("login") is True


def make_time(hour, minute):
    if hour and minute:
        return f"{hour}:{minute}"
    return ""


def split_time(value):
    if value and ":" in value:
        return value.split(":", 1)
    return "", ""


def parse_date(value):
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def date_range(start, end):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def get_japanese_holidays(year):
    fixed = [
        (1, 1), (2, 11), (2, 23), (4, 29),
        (5, 3), (5, 4), (5, 5), (8, 11),
        (11, 3), (11, 23)
    ]
    return {f"{year}-{m:02d}-{d:02d}" for m, d in fixed}


def normalize_event(row):
    start_date = row.get("start_date")
    end_date = row.get("end_date") or start_date

    if isinstance(start_date, date):
        start_date = start_date.strftime("%Y-%m-%d")
    if isinstance(end_date, date):
        end_date = end_date.strftime("%Y-%m-%d")

    start_time = row.get("start_time") or ""
    end_time = row.get("end_time") or ""

    start_hour, start_minute = split_time(start_time)
    end_hour, end_minute = split_time(end_time)

    return {
        "id": row.get("id"),
        "start_date": start_date,
        "end_date": end_date,
        "title": row.get("title") or "",
        "tag": row.get("tag") or "",
        "owner": row.get("owner") or "まき",
        "location": row.get("location") or "",
        "memo": row.get("memo") or "",
        "url": row.get("url") or "",
        "start_time": start_time,
        "end_time": end_time,
        "start_hour": start_hour,
        "start_minute": start_minute,
        "end_hour": end_hour,
        "end_minute": end_minute,
    }


def get_month_events(year, month):
    month_start = date(year, month, 1)
    month_end = date(year, month, calendar.monthrange(year, month)[1])

    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT id, start_date, end_date, title, tag, owner,
               location, memo, url, start_time, end_time
        FROM events
        WHERE start_date <= %s
          AND end_date >= %s
        ORDER BY start_date ASC, start_time ASC NULLS LAST, id ASC;
    """, (month_end, month_start))

    rows = cur.fetchall()
    conn.close()
    return [normalize_event(row) for row in rows]


def get_day_events(target_date):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT id, start_date, end_date, title, tag, owner,
               location, memo, url, start_time, end_time
        FROM events
        WHERE start_date <= %s
          AND end_date >= %s
        ORDER BY start_time ASC NULLS LAST, id ASC;
    """, (target_date, target_date))

    rows = cur.fetchall()
    conn.close()
    return [normalize_event(row) for row in rows]


def get_event(event_id):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT id, start_date, end_date, title, tag, owner,
               location, memo, url, start_time, end_time
        FROM events
        WHERE id = %s;
    """, (event_id,))

    row = cur.fetchone()
    conn.close()
    return normalize_event(row) if row else None


def build_events_by_date(events):
    result = {}

    for event in events:
        try:
            start = parse_date(event["start_date"])
            end = parse_date(event["end_date"])
        except Exception:
            continue

        for d in date_range(start, end):
            key = d.strftime("%Y-%m-%d")
            result.setdefault(key, []).append(event)

    return result


def notify_all_devices(event):
    if not VAPID_PUBLIC_KEY or not VAPID_PRIVATE_KEY:
        return

    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT id, subscription FROM push_subscriptions;")
    subs = cur.fetchall()

    date_text = event.get("start_date", "")
    if event.get("end_date") and event.get("end_date") != event.get("start_date"):
        date_text = f"{event.get('start_date')}〜{event.get('end_date')}"

    time_text = ""
    if event.get("start_time"):
        time_text = event.get("start_time")
        if event.get("end_time"):
            time_text += f"〜{event.get('end_time')}"

    body_lines = [
        f"📅 {date_text}",
        f"📝 {event.get('title', '')}",
    ]

    if time_text:
        body_lines.append(f"🕒 {time_text}")
    if event.get("owner"):
        body_lines.append(f"👤 {event.get('owner')}")
    if event.get("location"):
        body_lines.append(f"📍 {event.get('location')}")

    payload = {
        "title": "予定が追加されました",
        "body": "\n".join(body_lines),
        "url": f"/day/{event.get('start_date')}"
    }

    expired_ids = []

    for sub in subs:
        try:
            webpush(
                subscription_info=sub["subscription"],
                data=json.dumps(payload, ensure_ascii=False),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_SUBJECT},
            )
        except WebPushException as e:
            if getattr(e.response, "status_code", None) in [404, 410]:
                expired_ids.append(sub["id"])
        except Exception:
            pass

    for sid in expired_ids:
        cur.execute("DELETE FROM push_subscriptions WHERE id = %s;", (sid,))

    conn.commit()
    conn.close()

def notify_all_devices_custom(title, body, url="/calendar"):
    if not VAPID_PUBLIC_KEY or not VAPID_PRIVATE_KEY:
        return

    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT id, subscription FROM push_subscriptions;")
    subs = cur.fetchall()

    payload = {
        "title": title,
        "body": body,
        "url": url
    }

    expired_ids = []

    for sub in subs:
        try:
            webpush(
                subscription_info=sub["subscription"],
                data=json.dumps(payload, ensure_ascii=False),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_SUBJECT},
            )
        except WebPushException as e:
            if getattr(e.response, "status_code", None) in [404, 410]:
                expired_ids.append(sub["id"])
        except Exception:
            pass

    for sid in expired_ids:
        cur.execute("DELETE FROM push_subscriptions WHERE id = %s;", (sid,))

    conn.commit()
    conn.close()

@app.route("/sw.js")
def service_worker():
    response = make_response(send_from_directory("static", "sw.js"))
    response.headers["Content-Type"] = "application/javascript"
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.route("/", methods=["GET", "POST"])
def login():
    if login_required():
        return redirect(url_for("calendar_view"))

    error = ""

    if request.method == "POST":
        if request.form.get("pw") == PASSWORD:
            session["login"] = True
            return redirect(url_for("calendar_view"))
        error = "パスワードが違います"

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/calendar")
def calendar_view():
    if not login_required():
        return redirect(url_for("login"))

    today = date.today()
    year = int(request.args.get("year", today.year))
    month = int(request.args.get("month", today.month))

    if month < 1:
        year -= 1
        month = 12
    elif month > 12:
        year += 1
        month = 1

    prev_year = year if month > 1 else year - 1
    prev_month = month - 1 if month > 1 else 12
    next_year = year if month < 12 else year + 1
    next_month = month + 1 if month < 12 else 1

    events = get_month_events(year, month)
    events_by_date = build_events_by_date(events)

    maki_events = [e for e in events if e["owner"] == "まき"]
    ryota_events = [e for e in events if e["owner"] == "亮太"]
    both_events = [e for e in events if e["owner"] == "二人"]

    today_key = today.strftime("%Y-%m-%d")
    today_events = get_day_events(today_key)

    weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(year, month)

    return render_template(
        "calendar.html",
        year=year,
        month=month,
        today=today,
        today_key=today_key,
        today_events=today_events,
        weeks=weeks,
        events_by_date=events_by_date,
        maki_events=maki_events,
        ryota_events=ryota_events,
        both_events=both_events,
        prev_year=prev_year,
        prev_month=prev_month,
        next_year=next_year,
        next_month=next_month,
        tags=TAGS,
        owners=OWNERS,
        hours=HOURS,
        minutes=MINUTES,
        holidays=get_japanese_holidays(year),
        vapid_public_key=VAPID_PUBLIC_KEY,
    )


@app.route("/day/<target_date>")
def day_view(target_date):
    if not login_required():
        return redirect(url_for("login"))

    try:
        parsed = parse_date(target_date)
    except Exception:
        return redirect(url_for("calendar_view"))

    events = get_day_events(target_date)

    return render_template(
        "day.html",
        target_date=target_date,
        parsed_date=parsed,
        events=events
    )


@app.route("/new")
def new_event():
    if not login_required():
        return redirect(url_for("login"))

    selected_date = request.args.get("date", date.today().strftime("%Y-%m-%d"))

    return render_template(
        "new.html",
        selected_date=selected_date,
        tags=TAGS,
        owners=OWNERS,
        hours=HOURS,
        minutes=MINUTES
    )


@app.route("/add", methods=["POST"])
def add():
    if not login_required():
        return redirect(url_for("login"))

    start_date = request.form.get("start_date", "").strip()
    end_date = request.form.get("end_date", "").strip() or start_date
    title = request.form.get("title", "").strip()
    tag = request.form.get("tag", "").strip()
    owner = request.form.get("owner", "まき").strip()
    location = request.form.get("location", "").strip()
    memo = request.form.get("memo", "").strip()
    url = request.form.get("url", "").strip()

    start_time = make_time(
        request.form.get("start_hour", "").strip(),
        request.form.get("start_minute", "").strip()
    )

    end_time = make_time(
        request.form.get("end_hour", "").strip(),
        request.form.get("end_minute", "").strip()
    )

    if owner not in OWNERS:
        owner = "まき"

    if not start_date or not title:
        return redirect(url_for("calendar_view"))

    try:
        if parse_date(end_date) < parse_date(start_date):
            end_date = start_date
    except Exception:
        end_date = start_date

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO events (
            start_date, end_date, title, tag, owner,
            location, memo, url, start_time, end_time
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id;
    """, (
        start_date, end_date, title, tag, owner,
        location, memo, url, start_time, end_time
    ))

    event_id = cur.fetchone()[0]
    conn.commit()
    conn.close()

    event = {
        "id": event_id,
        "start_date": start_date,
        "end_date": end_date,
        "title": title,
        "tag": tag,
        "owner": owner,
        "location": location,
        "memo": memo,
        "url": url,
        "start_time": start_time,
        "end_time": end_time,
    }

    notify_all_devices(event)

    return redirect(url_for("day_view", target_date=start_date))


@app.route("/edit/<int:event_id>", methods=["GET", "POST"])
def edit(event_id):
    if not login_required():
        return redirect(url_for("login"))

    event = get_event(event_id)
    if not event:
        return redirect(url_for("calendar_view"))

    if request.method == "POST":
        start_date = request.form.get("start_date", "").strip()
        end_date = request.form.get("end_date", "").strip() or start_date
        title = request.form.get("title", "").strip()
        tag = request.form.get("tag", "").strip()
        owner = request.form.get("owner", "まき").strip()
        location = request.form.get("location", "").strip()
        memo = request.form.get("memo", "").strip()
        url = request.form.get("url", "").strip()

        start_time = make_time(
            request.form.get("start_hour", "").strip(),
            request.form.get("start_minute", "").strip()
        )

        end_time = make_time(
            request.form.get("end_hour", "").strip(),
            request.form.get("end_minute", "").strip()
        )

        if owner not in OWNERS:
            owner = "まき"

        if not start_date or not title:
            return redirect(url_for("edit", event_id=event_id))

        try:
            if parse_date(end_date) < parse_date(start_date):
                end_date = start_date
        except Exception:
            end_date = start_date

        conn = get_conn()
        cur = conn.cursor()

        cur.execute("""
            UPDATE events
            SET start_date=%s,
                end_date=%s,
                title=%s,
                tag=%s,
                owner=%s,
                location=%s,
                memo=%s,
                url=%s,
                start_time=%s,
                end_time=%s
            WHERE id=%s;
        """, (
            start_date, end_date, title, tag, owner,
            location, memo, url, start_time, end_time,
            event_id
        ))

        conn.commit()
        conn.close()

        return redirect(url_for("day_view", target_date=start_date))

    return render_template(
        "edit.html",
        event=event,
        tags=TAGS,
        owners=OWNERS,
        hours=HOURS,
        minutes=MINUTES
    )


@app.route("/delete/<int:event_id>", methods=["POST"])
def delete(event_id):
    if not login_required():
        return redirect(url_for("login"))

    event = get_event(event_id)
    redirect_date = event["start_date"] if event else None

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM events WHERE id=%s;", (event_id,))
    conn.commit()
    conn.close()

    if redirect_date:
        return redirect(url_for("day_view", target_date=redirect_date))

    return redirect(url_for("calendar_view"))


@app.route("/subscribe", methods=["POST"])
def subscribe():
    if not login_required():
        return jsonify({"ok": False, "error": "not logged in"}), 401

    subscription = request.get_json()

    if not subscription or "endpoint" not in subscription:
        return jsonify({"ok": False, "error": "invalid subscription"}), 400

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO push_subscriptions (endpoint, subscription)
        VALUES (%s, %s)
        ON CONFLICT (endpoint)
        DO UPDATE SET subscription = EXCLUDED.subscription;
    """, (subscription["endpoint"], Json(subscription)))

    conn.commit()
    conn.close()

    return jsonify({"ok": True})


@app.route("/test-notification", methods=["POST"])
def test_notification():
    if not login_required():
        return jsonify({"ok": False}), 401

    today = date.today().strftime("%Y-%m-%d")

    notify_all_devices({
        "start_date": today,
        "end_date": today,
        "title": "テスト通知",
        "owner": "",
        "location": "",
        "start_time": "",
        "end_time": "",
    })

    return jsonify({"ok": True})


@app.route("/notify-tomorrow")
def notify_tomorrow():
    key = request.args.get("key", "")
    expected_key = os.environ.get("CRON_SECRET_KEY", "")

    if not expected_key or key != expected_key:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    tomorrow = date.today() + timedelta(days=1)
    tomorrow_key = tomorrow.strftime("%Y-%m-%d")

    events = get_day_events(tomorrow_key)

    if not events:
        return jsonify({
            "ok": True,
            "message": "no events tomorrow",
            "date": tomorrow_key
        })

    body_lines = [f"📅 明日の予定：{tomorrow_key}"]

    for event in events:
        line = f"・{event.get('title', '')}"

        if event.get("start_time"):
            line += f"（{event.get('start_time')}"
            if event.get("end_time"):
                line += f"〜{event.get('end_time')}"
            line += "）"

        if event.get("owner"):
            line += f" / {event.get('owner')}"

        if event.get("location"):
            line += f" / {event.get('location')}"

        body_lines.append(line)

    payload_event = {
        "start_date": tomorrow_key,
        "end_date": tomorrow_key,
        "title": "明日の予定があります",
        "owner": "",
        "location": "",
        "start_time": "",
        "end_time": "",
    }

    notify_all_devices_custom(
        title="明日の予定",
        body="\n".join(body_lines),
        url=f"/day/{tomorrow_key}"
    )

    return jsonify({
        "ok": True,
        "notified": True,
        "date": tomorrow_key,
        "count": len(events)
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)