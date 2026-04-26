import os
import sqlite3
import calendar
from datetime import date, datetime, timedelta

import jpholiday
from flask import Flask, request, redirect, session, render_template, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret")

PASSWORD = os.environ.get("APP_PASSWORD", "0814")
DB = "events.db"

TAGS = ["撮影会", "通院", "生理", "デート", "飲み会", "邂逅", "休日", "その他"]
OWNERS = ["まき", "亮太", "二人"]
MINUTES = ["00", "15", "30", "45"]
HOURS = [f"{i:02d}" for i in range(24)]


def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            end_date TEXT,
            title TEXT NOT NULL,
            tag TEXT,
            location TEXT,
            memo TEXT,
            url TEXT,
            owner TEXT DEFAULT 'まき',
            start_time TEXT,
            end_time TEXT
        )
    """)

    cur.execute("PRAGMA table_info(events)")
    cols = [c[1] for c in cur.fetchall()]

    add_cols = {
        "end_date": "TEXT",
        "tag": "TEXT",
        "location": "TEXT",
        "memo": "TEXT",
        "url": "TEXT",
        "owner": "TEXT DEFAULT 'まき'",
        "start_time": "TEXT",
        "end_time": "TEXT",
    }

    for col, typ in add_cols.items():
        if col not in cols:
            cur.execute(f"ALTER TABLE events ADD COLUMN {col} {typ}")

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
        h, m = value.split(":", 1)
        return h, m
    return "", ""


def date_range(start, end):
    try:
        s = datetime.strptime(start, "%Y-%m-%d").date()
        e = datetime.strptime(end or start, "%Y-%m-%d").date()
    except Exception:
        return []

    if e < s:
        e = s

    days = []
    cur = s
    while cur <= e:
        days.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return days


def get_month_events(year, month):
    month_start = date(year, month, 1)
    month_end = date(year, month, calendar.monthrange(year, month)[1])

    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, date, end_date, title, tag, location, memo, url, owner, start_time, end_time
        FROM events
        WHERE date <= ? AND COALESCE(end_date, date) >= ?
        ORDER BY date ASC, start_time ASC, id ASC
    """, (
        month_end.strftime("%Y-%m-%d"),
        month_start.strftime("%Y-%m-%d")
    ))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_event(event_id):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, date, end_date, title, tag, location, memo, url, owner, start_time, end_time
        FROM events
        WHERE id = ?
    """, (event_id,))
    row = cur.fetchone()
    conn.close()
    return row


def build_events_by_date(rows):
    result = {}
    for e in rows:
        start = e[1]
        end = e[2] or e[1]
        for d in date_range(start, end):
            result.setdefault(d, []).append(e)
    return result


def build_holidays_for_calendar(weeks):
    result = {}
    for week in weeks:
        for d in week:
            name = jpholiday.is_holiday_name(d)
            if name:
                result[d.strftime("%Y-%m-%d")] = name
    return result


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

    rows = get_month_events(year, month)
    events_by_date = build_events_by_date(rows)

    maki_events = [e for e in rows if e[8] == "まき"]
    ryota_events = [e for e in rows if e[8] == "亮太"]
    both_events = [e for e in rows if e[8] == "二人"]

    cal = calendar.Calendar(firstweekday=6)
    weeks = cal.monthdatescalendar(year, month)
    holidays = build_holidays_for_calendar(weeks)

    return render_template(
        "calendar.html",
        year=year,
        month=month,
        today=today,
        weeks=weeks,
        events_by_date=events_by_date,
        holidays=holidays,
        maki_events=maki_events,
        ryota_events=ryota_events,
        both_events=both_events,
        tags=TAGS,
        owners=OWNERS,
        hours=HOURS,
        minutes=MINUTES,
        prev_year=year if month > 1 else year - 1,
        prev_month=month - 1 if month > 1 else 12,
        next_year=year if month < 12 else year + 1,
        next_month=month + 1 if month < 12 else 1,
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
        hours=HOURS,
        minutes=MINUTES
    )


@app.route("/add", methods=["POST"])
def add():
    if not login_required():
        return redirect(url_for("login"))

    event_date = request.form.get("date", "").strip()
    end_date = request.form.get("end_date", "").strip() or event_date
    title = request.form.get("title", "").strip()
    tag = request.form.get("tag", "").strip()
    owner = request.form.get("owner", "まき").strip()
    location = request.form.get("location", "").strip()
    memo = request.form.get("memo", "").strip()
    url = request.form.get("url", "").strip()

    start_time = make_time(
        request.form.get("start_hour", ""),
        request.form.get("start_minute", "")
    )
    end_time = make_time(
        request.form.get("end_hour", ""),
        request.form.get("end_minute", "")
    )

    if owner not in OWNERS:
        owner = "まき"

    if not event_date or not title:
        return redirect(url_for("calendar_view"))

    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO events(date, end_date, title, tag, location, memo, url, owner, start_time, end_time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (event_date, end_date, title, tag, location, memo, url, owner, start_time, end_time))
    conn.commit()
    conn.close()

    y, m, _ = event_date.split("-")
    return redirect(url_for("calendar_view", year=int(y), month=int(m)))


@app.route("/edit/<int:event_id>", methods=["GET", "POST"])
def edit(event_id):
    if not login_required():
        return redirect(url_for("login"))

    if request.method == "POST":
        event_date = request.form.get("date", "").strip()
        end_date = request.form.get("end_date", "").strip() or event_date
        title = request.form.get("title", "").strip()
        tag = request.form.get("tag", "").strip()
        owner = request.form.get("owner", "まき").strip()
        location = request.form.get("location", "").strip()
        memo = request.form.get("memo", "").strip()
        url = request.form.get("url", "").strip()

        start_time = make_time(
            request.form.get("start_hour", ""),
            request.form.get("start_minute", "")
        )
        end_time = make_time(
            request.form.get("end_hour", ""),
            request.form.get("end_minute", "")
        )

        if owner not in OWNERS:
            owner = "まき"

        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        cur.execute("""
            UPDATE events
            SET date=?, end_date=?, title=?, tag=?, location=?, memo=?, url=?, owner=?, start_time=?, end_time=?
            WHERE id=?
        """, (event_date, end_date, title, tag, location, memo, url, owner, start_time, end_time, event_id))
        conn.commit()
        conn.close()

        y, m, _ = event_date.split("-")
        return redirect(url_for("calendar_view", year=int(y), month=int(m)))

    event = get_event(event_id)
    if not event:
        return redirect(url_for("calendar_view"))

    start_hour, start_minute = split_time(event[9])
    end_hour, end_minute = split_time(event[10])

    return render_template(
        "edit.html",
        event=event,
        tags=TAGS,
        hours=HOURS,
        minutes=MINUTES,
        start_hour=start_hour,
        start_minute=start_minute,
        end_hour=end_hour,
        end_minute=end_minute
    )


@app.route("/delete/<int:event_id>", methods=["POST"])
def delete(event_id):
    if not login_required():
        return redirect(url_for("login"))

    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("DELETE FROM events WHERE id=?", (event_id,))
    conn.commit()
    conn.close()

    return redirect(request.referrer or url_for("calendar_view"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)