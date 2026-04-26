import os
import sqlite3
import calendar
from datetime import date
from flask import Flask, request, redirect, session, render_template_string

app = Flask(__name__)
app.secret_key = "secret-key"

PASSWORD = "0814"

DB = "events.db"


def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            title TEXT,
            memo TEXT,
            url TEXT,
            image_url TEXT,
            tag TEXT
        )
    """)
    conn.commit()
    conn.close()


init_db()


def get_events():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT * FROM events ORDER BY date")
    rows = cur.fetchall()
    conn.close()
    return rows


@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("pw") == PASSWORD:
            session["login"] = True
            return redirect("/calendar")
    return """
    <form method="post" style="padding:40px;text-align:center;">
    <h2>パスワード</h2>
    <input name="pw" type="password" style="font-size:20px;">
    <br><br>
    <button style="font-size:20px;">ログイン</button>
    </form>
    """


@app.route("/calendar")
def calendar_view():
    if not session.get("login"):
        return redirect("/")

    today = date.today()
    year = int(request.args.get("year", today.year))
    month = int(request.args.get("month", today.month))

    events = get_events()

    event_dict = {}
    for e in events:
        event_dict.setdefault(e[1], []).append(e)

    cal = calendar.monthcalendar(year, month)

    return render_template_string("""
    <h2>{{year}}年 {{month}}月</h2>

    <a href="/calendar?year={{year}}&month={{month-1}}">◀</a>
    <a href="/calendar?year={{year}}&month={{month+1}}">▶</a>

    <table border=1>
    {% for week in cal %}
    <tr>
    {% for d in week %}
    <td>
    {{d}}
    {% set key = "%04d-%02d-%02d"|format(year,month,d) %}
    {% if key in events %}
        {% for e in events[key] %}
        <div style="background:#ddd;margin:2px;">
            {{e[2]}}<br>
            <a href="/edit/{{e[0]}}">編集</a>
            <a href="/delete/{{e[0]}}">削除</a>
        </div>
        {% endfor %}
    {% endif %}
    </td>
    {% endfor %}
    </tr>
    {% endfor %}
    </table>

    <hr>

    <h3>予定追加</h3>
    <form action="/add" method="post">
    日付<input name="date"><br>
    タイトル<input name="title"><br>
    メモ<textarea name="memo"></textarea><br>
    URL<input name="url"><br>
    画像URL<input name="image_url"><br>
    タグ<input name="tag"><br>
    <button>追加</button>
    </form>

    <hr>
    <h3>今月の予定</h3>
    {% for e in events_list %}
        {{e[1]}} {{e[2]}} {{e[6]}}<br>
    {% endfor %}
    """,
    year=year,
    month=month,
    cal=cal,
    events=event_dict,
    events_list=events
    )


@app.route("/add", methods=["POST"])
def add():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO events(date,title,memo,url,image_url,tag)
        VALUES (?,?,?,?,?,?)
    """, (
        request.form["date"],
        request.form["title"],
        request.form["memo"],
        request.form["url"],
        request.form["image_url"],
        request.form["tag"]
    ))
    conn.commit()
    conn.close()
    return redirect("/calendar")


@app.route("/delete/<int:id>")
def delete(id):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("DELETE FROM events WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return redirect("/calendar")


@app.route("/edit/<int:id>", methods=["GET", "POST"])
def edit(id):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    if request.method == "POST":
        cur.execute("""
            UPDATE events
            SET date=?,title=?,memo=?,url=?,image_url=?,tag=?
            WHERE id=?
        """, (
            request.form["date"],
            request.form["title"],
            request.form["memo"],
            request.form["url"],
            request.form["image_url"],
            request.form["tag"],
            id
        ))
        conn.commit()
        conn.close()
        return redirect("/calendar")

    cur.execute("SELECT * FROM events WHERE id=?", (id,))
    e = cur.fetchone()
    conn.close()

    return f"""
    <form method="post">
    日付<input name="date" value="{e[1]}"><br>
    タイトル<input name="title" value="{e[2]}"><br>
    メモ<textarea name="memo">{e[3]}</textarea><br>
    URL<input name="url" value="{e[4]}"><br>
    画像URL<input name="image_url" value="{e[5]}"><br>
    タグ<input name="tag" value="{e[6]}"><br>
    <button>更新</button>
    </form>
    """


if __name__ == "__main__":
    app.run()