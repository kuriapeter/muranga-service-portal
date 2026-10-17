
import os
import secrets
import string

from flask import (
    Flask, render_template, redirect, url_for,
    request, flash, abort
)
from flask_login import (
    LoginManager, current_user, login_user,
    logout_user, login_required
)
from flask_wtf.csrf import CSRFProtect
from sqlalchemy.exc import IntegrityError

from config import Config
from models import db, User, ServiceRequest


app = Flask(__name__)
app.config.from_object(Config)

# Use SQLite locally until Neon is configured.
# On Vercel, set DATABASE_URL to your Neon PostgreSQL connection URL.

if not app.config.get("SQLALCHEMY_DATABASE_URI"):
    if not os.getenv("VERCEL"):
        os.makedirs(app.instance_path, exist_ok=True)
        app.config["SQLALCHEMY_DATABASE_URI"] = (
            "sqlite:///" + os.path.join(app.instance_path, "portal.db")
        )

# Normalize PostgreSQL URLs for the psycopg driver.
database_url = app.config["SQLALCHEMY_DATABASE_URI"]
if database_url.startswith("postgres://"):
    database_url = database_url.replace(
        "postgres://", "postgresql+psycopg://", 1
    )
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace(
        "postgresql://", "postgresql+psycopg://", 1
    )
app.config["SQLALCHEMY_DATABASE_URI"] = database_url

# Never use the development fallback key on a deployed site.
if os.getenv("VERCEL") and not os.getenv("SECRET_KEY"):
    raise RuntimeError("Set SECRET_KEY in Vercel environment variables.")

db.init_app(app)

csrf = CSRFProtect(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to access that page."


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def generate_tracking_code():
    alphabet = string.ascii_uppercase + string.digits
    return "MUR-" + "".join(secrets.choice(alphabet) for _ in range(10))


@app.route("/")
def home():
    return render_template("home.html", page_title="Home")

@app.route("/health")
def health():
    return {"status": "ok"}, 200


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        national_id = request.form.get("national_id", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not full_name or not national_id or not email or not password:
            flash("Please complete all required fields.", "danger")
        elif len(full_name) > 120 or len(national_id) > 20 or len(email) > 150:
            flash("One or more fields exceed the allowed length.", "danger")
        elif not national_id.isdigit():
            flash("Enter a valid National ID using digits only.", "danger")
        elif len(password) < 8:
            flash("Your password must be at least 8 characters.", "danger")
        elif password != confirm_password:
            flash("The passwords do not match.", "danger")
        elif User.query.filter_by(national_id=national_id).first():
            flash("An account with that National ID already exists.", "warning")
        elif User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "warning")
        else:
            user = User(
                full_name=full_name,
                national_id=national_id,
                email=email,
                role="citizen",
            )
            user.set_password(password)
            db.session.add(user)

            try:
                db.session.commit()
                flash("Account created. Log in using your National ID.", "success")
                return redirect(url_for("login"))
            except IntegrityError:
                db.session.rollback()
                flash(
                    "That National ID or email may already be registered.",
                    "warning",
                )

    return render_template("register.html", page_title="Register")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        national_id = request.form.get("national_id", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(national_id=national_id).first()

        if user and user.check_password(password):
            login_user(user)
            flash("Welcome back!", "success")
            next_page = request.args.get("next")

            if (
                next_page
                and next_page.startswith("/")
                and not next_page.startswith("//")
            ):
                return redirect(next_page)

            return redirect(url_for("dashboard"))

        flash("Invalid National ID or password.", "danger")

    return render_template("login.html", page_title="Login")

@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have logged out.", "info")
    return redirect(url_for("home"))


@app.route("/dashboard")
@login_required
def dashboard():
    requests_list = (
        ServiceRequest.query
        .filter_by(user_id=current_user.id)
        .order_by(ServiceRequest.created_at.desc())
        .all()
    )
    return render_template(
        "dashboard.html",
        page_title="My Dashboard",
        service_requests=requests_list,
    )


@app.route("/requests/new", methods=["GET", "POST"])
@login_required
def new_request():
    categories = [
        "Roads and Transport",
        "Water and Sanitation",
        "Health Services",
        "Business and Licensing",
        "Land and Housing",
        "Environment and Waste",
        "Other",
    ]

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()

        if not title or not description or category not in categories:
            flash("Please complete all fields and choose a valid category.", "danger")
        elif len(title) > 150:
            flash("The request title must be 150 characters or fewer.", "danger")
        else:
            service_request = ServiceRequest(
                tracking_code=generate_tracking_code(),
                title=title,
                category=category,
                description=description,
                status="Submitted",
                user_id=current_user.id,
            )
            db.session.add(service_request)
            db.session.commit()
            flash(
                f"Request submitted. Your tracking code is "
                f"{service_request.tracking_code}.",
                "success",
            )
            return redirect(url_for("dashboard"))

    return render_template(
        "requests/new.html",
        page_title="New Service Request",
        categories=categories,
    )


@app.route("/requests/<int:request_id>")
@login_required
def view_request(request_id):
    service_request = db.get_or_404(ServiceRequest, request_id)

    if (
        service_request.user_id != current_user.id
        and current_user.role != "admin"
    ):
        abort(403)

    return render_template(
        "requests/detail.html",
        page_title="Request Details",
        service_request=service_request,
    )


@app.route("/admin")
@login_required
def admin_dashboard():
    if current_user.role != "admin":
        abort(403)

    requests_list = ServiceRequest.query.order_by(
        ServiceRequest.created_at.desc()
    ).all()

    return render_template(
        "admin/dashboard.html",
        page_title="Administration",
        service_requests=requests_list,
    )


@app.route("/admin/requests/<int:request_id>/update", methods=["POST"])
@login_required
def update_request(request_id):
    if current_user.role != "admin":
        abort(403)

    service_request = db.get_or_404(ServiceRequest, request_id)
    allowed_statuses = {
        "Submitted",
        "Under Review",
        "In Progress",
        "Resolved",
        "Rejected",
    }

    status = request.form.get("status", "")
    staff_notes = request.form.get("staff_notes", "").strip()

    if status not in allowed_statuses:
        flash("Please choose a valid status.", "danger")
    else:
        service_request.status = status
        service_request.staff_notes = staff_notes or None
        db.session.commit()
        flash("Request updated successfully.", "success")

    return redirect(url_for("admin_dashboard"))


# Create the initial database tables if they do not exist.
# For production schema changes, use Flask-Migrate.
with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG") == "1")
