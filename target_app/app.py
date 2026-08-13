"""Mock banking portal Flask application.

Simulates a legacy credit union member servicing tool with intentionally
messy HTML (table layouts, no test IDs, deep nesting) to mirror real legacy
banking systems. Accessibility tree remains navigable via aria-labels.
"""

import random
import time
from datetime import timedelta

from flask import Flask, redirect, render_template, request, session, url_for

from target_app.data import CREDENTIALS, MEMBERS

app = Flask(__name__)
app.secret_key = "dev-secret-key-not-for-production"
app.permanent_session_lifetime = timedelta(minutes=5)


def _is_authenticated() -> bool:
    return session.get("logged_in", False)


@app.before_request
def enforce_session() -> None:
    """Redirect unauthenticated requests away from protected routes."""
    public = {"login", "static"}
    if request.endpoint not in public and not _is_authenticated():
        return redirect(url_for("login"))


@app.route("/")
def index():
    return redirect(url_for("search"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if CREDENTIALS.get(username) == password:
            session.permanent = True
            session["logged_in"] = True
            session["username"] = username
            return redirect(url_for("search"))
        error = "Invalid username or password. Please try again."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/search", methods=["GET", "POST"])
def search():
    # 5% random system error to test recoverable error handling
    if random.random() < 0.05:
        return render_template("error.html", message="Unexpected system error. Please retry.")

    result = None
    not_found = False
    if request.method == "POST":
        member_id = request.form.get("member_id", "").strip()
        if member_id in MEMBERS:
            return redirect(url_for("member_detail", member_id=member_id))
        not_found = True
        result = member_id

    return render_template("search.html", not_found=not_found, searched_id=result)


@app.route("/member/<member_id>")
def member_detail(member_id: str):
    # 5% random system error
    if random.random() < 0.05:
        return render_template("error.html", message="Unexpected system error. Please retry.")

    member = MEMBERS.get(member_id)
    if not member:
        return render_template("search.html", not_found=True, searched_id=member_id)

    if member["status"] == "restricted":
        return render_template(
            "member_detail.html",
            member=member,
            member_id=member_id,
            permission_denied=True,
        )

    if member["status"] == "slow":
        # Simulate a 10-second delay for transient slowness testing
        time.sleep(10)

    return render_template(
        "member_detail.html",
        member=member,
        member_id=member_id,
        permission_denied=False,
    )


@app.route("/member/<member_id>/open-subaccount", methods=["GET", "POST"])
def open_subaccount(member_id: str):
    member = MEMBERS.get(member_id)
    if not member:
        return render_template("search.html", not_found=True, searched_id=member_id)

    if member["status"] == "restricted":
        return render_template("error.html", message="Permission denied — restricted account.")

    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "confirm":
            return render_template(
                "action_confirm.html",
                member=member,
                member_id=member_id,
                confirmed=True,
            )
        return redirect(url_for("member_detail", member_id=member_id))

    return render_template(
        "action_confirm.html",
        member=member,
        member_id=member_id,
        confirmed=False,
    )


if __name__ == "__main__":
    app.run(debug=True, port=5001, host="127.0.0.1")
