import os
import random
import sqlite3
import threading
import time
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from authlib.integrations.flask_client import OAuth
from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

DB_PATH = os.environ.get("DB_PATH", str(Path(__file__).parent / "wichteln.db"))
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

BACKUP_DIR = os.environ.get("BACKUP_DIR", str(Path(__file__).parent / "backups"))
BACKUP_INTERVAL_SECONDS = int(os.environ.get("BACKUP_INTERVAL_HOURS", "24")) * 3600
BACKUP_KEEP = int(os.environ.get("BACKUP_KEEP", "14"))

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

oauth = OAuth(app)
oauth.register(
    name="authentik",
    server_metadata_url=os.environ["OIDC_ISSUER"].rstrip("/") + "/.well-known/openid-configuration",
    client_id=os.environ["OIDC_CLIENT_ID"],
    client_secret=os.environ["OIDC_CLIENT_SECRET"],
    client_kwargs={"scope": "openid email profile"},
)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript((Path(__file__).parent / "schema.sql").read_text())
    db.commit()
    db.close()


def backup_once():
    Path(BACKUP_DIR).mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest_path = Path(BACKUP_DIR) / f"wichteln-{stamp}.db"

    src = sqlite3.connect(DB_PATH)
    dest = sqlite3.connect(dest_path)
    with dest:
        src.backup(dest)
    src.close()
    dest.close()

    backups = sorted(Path(BACKUP_DIR).glob("wichteln-*.db"))
    for old in backups[:-BACKUP_KEEP]:
        old.unlink()


def backup_loop():
    while True:
        try:
            backup_once()
        except Exception as exc:
            app.logger.exception("Scheduled backup failed: %s", exc)
        time.sleep(BACKUP_INTERVAL_SECONDS)


def current_user():
    user_id = session.get("user_id")
    if user_id is None:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def get_group_or_404(group_id, user_id):
    group = get_db().execute(
        """
        SELECT groups.* FROM groups
        JOIN group_members ON group_members.group_id = groups.id
        WHERE groups.id = ? AND group_members.user_id = ?
        """,
        (group_id, user_id),
    ).fetchone()
    if group is None:
        abort(404)
    return group


def draw_names(db, group_id):
    member_ids = [
        row["user_id"]
        for row in db.execute("SELECT user_id FROM group_members WHERE group_id = ?", (group_id,)).fetchall()
    ]
    exclusions = {
        (row["user_id_a"], row["user_id_b"])
        for row in db.execute(
            "SELECT user_id_a, user_id_b FROM exclusions WHERE group_id = ?", (group_id,)
        ).fetchall()
    }

    def excluded(a, b):
        pair = (min(a, b), max(a, b))
        return pair in exclusions

    for _ in range(1000):
        receivers = member_ids[:]
        random.shuffle(receivers)
        if all(giver != recv and not excluded(giver, recv) for giver, recv in zip(member_ids, receivers)):
            return list(zip(member_ids, receivers))
    return None


@app.route("/")
def index():
    user = current_user()
    if user is None:
        return render_template("index.html", user=None, groups=None)
    groups = get_db().execute(
        """
        SELECT groups.* FROM groups
        JOIN group_members ON group_members.group_id = groups.id
        WHERE group_members.user_id = ?
        ORDER BY groups.id DESC
        """,
        (user["id"],),
    ).fetchall()
    return render_template("index.html", user=user, groups=groups)


@app.route("/login")
def login():
    return oauth.authentik.authorize_redirect(url_for("auth_callback", _external=True))


@app.route("/auth/callback")
def auth_callback():
    token = oauth.authentik.authorize_access_token()
    claims = token["userinfo"]
    db = get_db()
    db.execute(
        """
        INSERT INTO users (sub, email, name) VALUES (?, ?, ?)
        ON CONFLICT(sub) DO UPDATE SET email = excluded.email, name = excluded.name
        """,
        (claims["sub"], claims.get("email"), claims.get("name", claims.get("email", claims["sub"]))),
    )
    db.commit()
    user = db.execute("SELECT * FROM users WHERE sub = ?", (claims["sub"],)).fetchone()
    session["user_id"] = user["id"]
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/groups/new", methods=["GET", "POST"])
@login_required
def group_new():
    user = current_user()
    db = get_db()
    all_users = db.execute("SELECT * FROM users ORDER BY name").fetchall()

    if request.method == "POST":
        name = request.form["name"].strip()
        member_ids = {int(x) for x in request.form.getlist("member_ids")}
        member_ids.add(user["id"])
        if not name:
            flash("Group name is required.")
            return render_template("group_new.html", all_users=all_users)

        cur = db.execute("INSERT INTO groups (name, owner_id) VALUES (?, ?)", (name, user["id"]))
        group_id = cur.lastrowid
        db.executemany(
            "INSERT INTO group_members (group_id, user_id) VALUES (?, ?)",
            [(group_id, uid) for uid in member_ids],
        )
        db.commit()
        return redirect(url_for("group_detail", group_id=group_id))

    return render_template("group_new.html", all_users=all_users)


@app.route("/groups/<int:group_id>")
@login_required
def group_detail(group_id):
    user = current_user()
    db = get_db()
    group = get_group_or_404(group_id, user["id"])

    members = db.execute(
        """
        SELECT users.* FROM users
        JOIN group_members ON group_members.user_id = users.id
        WHERE group_members.group_id = ?
        ORDER BY users.name
        """,
        (group_id,),
    ).fetchall()

    exclusions = db.execute(
        """
        SELECT exclusions.*, a.name AS name_a, b.name AS name_b FROM exclusions
        JOIN users a ON a.id = exclusions.user_id_a
        JOIN users b ON b.id = exclusions.user_id_b
        WHERE exclusions.group_id = ?
        """,
        (group_id,),
    ).fetchall()

    non_members = db.execute(
        """
        SELECT * FROM users
        WHERE id NOT IN (SELECT user_id FROM group_members WHERE group_id = ?)
        ORDER BY name
        """,
        (group_id,),
    ).fetchall()

    my_items = db.execute(
        "SELECT * FROM wishlist_items WHERE group_id = ? AND user_id = ? ORDER BY id",
        (group_id, user["id"]),
    ).fetchall()

    receiver = None
    receiver_items = None
    if group["drawn_at"] is not None:
        assignment = db.execute(
            "SELECT receiver_id FROM assignments WHERE group_id = ? AND giver_id = ?",
            (group_id, user["id"]),
        ).fetchone()
        if assignment is not None:
            receiver = db.execute("SELECT * FROM users WHERE id = ?", (assignment["receiver_id"],)).fetchone()
            receiver_items = db.execute(
                "SELECT * FROM wishlist_items WHERE group_id = ? AND user_id = ? ORDER BY id",
                (group_id, receiver["id"]),
            ).fetchall()

    return render_template(
        "group.html",
        user=user,
        group=group,
        members=members,
        non_members=non_members,
        exclusions=exclusions,
        my_items=my_items,
        receiver=receiver,
        receiver_items=receiver_items,
    )


@app.route("/groups/<int:group_id>/members/add", methods=["POST"])
@login_required
def member_add(group_id):
    user = current_user()
    db = get_db()
    group = get_group_or_404(group_id, user["id"])
    if group["owner_id"] != user["id"] or group["drawn_at"] is not None:
        abort(403)

    new_member_id = int(request.form["user_id"])
    db.execute(
        "INSERT OR IGNORE INTO group_members (group_id, user_id) VALUES (?, ?)",
        (group_id, new_member_id),
    )
    db.commit()
    return redirect(url_for("group_detail", group_id=group_id))


@app.route("/groups/<int:group_id>/draw", methods=["POST"])
@login_required
def group_draw(group_id):
    user = current_user()
    db = get_db()
    group = get_group_or_404(group_id, user["id"])
    if group["owner_id"] != user["id"]:
        abort(403)
    if group["drawn_at"] is not None:
        return redirect(url_for("group_detail", group_id=group_id))

    pairs = draw_names(db, group_id)
    if pairs is None:
        flash("Could not find a valid draw with the current exclusions. Try removing some exclusions.")
        return redirect(url_for("group_detail", group_id=group_id))

    db.executemany(
        "INSERT INTO assignments (group_id, giver_id, receiver_id) VALUES (?, ?, ?)",
        [(group_id, giver, receiver) for giver, receiver in pairs],
    )
    db.execute("UPDATE groups SET drawn_at = datetime('now') WHERE id = ?", (group_id,))
    db.commit()
    return redirect(url_for("group_detail", group_id=group_id))


@app.route("/groups/<int:group_id>/wishlist/add", methods=["POST"])
@login_required
def wishlist_add(group_id):
    user = current_user()
    db = get_db()
    get_group_or_404(group_id, user["id"])
    text = request.form["text"].strip()
    if text:
        db.execute(
            "INSERT INTO wishlist_items (group_id, user_id, text) VALUES (?, ?, ?)",
            (group_id, user["id"], text),
        )
        db.commit()
    return redirect(url_for("group_detail", group_id=group_id))


@app.route("/groups/<int:group_id>/wishlist/<int:item_id>/delete", methods=["POST"])
@login_required
def wishlist_delete(group_id, item_id):
    user = current_user()
    db = get_db()
    get_group_or_404(group_id, user["id"])
    db.execute(
        "DELETE FROM wishlist_items WHERE id = ? AND group_id = ? AND user_id = ?",
        (item_id, group_id, user["id"]),
    )
    db.commit()
    return redirect(url_for("group_detail", group_id=group_id))


@app.route("/groups/<int:group_id>/exclusions/add", methods=["POST"])
@login_required
def exclusion_add(group_id):
    user = current_user()
    db = get_db()
    group = get_group_or_404(group_id, user["id"])
    if group["owner_id"] != user["id"] or group["drawn_at"] is not None:
        abort(403)

    a, b = int(request.form["user_id_a"]), int(request.form["user_id_b"])
    if a != b:
        lo, hi = min(a, b), max(a, b)
        db.execute(
            "INSERT OR IGNORE INTO exclusions (group_id, user_id_a, user_id_b) VALUES (?, ?, ?)",
            (group_id, lo, hi),
        )
        db.commit()
    return redirect(url_for("group_detail", group_id=group_id))


@app.route("/groups/<int:group_id>/exclusions/<int:user_id_a>/<int:user_id_b>/delete", methods=["POST"])
@login_required
def exclusion_delete(group_id, user_id_a, user_id_b):
    user = current_user()
    db = get_db()
    group = get_group_or_404(group_id, user["id"])
    if group["owner_id"] != user["id"] or group["drawn_at"] is not None:
        abort(403)

    db.execute(
        "DELETE FROM exclusions WHERE group_id = ? AND user_id_a = ? AND user_id_b = ?",
        (group_id, user_id_a, user_id_b),
    )
    db.commit()
    return redirect(url_for("group_detail", group_id=group_id))


init_db()
threading.Thread(target=backup_loop, daemon=True).start()
