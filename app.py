import os
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request, redirect, session, render_template, url_for
from datetime import date

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "secret")

DATABASE_URL = os.environ.get("DATABASE_URL")
PASSWORD = os.environ.get("APP_PASSWORD", "1234")

def get_conn():
    return psycopg2.connect(DATABASE_URL)

def login_required():
    return session.get("login") is True

@app.route("/", methods=["GET", "POST"])
def login():
    if login_required():
        return redirect("/calendar")

    error = ""
    if request.method == "POST":
        if request.form.get("pw") == PASSWORD:
            session["login"] = True
            return redirect("/calendar")
        error = "パスワード違う"

    return render_template("login.html", error=error)

@app.route("/calendar")
def calendar_view():
    if not login_required():
        return redirect("/")

    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("SELECT * FROM events ORDER BY start_date")
    events = cur.fetchall()

    conn.close()

    return render_template(
        "calendar.html",
        events=events,
        today=date.today()
    )

@app.route("/add", methods=["POST"])
def add():
    if not login_required():
        return redirect("/")

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO events (
            start_date, end_date, title, tag, owner,
            location, memo, url, start_time, end_time
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        request.form.get("start_date"),
        request.form.get("end_date") or request.form.get("start_date"),
        request.form.get("title"),
        request.form.get("tag"),
        request.form.get("owner"),
        request.form.get("location"),
        request.form.get("memo"),
        request.form.get("url"),
        f"{request.form.get('start_hour')}:{request.form.get('start_minute')}" if request.form.get('start_hour') else None,
        f"{request.form.get('end_hour')}:{request.form.get('end_minute')}" if request.form.get('end_hour') else None
    ))

    conn.commit()
    conn.close()

    return redirect("/calendar")

@app.route("/delete/<int:id>", methods=["POST"])
def delete(id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM events WHERE id = %s", (id,))
    conn.commit()
    conn.close()
    return redirect("/calendar")

if __name__ == "__main__":
    app.run()