import os
import sqlite3
import calendar
from datetime import date, datetime, timedelta
from flask import Flask, request, redirect, session, render_template, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret")

PASSWORD = os.environ.get("APP_PASSWORD", "1234")
DB = "events.db"

TAGS = ["撮影会", "通院", "生理", "デート", "飲み会", "邂逅", "休日", "その他"]
OWNERS = ["まき", "亮太", "二人"]

HOURS = [f"{h:02d}" for h in range(24)]
MINUTES = ["00", "15", "30", "45"]


def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            title TEXT NOT NULL,
            tag TEXT,
            owner TEXT,
            location TEXT,
            memo TEXT,
            url TEXT,
            start_time TEXT,
            end_time TEXT
        )
    """)

    cur.execute("PRAGMA table_info(events)")
    cols = [c[1] for c in cur.fetchall()]

    required_cols = {
        "start_date": "TEXT",
        "end_date": "TEXT",
        "title": "TEXT",
        "tag": "TEXT",
        "owner": "TEXT",
        "location": "TEXT",
        "memo": "TEXT",
        "url": "TEXT",
        "start_time": "TEXT",
        "end_time": "TEXT",
    }

    for col, col_type in required_cols.items():
        if col not in cols:
            cur.execute(f"ALTER TABLE events ADD COLUMN {col} {col_type}")

    # 旧DB対策：date列がある場合はstart_date/end_dateへ移す
    cur.execute("PRAGMA table_info(events)")
    cols = [c[1] for c in cur.fetchall()]

    if "date" in cols:
        cur.execute("""
            UPDATE events
            SET start_date = COALESCE(NULLIF(start_date, ''), date),
                end_date = COALESCE(NULLIF(end_date, ''), date)
            WHERE date IS NOT NULL
        """)

    cur.execute("""
        UPDATE events
        SET end_date = start_date
        WHERE end_date IS NULL OR end_date = ''
    """)

    cur.execute("""
        UPDATE events
        SET owner = 'まき'
        WHERE owner IS NULL OR owner = ''
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
    return datetime.strptime(value, "%Y-%m-%d").date()


def date_range(start, end):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def get_japanese_holidays(year):
    # ひとまず固定祝日＋代表的な祝日だけ
    # 完全な祝日計算は後で強化可能
    holidays = set()

    fixed = [
        (1, 1),    # 元日
        (2, 11),   # 建国記念の日
        (2, 23),   # 天皇誕生日
        (4, 29),   # 昭和の日
        (5, 3),    # 憲法記念日
        (5, 4),    # みどりの日
        (5, 5),    # こどもの日
        (8, 11),   # 山の日
        (11, 3),   # 文化の日
        (11, 23),  # 勤労感謝の日
    ]

    for m, d in fixed:
        holidays.add(f"{year}-{m:02d}-{d:02d}")

    return holidays


def row_to_event(row):
    start_hour, start_minute = split_time(row["start_time"])
    end_hour, end_minute = split_time(row["end_time"])

    return {
        "id": row["id"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "title": row["title"],
        "tag": row["tag"],
        "owner": row["owner"] or "まき",
        "location": row["location"],
        "memo": row["memo"],
        "url": row["url"],
        "start_time": row["start_time"],
        "end_time": row["end_time"],
        "start_hour": start_hour,
        "start_minute": start_minute,
        "end_hour": end_hour,
        "end_minute": end_minute,
    }


def get_month_events(year, month):
    month_start = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    month_end = date(year, month, last_day)

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT id, start_date, end_date, title, tag, owner, location, memo, url, start_time, end_time
        FROM events
        WHERE start_date <= ?
          AND end_date >= ?
        ORDER BY start_date ASC, start_time ASC, id ASC
    """, (
        month_end.strftime("%Y-%m-%d"),
        month_start.strftime("%Y-%m-%d")
    ))

    rows = cur.fetchall()
    conn.close()

    return [row_to_event(row) for row in rows]


def get_event(event_id):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT id, start_date, end_date, title, tag, owner, location, memo, url, start_time, end_time
        FROM events
        WHERE id = ?
    """, (event_id,))

    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    return row_to_event(row)


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

    # 終了日が開始日より前なら開始日に戻す
    try:
        if parse_date(end_date) < parse_date(start_date):
            end_date = start_date
    except Exception:
        end_date = start_date

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO events (
            start_date, end_date, title, tag, owner,
            location, memo, url, start_time, end_time
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        start_date, end_date, title, tag, owner,
        location, memo, url, start_time, end_time
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

        conn = sqlite3.connect(DB)
        cur = conn.cursor()

        cur.execute("""
            UPDATE events
            SET start_date = ?,
                end_date = ?,
                title = ?,
                tag = ?,
                owner = ?,
                location = ?,
                memo = ?,
                url = ?,
                start_time = ?,
                end_time = ?
            WHERE id = ?
        """, (
            start_date, end_date, title, tag, owner,
            location, memo, url, start_time, end_time,
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

    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("DELETE FROM events WHERE id = ?", (event_id,))
    conn.commit()
    conn.close()

    return redirect(request.referrer or url_for("calendar_view"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)