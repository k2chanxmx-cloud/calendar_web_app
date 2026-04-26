import os
import calendar
from datetime import date, datetime, timedelta

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request, redirect, session, render_template, url_for


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret")

DATABASE_URL = os.environ.get("DATABASE_URL")
PASSWORD = os.environ.get("APP_PASSWORD", "1234")

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

    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS start_date DATE;")
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS end_date DATE;")
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS title TEXT;")
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS tag TEXT;")
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS owner TEXT;")
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS location TEXT;")
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS memo TEXT;")
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS url TEXT;")
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS start_time TEXT;")
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS end_time TEXT;")
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();")

    cur.execute("""
        UPDATE events
        SET owner = 'まき'
        WHERE owner IS NULL OR owner = '';
    """)

    cur.execute("""
        UPDATE events
        SET end_date = start_date
        WHERE end_date IS NULL;
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
        h, m = value.split(":", 1)
        return h, m
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
        (1, 1),
        (2, 11),
        (2, 23),
        (4, 29),
        (5, 3),
        (5, 4),
        (5, 5),
        (8, 11),
        (11, 3),
        (11, 23),
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
    last_day = calendar.monthrange(year, month)[1]
    month_end = date(year, month, last_day)

    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT
            id,
            start_date,
            end_date,
            title,
            tag,
            owner,
            location,
            memo,
            url,
            start_time,
            end_time
        FROM events
        WHERE start_date <= %s
          AND end_date >= %s
        ORDER BY start_date ASC, start_time ASC NULLS LAST, id ASC;
    """, (month_end, month_start))

    rows = cur.fetchall()
    conn.close()

    return [normalize_event(row) for row in rows]


def get_event(event_id):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT
            id,
            start_date,
            end_date,
            title,
            tag,
            owner,
            location,
            memo,
            url,
            start_time,
            end_time
        FROM events
        WHERE id = %s;
    """, (event_id,))

    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    return normalize_event(row)


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

    cal = calendar.Calendar(firstweekday=6)
    weeks = cal.monthdatescalendar(year, month)

    holidays = get_japanese_holidays(year)

    return render_template(
        "calendar.html",
        year=year,
        month=month,
        today=today,
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
        holidays=holidays
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
            start_date,
            end_date,
            title,
            tag,
            owner,
            location,
            memo,
            url,
            start_time,
            end_time
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
    """, (
        start_date,
        end_date,
        title,
        tag,
        owner,
        location,
        memo,
        url,
        start_time,
        end_time
    ))

    conn.commit()
    conn.close()

    try:
        y, m, _ = start_date.split("-")
        return redirect(url_for("calendar_view", year=int(y), month=int(m)))
    except Exception:
        return redirect(url_for("calendar_view"))


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
            SET
                start_date = %s,
                end_date = %s,
                title = %s,
                tag = %s,
                owner = %s,
                location = %s,
                memo = %s,
                url = %s,
                start_time = %s,
                end_time = %s
            WHERE id = %s;
        """, (
            start_date,
            end_date,
            title,
            tag,
            owner,
            location,
            memo,
            url,
            start_time,
            end_time,
            event_id
        ))

        conn.commit()
        conn.close()

        try:
            y, m, _ = start_date.split("-")
            return redirect(url_for("calendar_view", year=int(y), month=int(m)))
        except Exception:
            return redirect(url_for("calendar_view"))

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

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("DELETE FROM events WHERE id = %s;", (event_id,))

    conn.commit()
    conn.close()

    return redirect(request.referrer or url_for("calendar_view"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)