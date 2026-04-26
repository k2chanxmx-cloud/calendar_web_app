import os
import sqlite3
import calendar
from datetime import date
from flask import Flask, request, redirect, session, render_template_string, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret")

PASSWORD = os.environ.get("APP_PASSWORD", "0814")
DB = "events.db"

TAGS = ["撮影会", "通院", "生理", "デート", "飲み会", "邂逅"]
OWNERS = ["まき", "亮太", "二人"]


def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            title TEXT NOT NULL,
            tag TEXT,
            location TEXT,
            memo TEXT,
            url TEXT,
            owner TEXT DEFAULT 'まき'
        )
    """)

    cur.execute("PRAGMA table_info(events)")
    cols = [c[1] for c in cur.fetchall()]

    if "location" not in cols:
        cur.execute("ALTER TABLE events ADD COLUMN location TEXT")

    if "owner" not in cols:
        cur.execute("ALTER TABLE events ADD COLUMN owner TEXT DEFAULT 'まき'")

    conn.commit()
    conn.close()


init_db()


def login_required():
    return session.get("login") is True


def get_month_events(year, month):
    start = f"{year}-{month:02d}-01"
    last = calendar.monthrange(year, month)[1]
    end = f"{year}-{month:02d}-{last:02d}"

    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, date, title, tag, location, memo, url, owner
        FROM events
        WHERE date BETWEEN ? AND ?
        ORDER BY date ASC, id ASC
    """, (start, end))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_event(event_id):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, date, title, tag, location, memo, url, owner
        FROM events
        WHERE id = ?
    """, (event_id,))
    row = cur.fetchone()
    conn.close()
    return row


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

    return render_template_string(LOGIN_TEMPLATE, error=error)


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

    rows = get_month_events(year, month)

    events_by_date = {}
    maki_events = []
    ryota_events = []
    both_events = []

    for e in rows:
        events_by_date.setdefault(e[1], []).append(e)

        if e[7] == "亮太":
            ryota_events.append(e)
        elif e[7] == "二人":
            both_events.append(e)
        else:
            maki_events.append(e)

    cal = calendar.Calendar(firstweekday=6)
    weeks = cal.monthdatescalendar(year, month)

    return render_template_string(
        CALENDAR_TEMPLATE,
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
        tags=TAGS
    )


@app.route("/new")
def new_event():
    if not login_required():
        return redirect(url_for("login"))

    selected_date = request.args.get("date", date.today().strftime("%Y-%m-%d"))

    return render_template_string(
        NEW_TEMPLATE,
        selected_date=selected_date,
        tags=TAGS
    )


@app.route("/add", methods=["POST"])
def add():
    if not login_required():
        return redirect(url_for("login"))

    event_date = request.form.get("date", "").strip()
    title = request.form.get("title", "").strip()
    tag = request.form.get("tag", "").strip()
    owner = request.form.get("owner", "まき").strip()
    location = request.form.get("location", "").strip()
    memo = request.form.get("memo", "").strip()
    url = request.form.get("url", "").strip()

    if owner not in OWNERS:
        owner = "まき"

    if not event_date or not title:
        return redirect(url_for("calendar_view"))

    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO events(date, title, tag, location, memo, url, owner)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (event_date, title, tag, location, memo, url, owner))
    conn.commit()
    conn.close()

    try:
        y, m, _ = event_date.split("-")
        return redirect(url_for("calendar_view", year=int(y), month=int(m)))
    except Exception:
        return redirect(url_for("calendar_view"))


@app.route("/edit/<int:event_id>", methods=["GET", "POST"])
def edit(event_id):
    if not login_required():
        return redirect(url_for("login"))

    if request.method == "POST":
        event_date = request.form.get("date", "").strip()
        title = request.form.get("title", "").strip()
        tag = request.form.get("tag", "").strip()
        owner = request.form.get("owner", "まき").strip()
        location = request.form.get("location", "").strip()
        memo = request.form.get("memo", "").strip()
        url = request.form.get("url", "").strip()

        if owner not in OWNERS:
            owner = "まき"

        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        cur.execute("""
            UPDATE events
            SET date=?, title=?, tag=?, location=?, memo=?, url=?, owner=?
            WHERE id=?
        """, (event_date, title, tag, location, memo, url, owner, event_id))
        conn.commit()
        conn.close()

        try:
            y, m, _ = event_date.split("-")
            return redirect(url_for("calendar_view", year=int(y), month=int(m)))
        except Exception:
            return redirect(url_for("calendar_view"))

    event = get_event(event_id)
    if not event:
        return redirect(url_for("calendar_view"))

    return render_template_string(EDIT_TEMPLATE, event=event, tags=TAGS)


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


BASE_CSS = """
<style>
:root {
  --bg:#f4f7fb;
  --card:#ffffff;
  --text:#111827;
  --muted:#6b7280;
  --blue:#3b82f6;
  --blue2:#2563eb;
  --soft-blue:#dbeafe;
  --green:#22c55e;
  --red-soft:#fee2e2;
  --pink:#ec4899;
  --pink-soft:#fce7f3;
  --orange:#f97316;
  --orange-soft:#ffedd5;
  --purple:#8b5cf6;
  --purple-soft:#ede9fe;
  --shadow:0 10px 28px rgba(15,23,42,.08);
}
* { box-sizing:border-box; }
body {
  margin:0;
  background:linear-gradient(180deg,#eef5ff 0%,#f8fafc 45%,#f4f7fb 100%);
  color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Hiragino Sans","Yu Gothic UI",sans-serif;
}
.app {
  max-width:520px;
  margin:0 auto;
  padding:14px;
  padding-bottom:40px;
}
.card {
  background:rgba(255,255,255,.96);
  border-radius:28px;
  padding:16px;
  box-shadow:var(--shadow);
  margin-bottom:14px;
}
.header { padding:20px 18px; }
.top-row {
  display:flex;
  justify-content:space-between;
  align-items:center;
  margin-bottom:14px;
}
.app-title {
  font-size:24px;
  font-weight:900;
}
.logout {
  text-decoration:none;
  color:#64748b;
  background:#f1f5f9;
  padding:8px 12px;
  border-radius:999px;
  font-size:12px;
  font-weight:800;
}
.nav {
  display:flex;
  align-items:center;
  justify-content:space-between;
}
.nav a {
  width:46px;
  height:40px;
  border-radius:18px;
  display:flex;
  align-items:center;
  justify-content:center;
  background:#e8eef8;
  color:var(--blue2);
  text-decoration:none;
  font-size:28px;
  font-weight:900;
}
.month {
  font-size:22px;
  font-weight:900;
}
.section-title {
  font-size:18px;
  font-weight:900;
  margin:0 0 12px;
}
.weekdays, .week {
  display:grid;
  grid-template-columns:repeat(7,1fr);
  gap:6px;
}
.weekdays div {
  text-align:center;
  color:var(--muted);
  font-size:12px;
  font-weight:900;
  padding:4px 0 8px;
}
.day-link {
  text-decoration:none;
  color:inherit;
}
.day {
  min-height:52px;
  border-radius:17px;
  background:#f3f4f6;
  text-align:center;
  padding:7px 2px;
  position:relative;
  font-weight:900;
  font-size:14px;
}
.day.other { opacity:.28; }
.day.today {
  background:var(--green);
  color:#fff;
}
.day.has {
  background:var(--soft-blue);
  color:#1d4ed8;
}
.dot {
  width:6px;
  height:6px;
  border-radius:50%;
  background:var(--blue);
  position:absolute;
  left:50%;
  bottom:7px;
  transform:translateX(-50%);
}
.form-grid {
  display:grid;
  gap:10px;
}
label {
  font-size:12px;
  font-weight:900;
  color:#475569;
  margin-bottom:4px;
  display:block;
}
input, textarea, select {
  width:100%;
  border:0;
  outline:none;
  background:#f1f5f9;
  border-radius:16px;
  padding:13px 14px;
  font-size:16px;
  color:var(--text);
}
textarea {
  min-height:88px;
  resize:vertical;
}
.btn {
  width:100%;
  height:48px;
  border:0;
  border-radius:18px;
  background:var(--blue);
  color:#fff;
  font-size:16px;
  font-weight:900;
  margin-top:4px;
}
.owner-buttons {
  display:grid;
  grid-template-columns:1fr 1fr 1fr;
  gap:8px;
}
.owner-radio {
  display:none;
}
.owner-label {
  display:flex;
  align-items:center;
  justify-content:center;
  height:46px;
  border-radius:18px;
  background:#f1f5f9;
  color:#64748b;
  font-size:15px;
  font-weight:900;
  cursor:pointer;
}
.owner-radio:checked + .owner-label.maki {
  background:var(--pink-soft);
  color:var(--pink);
  box-shadow:inset 0 0 0 2px var(--pink);
}
.owner-radio:checked + .owner-label.ryota {
  background:var(--orange-soft);
  color:var(--orange);
  box-shadow:inset 0 0 0 2px var(--orange);
}
.owner-radio:checked + .owner-label.both {
  background:var(--purple-soft);
  color:var(--purple);
  box-shadow:inset 0 0 0 2px var(--purple);
}
.tabs {
  display:grid;
  grid-template-columns:1fr 1fr 1fr;
  gap:8px;
  background:#f1f5f9;
  padding:6px;
  border-radius:20px;
  margin-bottom:12px;
}
.tab-btn {
  border:0;
  height:40px;
  border-radius:16px;
  font-size:14px;
  font-weight:900;
  background:transparent;
  color:#64748b;
}
.tab-btn.active.maki {
  background:#fff;
  color:var(--pink);
  box-shadow:0 4px 12px rgba(236,72,153,.12);
}
.tab-btn.active.ryota {
  background:#fff;
  color:var(--orange);
  box-shadow:0 4px 12px rgba(249,115,22,.12);
}
.tab-btn.active.both {
  background:#fff;
  color:var(--purple);
  box-shadow:0 4px 12px rgba(139,92,246,.12);
}
.tab-panel {
  display:none;
}
.tab-panel.active {
  display:block;
}
.event {
  background:#f8fafc;
  border:1px solid #eef2f7;
  border-radius:22px;
  padding:14px;
  margin:10px 0;
}
.event-head {
  display:flex;
  justify-content:space-between;
  gap:8px;
  align-items:flex-start;
}
.event-date {
  color:var(--blue2);
  font-size:12px;
  font-weight:900;
  margin-bottom:4px;
}
.event-title {
  font-size:16px;
  font-weight:900;
  line-height:1.35;
}
.tag-row {
  display:flex;
  gap:6px;
  flex-wrap:wrap;
  justify-content:flex-end;
}
.tag {
  flex-shrink:0;
  background:#eef4ff;
  color:#2563eb;
  border-radius:999px;
  padding:5px 9px;
  font-size:11px;
  font-weight:900;
}
.owner-tag.maki {
  background:var(--pink-soft);
  color:var(--pink);
}
.owner-tag.ryota {
  background:var(--orange-soft);
  color:var(--orange);
}
.owner-tag.both {
  background:var(--purple-soft);
  color:var(--purple);
}
.event-memo {
  color:#64748b;
  font-size:13px;
  line-height:1.6;
  white-space:pre-wrap;
  margin-top:8px;
}
.link {
  display:block;
  color:#2563eb;
  word-break:break-all;
  font-size:13px;
  margin-top:8px;
  text-decoration:none;
  font-weight:800;
}
.event-actions {
  display:flex;
  gap:8px;
  margin-top:10px;
}
.small-btn {
  flex:1;
  border:0;
  border-radius:14px;
  padding:10px;
  font-weight:900;
  text-align:center;
  text-decoration:none;
  font-size:13px;
}
.edit-btn {
  background:#eef4ff;
  color:#2563eb;
}
.delete-btn {
  background:var(--red-soft);
  color:#dc2626;
}
.empty {
  background:#f8fafc;
  border-radius:20px;
  padding:20px;
  text-align:center;
  color:#64748b;
  font-weight:800;
}
.back {
  display:block;
  text-align:center;
  text-decoration:none;
  color:#475569;
  background:#f1f5f9;
  border-radius:18px;
  padding:13px;
  font-weight:900;
  margin-top:10px;
}
.login-wrap {
  min-height:100vh;
  display:flex;
  align-items:center;
  justify-content:center;
  padding:18px;
}
.login-card {
  width:100%;
  max-width:420px;
  background:#fff;
  border-radius:30px;
  box-shadow:var(--shadow);
  padding:26px;
}
.login-title {
  font-size:25px;
  font-weight:900;
  text-align:center;
  margin-bottom:8px;
}
.login-sub {
  text-align:center;
  color:#64748b;
  margin-bottom:20px;
  font-weight:700;
}
.error {
  background:#fee2e2;
  color:#b91c1c;
  padding:10px;
  border-radius:16px;
  font-weight:800;
  margin-bottom:12px;
}
</style>
"""


LOGIN_TEMPLATE = """
<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>ログイン</title>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">

<link rel="apple-touch-icon" href="/static/icon.png?v=2">

""" + BASE_CSS + """
</head>
<body>
<div class="login-wrap">
  <div class="login-card">
    <div class="login-title">共有カレンダー</div>
    <div class="login-sub">パスワードを入力してください</div>
    {% if error %}
      <div class="error">{{ error }}</div>
    {% endif %}
    <form method="post">
      <input name="pw" type="password" placeholder="パスワード">
      <button class="btn" type="submit">ログイン</button>
    </form>
  </div>
</div>
</body>
</html>
"""


EVENT_CARD_TEMPLATE = """
{% for id, event_date, title, tag, location, memo, url, owner in event_list %}
  <div class="event">
    <div class="event-head">
      <div>
        <div class="event-date">{{ event_date }}</div>
        <div class="event-title">{{ title }}</div>
      </div>

      <div class="tag-row">
        <div class="tag owner-tag {% if owner == '亮太' %}ryota{% elif owner == '二人' %}both{% else %}maki{% endif %}">
          {{ owner or "まき" }}
        </div>
        {% if tag %}
          <div class="tag">{{ tag }}</div>
        {% endif %}
      </div>
    </div>

    {% if location %}
      <div class="event-memo">場所：{{ location }}</div>
    {% endif %}

    {% if memo %}
      <div class="event-memo">{{ memo }}</div>
    {% endif %}

    {% if url %}
      <a class="link" href="{{ url }}" target="_blank">URLを開く</a>
    {% endif %}

    <div class="event-actions">
      <a class="small-btn edit-btn" href="/edit/{{ id }}">編集</a>
      <form method="post" action="/delete/{{ id }}" style="flex:1;margin:0;" onsubmit="return confirm('削除しますか？');">
        <button class="small-btn delete-btn" type="submit" style="width:100%;">削除</button>
      </form>
    </div>
  </div>
{% endfor %}
"""


CALENDAR_TEMPLATE = """
<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>共有カレンダー</title>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
""" + BASE_CSS + """
</head>
<body>
<div class="app">

  <section class="card header">
    <div class="top-row">
      <div class="app-title">共有カレンダー</div>
      <a class="logout" href="/logout">ログアウト</a>
    </div>
    <div class="nav">
      <a href="/calendar?year={{ prev_year }}&month={{ prev_month }}">‹</a>
      <div class="month">{{ year }}年 {{ month }}月</div>
      <a href="/calendar?year={{ next_year }}&month={{ next_month }}">›</a>
    </div>
  </section>

  <section class="card">
    <div class="weekdays">
      <div style="color:#ef4444;">日</div>
      <div>月</div><div>火</div><div>水</div><div>木</div><div>金</div><div>土</div>
    </div>

    {% for week in weeks %}
      <div class="week">
        {% for d in week %}
          {% set ds = d.strftime("%Y-%m-%d") %}
          <a class="day-link" href="/new?date={{ ds }}">
            <div class="day {% if d.month != month %}other{% endif %} {% if d == today %}today{% endif %} {% if ds in events_by_date %}has{% endif %}">
              {{ d.day }}
              {% if ds in events_by_date %}
                <span class="dot"></span>
              {% endif %}
            </div>
          </a>
        {% endfor %}
      </div>
    {% endfor %}
  </section>

  <section class="card">
    <h2 class="section-title">予定追加</h2>
    <form class="form-grid" action="/add" method="post">
      <div>
        <label>日付</label>
        <input name="date" type="date" required>
      </div>

      <div>
        <label>誰の予定？</label>
        <div class="owner-buttons">
          <input class="owner-radio" type="radio" id="owner_maki_main" name="owner" value="まき" checked>
          <label class="owner-label maki" for="owner_maki_main">まき</label>

          <input class="owner-radio" type="radio" id="owner_ryota_main" name="owner" value="亮太">
          <label class="owner-label ryota" for="owner_ryota_main">亮太</label>

          <input class="owner-radio" type="radio" id="owner_both_main" name="owner" value="二人">
          <label class="owner-label both" for="owner_both_main">二人</label>
        </div>
      </div>

      <div>
        <label>タイトル</label>
        <input name="title" required>
      </div>

      <div>
        <label>タグ</label>
        <select name="tag">
          {% for tag in tags %}
            <option value="{{ tag }}">{{ tag }}</option>
          {% endfor %}
        </select>
      </div>

      <div>
        <label>場所</label>
        <input name="location">
      </div>

      <div>
        <label>メモ</label>
        <textarea name="memo"></textarea>
      </div>

      <div>
        <label>URL</label>
        <input name="url">
      </div>

      <button class="btn" type="submit">予定を追加</button>
    </form>
  </section>

  <section class="card">
    <h2 class="section-title">今月の予定</h2>

    <div class="tabs">
      <button type="button" class="tab-btn active maki" onclick="showTab('maki')">まき</button>
      <button type="button" class="tab-btn ryota" onclick="showTab('ryota')">亮太</button>
      <button type="button" class="tab-btn both" onclick="showTab('both')">二人</button>
    </div>

    <div id="tab-maki" class="tab-panel active">
      {% if not maki_events %}
        <div class="empty">まきの予定はまだありません</div>
      {% endif %}
      {% set event_list = maki_events %}
      """ + EVENT_CARD_TEMPLATE + """
    </div>

    <div id="tab-ryota" class="tab-panel">
      {% if not ryota_events %}
        <div class="empty">亮太の予定はまだありません</div>
      {% endif %}
      {% set event_list = ryota_events %}
      """ + EVENT_CARD_TEMPLATE + """
    </div>

    <div id="tab-both" class="tab-panel">
      {% if not both_events %}
        <div class="empty">二人の予定はまだありません</div>
      {% endif %}
      {% set event_list = both_events %}
      """ + EVENT_CARD_TEMPLATE + """
    </div>
  </section>

</div>

<script>
function showTab(name) {
  document.querySelectorAll(".tab-panel").forEach(panel => {
    panel.classList.remove("active");
  });

  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.classList.remove("active");
  });

  document.getElementById("tab-" + name).classList.add("active");
  document.querySelector(".tab-btn." + name).classList.add("active");
}
</script>
</body>
</html>
"""


NEW_TEMPLATE = """
<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>予定追加</title>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
""" + BASE_CSS + """
</head>
<body>
<div class="app">
  <section class="card">
    <h1 class="section-title">予定追加</h1>

    <form class="form-grid" action="/add" method="post">
      <div>
        <label>日付</label>
        <input name="date" type="date" value="{{ selected_date }}" required>
      </div>

      <div>
        <label>誰の予定？</label>
        <div class="owner-buttons">
          <input class="owner-radio" type="radio" id="owner_maki_new" name="owner" value="まき" checked>
          <label class="owner-label maki" for="owner_maki_new">まき</label>

          <input class="owner-radio" type="radio" id="owner_ryota_new" name="owner" value="亮太">
          <label class="owner-label ryota" for="owner_ryota_new">亮太</label>

          <input class="owner-radio" type="radio" id="owner_both_new" name="owner" value="二人">
          <label class="owner-label both" for="owner_both_new">二人</label>
        </div>
      </div>

      <div>
        <label>タイトル</label>
        <input name="title" required>
      </div>

      <div>
        <label>タグ</label>
        <select name="tag">
          {% for tag in tags %}
            <option value="{{ tag }}">{{ tag }}</option>
          {% endfor %}
        </select>
      </div>

      <div>
        <label>場所</label>
        <input name="location">
      </div>

      <div>
        <label>メモ</label>
        <textarea name="memo"></textarea>
      </div>

      <div>
        <label>URL</label>
        <input name="url">
      </div>

      <button class="btn" type="submit">予定を追加</button>
    </form>

    <a class="back" href="/calendar">戻る</a>
  </section>
</div>
</body>
</html>
"""


EDIT_TEMPLATE = """
<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>予定編集</title>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
""" + BASE_CSS + """
</head>
<body>
<div class="app">
  <section class="card">
    <h1 class="section-title">予定編集</h1>

    <form class="form-grid" method="post">
      <div>
        <label>日付</label>
        <input name="date" type="date" value="{{ event[1] }}" required>
      </div>

      <div>
        <label>誰の予定？</label>
        <div class="owner-buttons">
          <input class="owner-radio" type="radio" id="owner_maki_edit" name="owner" value="まき" {% if event[7] != "亮太" and event[7] != "二人" %}checked{% endif %}>
          <label class="owner-label maki" for="owner_maki_edit">まき</label>

          <input class="owner-radio" type="radio" id="owner_ryota_edit" name="owner" value="亮太" {% if event[7] == "亮太" %}checked{% endif %}>
          <label class="owner-label ryota" for="owner_ryota_edit">亮太</label>

          <input class="owner-radio" type="radio" id="owner_both_edit" name="owner" value="二人" {% if event[7] == "二人" %}checked{% endif %}>
          <label class="owner-label both" for="owner_both_edit">二人</label>
        </div>
      </div>

      <div>
        <label>タイトル</label>
        <input name="title" value="{{ event[2] }}" required>
      </div>

      <div>
        <label>タグ</label>
        <select name="tag">
          {% for tag in tags %}
            <option value="{{ tag }}" {% if event[3] == tag %}selected{% endif %}>{{ tag }}</option>
          {% endfor %}
        </select>
      </div>

      <div>
        <label>場所</label>
        <input name="location" value="{{ event[4] or '' }}">
      </div>

      <div>
        <label>メモ</label>
        <textarea name="memo">{{ event[5] or "" }}</textarea>
      </div>

      <div>
        <label>URL</label>
        <input name="url" value="{{ event[6] or '' }}">
      </div>

      <button class="btn" type="submit">更新する</button>
    </form>

    <a class="back" href="/calendar">戻る</a>
  </section>
</div>
</body>
</html>
"""


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
