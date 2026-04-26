import os
import re
import sqlite3
import calendar
from datetime import date, datetime
from pathlib import Path

from flask import Flask, request, redirect, url_for, render_template_string, flash
from PIL import Image, ImageOps, ImageEnhance
import pytesseract


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "calendar_events.db"
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_date TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT,
            source TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def db_rows(year, month):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    last_day = calendar.monthrange(year, month)[1]
    start = f"{year}-{month:02d}-01"
    end = f"{year}-{month:02d}-{last_day:02d}"

    cur.execute("""
        SELECT id, event_date, title, body, source
        FROM events
        WHERE event_date BETWEEN ? AND ?
        ORDER BY event_date ASC, id ASC
    """, (start, end))

    rows = cur.fetchall()
    conn.close()
    return rows


def clean_ocr_text(text):
    lines = text.splitlines()
    cleaned = []

    noise_patterns = [
        r"^[\W_]{1,}$",
        r"^[|｜/\\\-_.,:;!?\s]+$",
        r"^[a-zA-Z]{1,2}$",
    ]

    for line in lines:
        line = line.strip()
        if not line:
            continue

        line = line.replace("　", " ")
        line = re.sub(r"\s+", " ", line)

        if any(re.match(pat, line) for pat in noise_patterns):
            continue

        cleaned.append(line)

    result = []
    prev = None
    for line in cleaned:
        if line != prev:
            result.append(line)
        prev = line

    return result


def extract_date(text):
    now_year = date.today().year

    m = re.search(r"(\d{4})\s*[年/-]\s*(\d{1,2})\s*[月/-]\s*(\d{1,2})\s*日?", text)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
    if m:
        return f"{now_year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"

    m = re.search(r"(?<!\d)(\d{1,2})\s*/\s*(\d{1,2})(?!\d)", text)
    if m:
        mo = int(m.group(1))
        d = int(m.group(2))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{now_year}-{mo:02d}-{d:02d}"

    return ""


def extract_title(text):
    lines = clean_ocr_text(text)

    keywords = [
        "撮影会", "イベント", "生誕", "オフ会",
        "出演", "予約", "開催", "告知", "個撮",
        "セッション", "お知らせ"
    ]

    for line in lines:
        if any(k in line for k in keywords):
            return line[:45]

    for line in lines:
        if len(line) >= 4:
            return line[:45]

    return "画像から登録した予定"


def format_post_text(raw_text, event_date, title):
    lines = clean_ocr_text(raw_text)

    body_lines = []
    for line in lines:
        if line == title:
            continue
        if len(line) <= 1:
            continue
        body_lines.append(line)

    if not body_lines:
        body_lines = ["OCR結果を確認してください。"]

    return f"""【イベント情報】
{title}

【日付】
{event_date}

【投稿内容】
{chr(10).join(body_lines)}
"""


def ocr_image(path):
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    img = img.convert("L")

    w, h = img.size
    img = img.resize((w * 3, h * 3), Image.Resampling.LANCZOS)
    img = ImageEnhance.Contrast(img).enhance(2.5)
    img = img.point(lambda p: 255 if p > 170 else 0)

    return pytesseract.image_to_string(
        img,
        lang="jpn+eng",
        config="--psm 11"
    )


@app.route("/")
def index():
    today = date.today()

    year = int(request.args.get("year", today.year))
    month = int(request.args.get("month", today.month))

    if month < 1:
        year -= 1
        month = 12
    elif month > 12:
        year += 1
        month = 1

    rows = db_rows(year, month)

    events_by_date = {}
    for row in rows:
        event_id, event_date, title, body, source = row
        events_by_date.setdefault(event_date, []).append({
            "id": event_id,
            "date": event_date,
            "title": title,
            "body": body or ""
        })

    cal = calendar.Calendar(firstweekday=6)
    weeks = cal.monthdatescalendar(year, month)

    return render_template_string(
        TEMPLATE,
        year=year,
        month=month,
        weeks=weeks,
        today=today,
        events=events_by_date,
        flat_events=rows,
        prev_year=year if month > 1 else year - 1,
        prev_month=month - 1 if month > 1 else 12,
        next_year=year if month < 12 else year + 1,
        next_month=month + 1 if month < 12 else 1,
    )


@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("image")
    if not file or file.filename == "":
        flash("画像を選択してください。")
        return redirect(url_for("index"))

    ext = Path(file.filename).suffix.lower()
    if ext not in [".png", ".jpg", ".jpeg", ".webp", ".bmp"]:
        flash("画像ファイルを選択してください。")
        return redirect(url_for("index"))

    filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
    save_path = UPLOAD_DIR / filename
    file.save(save_path)

    try:
        text = ocr_image(save_path)
    except Exception as e:
        flash(f"OCRに失敗しました: {e}")
        return redirect(url_for("index"))

    event_date = extract_date(text)
    title = extract_title(text)
    body = format_post_text(text, event_date or "日付未設定", title)

    return render_template_string(
        CONFIRM_TEMPLATE,
        event_date=event_date,
        title=title,
        body=body,
        source=str(save_path),
        raw_text=text
    )


@app.route("/save", methods=["POST"])
def save():
    event_date = request.form.get("event_date", "").strip()
    title = request.form.get("title", "").strip()
    body = request.form.get("body", "").strip()
    source = request.form.get("source", "").strip()

    if not event_date or not title:
        flash("日付とタイトルは必須です。")
        return redirect(url_for("index"))

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO events (event_date, title, body, source, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        event_date,
        title,
        body,
        source,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()
    conn.close()

    y, m, _ = event_date.split("-")
    return redirect(url_for("index", year=int(y), month=int(m)))


@app.route("/delete/<int:event_id>", methods=["POST"])
def delete(event_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM events WHERE id = ?", (event_id,))
    conn.commit()
    conn.close()

    return redirect(request.referrer or url_for("index"))


TEMPLATE = """
<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>撮影会カレンダー</title>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>
:root {
  --bg:#f4f7fb;
  --card:#ffffff;
  --blue:#3b82f6;
  --blue-soft:#dbeafe;
  --text:#111827;
  --muted:#6b7280;
  --danger:#ef4444;
  --green:#22c55e;
}
* { box-sizing:border-box; }
body {
  margin:0;
  background:var(--bg);
  color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Hiragino Sans","Yu Gothic UI",sans-serif;
}
.app {
  max-width:520px;
  margin:0 auto;
  padding:14px;
  padding-bottom:40px;
}
.header {
  background:var(--card);
  border-radius:28px;
  padding:18px;
  box-shadow:0 8px 24px rgba(15,23,42,.06);
  margin-bottom:12px;
}
h1 {
  margin:0 0 12px;
  font-size:24px;
  text-align:center;
}
.nav {
  display:flex;
  align-items:center;
  justify-content:space-between;
}
.nav a {
  width:44px;
  height:38px;
  border-radius:18px;
  display:flex;
  align-items:center;
  justify-content:center;
  text-decoration:none;
  background:#e8eef8;
  color:#2563eb;
  font-size:26px;
  font-weight:800;
}
.month {
  font-size:21px;
  font-weight:800;
}
.card {
  background:var(--card);
  border-radius:28px;
  padding:16px;
  box-shadow:0 8px 24px rgba(15,23,42,.06);
  margin-bottom:12px;
}
.upload input[type=file] {
  width:100%;
  padding:12px;
  background:#f9fafb;
  border-radius:16px;
}
.btn {
  width:100%;
  border:none;
  border-radius:18px;
  height:46px;
  color:white;
  background:var(--blue);
  font-weight:800;
  font-size:15px;
  margin-top:10px;
}
.weekdays, .week {
  display:grid;
  grid-template-columns:repeat(7,1fr);
  gap:5px;
}
.weekdays div {
  text-align:center;
  color:var(--muted);
  font-size:12px;
  font-weight:800;
  padding:6px 0;
}
.day {
  min-height:48px;
  border-radius:16px;
  background:#f3f4f6;
  padding:6px;
  text-align:center;
  font-weight:800;
  position:relative;
}
.day.other { opacity:.32; }
.day.today { background:var(--green); color:white; }
.day.has { background:var(--blue-soft); color:#1d4ed8; }
.dot {
  width:6px;
  height:6px;
  border-radius:50%;
  background:var(--blue);
  position:absolute;
  bottom:6px;
  left:50%;
  transform:translateX(-50%);
}
.event {
  background:#f9fafb;
  border-radius:20px;
  padding:12px;
  margin:10px 0;
}
.event-date {
  color:#2563eb;
  font-weight:800;
  font-size:12px;
}
.event-title {
  font-weight:900;
  margin-top:3px;
}
.event-body {
  white-space:pre-wrap;
  color:var(--muted);
  font-size:13px;
  margin-top:6px;
  max-height:90px;
  overflow:hidden;
}
.delete {
  border:none;
  background:#fee2e2;
  color:#dc2626;
  padding:8px 12px;
  border-radius:14px;
  font-weight:800;
  margin-top:8px;
}
.flash {
  background:#fff7ed;
  color:#c2410c;
  border-radius:18px;
  padding:10px;
  margin-bottom:10px;
  font-weight:700;
}
</style>
</head>
<body>
<div class="app">

  {% with messages = get_flashed_messages() %}
    {% if messages %}
      {% for msg in messages %}
        <div class="flash">{{ msg }}</div>
      {% endfor %}
    {% endif %}
  {% endwith %}

  <section class="header">
    <h1>撮影会カレンダー</h1>
    <div class="nav">
      <a href="/?year={{ prev_year }}&month={{ prev_month }}">‹</a>
      <div class="month">{{ year }}年 {{ month }}月</div>
      <a href="/?year={{ next_year }}&month={{ next_month }}">›</a>
    </div>
  </section>

  <section class="card upload">
    <form action="/upload" method="post" enctype="multipart/form-data">
      <input type="file" name="image" accept="image/*" required>
      <button class="btn" type="submit">画像から予定を登録</button>
    </form>
  </section>

  <section class="card">
    <div class="weekdays">
      <div style="color:#ef4444;">日</div><div>月</div><div>火</div><div>水</div><div>木</div><div>金</div><div>土</div>
    </div>
    {% for week in weeks %}
      <div class="week">
        {% for d in week %}
          {% set ds = d.strftime("%Y-%m-%d") %}
          <div class="day {% if d.month != month %}other{% endif %} {% if d == today %}today{% endif %} {% if ds in events %}has{% endif %}">
            {{ d.day }}
            {% if ds in events %}<span class="dot"></span>{% endif %}
          </div>
        {% endfor %}
      </div>
    {% endfor %}
  </section>

  <section class="card">
    <h2 style="margin:0 0 8px;font-size:18px;">今月の予定</h2>
    {% if not flat_events %}
      <div class="event">予定はまだありません</div>
    {% endif %}

    {% for event_id, event_date, title, body, source in flat_events %}
      <div class="event">
        <div class="event-date">{{ event_date }}</div>
        <div class="event-title">{{ title }}</div>
        <div class="event-body">{{ body }}</div>
        <form method="post" action="/delete/{{ event_id }}" onsubmit="return confirm('削除しますか？');">
          <button class="delete" type="submit">削除</button>
        </form>
      </div>
    {% endfor %}
  </section>

</div>
</body>
</html>
"""


CONFIRM_TEMPLATE = """
<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>OCR結果確認</title>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>
* { box-sizing:border-box; }
body {
  margin:0;
  background:#f4f7fb;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Hiragino Sans","Yu Gothic UI",sans-serif;
  color:#111827;
}
.app {
  max-width:520px;
  margin:0 auto;
  padding:14px;
}
.card {
  background:#fff;
  border-radius:28px;
  padding:18px;
  box-shadow:0 8px 24px rgba(15,23,42,.06);
}
h1 {
  font-size:23px;
  margin:0 0 16px;
  text-align:center;
}
label {
  display:block;
  font-weight:800;
  color:#374151;
  margin:12px 0 6px;
}
input, textarea {
  width:100%;
  border:0;
  background:#f3f4f6;
  border-radius:16px;
  padding:12px;
  font-size:16px;
}
textarea {
  min-height:320px;
  resize:vertical;
  white-space:pre-wrap;
}
.btn {
  width:100%;
  height:48px;
  border:0;
  border-radius:18px;
  background:#3b82f6;
  color:white;
  font-size:16px;
  font-weight:900;
  margin-top:14px;
}
.back {
  display:block;
  text-align:center;
  text-decoration:none;
  color:#374151;
  background:#f3f4f6;
  border-radius:18px;
  padding:13px;
  font-weight:800;
  margin-top:10px;
}
.raw {
  margin-top:12px;
  color:#6b7280;
  font-size:12px;
  white-space:pre-wrap;
}
</style>
</head>
<body>
<div class="app">
  <div class="card">
    <h1>読み取り結果を確認</h1>
    <form action="/save" method="post">
      <input type="hidden" name="source" value="{{ source }}">

      <label>日付</label>
      <input name="event_date" value="{{ event_date }}" placeholder="例：2026-05-30" required>

      <label>タイトル</label>
      <input name="title" value="{{ title }}" required>

      <label>整形後メモ</label>
      <textarea name="body">{{ body }}</textarea>

      <button class="btn" type="submit">カレンダーに登録</button>
    </form>

    <a class="back" href="/">キャンセル</a>

    <details>
      <summary style="margin-top:14px;color:#6b7280;">OCR生データを見る</summary>
      <div class="raw">{{ raw_text }}</div>
    </details>
  </div>
</div>
</body>
</html>
"""


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)