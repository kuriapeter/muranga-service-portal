
import os
import secrets
import string
from datetime import date, timedelta
from functools import wraps

import cloudinary
import cloudinary.uploader

from flask import (
    Flask, render_template, redirect, url_for,
    request, flash, abort
)
from flask_login import (
    LoginManager, current_user, login_user,
    logout_user, login_required
)
from flask_mail import Mail, Message
from flask_wtf.csrf import CSRFProtect
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from config import Config
from models import (
    db,
    User,
    ServiceRequest,
    Department,
    AuditLog,
)


app = Flask(__name__)
app.config.from_object(Config)

app.config["MAIL_SERVER"] = os.getenv("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"] = int(os.getenv("MAIL_PORT", "587"))
app.config["MAIL_USE_TLS"] = (
    os.getenv("MAIL_USE_TLS", "True").lower() == "true"
)
app.config["MAIL_USE_SSL"] = False
app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD")
app.config["MAIL_DEFAULT_SENDER"] = (
    os.getenv("MAIL_DEFAULT_SENDER") or os.getenv("MAIL_USERNAME")
)

mail = Mail(app)

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True,
)

MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
app.config["MAX_CONTENT_LENGTH"] = MAX_IMAGE_BYTES + (256 * 1024)

# Use SQLite locally if no database URL is configured.
if not app.config.get("SQLALCHEMY_DATABASE_URI"):
    if not os.getenv("VERCEL"):
        os.makedirs(app.instance_path, exist_ok=True)
        app.config["SQLALCHEMY_DATABASE_URI"] = (
            "sqlite:///" + os.path.join(app.instance_path, "portal.db")
        )

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

if os.getenv("VERCEL") and not os.getenv("SECRET_KEY"):
    raise RuntimeError(
        "Set SECRET_KEY in Vercel environment variables."
    )

db.init_app(app)
csrf = CSRFProtect(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to access that page."


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# --------------------------------------------------
# ROLE AND PERMISSION HELPERS
# --------------------------------------------------

def is_overall_admin(user):
    """
    Temporarily accept the old 'admin' role as an overall admin
    so an existing administrator is not locked out during migration.

    New overall administrator accounts should use 'overall_admin'.
    """
    return user.is_authenticated and user.role in {
        "overall_admin",
        "admin",
    }


def is_department_admin(user):
    return (
        user.is_authenticated
        and user.role == "department_admin"
        and user.department_id is not None
    )


def admin_required(view):
    """Allow an overall admin or a properly assigned department admin."""
    @wraps(view)
    @login_required
    def wrapped_view(*args, **kwargs):
        if not (
            is_overall_admin(current_user)
            or is_department_admin(current_user)
        ):
            abort(403)

        return view(*args, **kwargs)

    return wrapped_view


def overall_admin_required(view):
    """Allow only the overall administrator."""
    @wraps(view)
    @login_required
    def wrapped_view(*args, **kwargs):
        if not is_overall_admin(current_user):
            abort(403)

        return view(*args, **kwargs)

    return wrapped_view


def request_is_accessible(service_request):
    """Enforce request access for citizens and administrators."""
    if is_overall_admin(current_user):
        return True

    if is_department_admin(current_user):
        return (
            service_request.department_id is not None
            and service_request.department_id
            == current_user.department_id
        )

    return service_request.user_id == current_user.id


def get_department_for_category(category):
    """Map citizen request categories to the departments we created."""
    category_to_department = {
        "Roads and Transport": "Roads and Transport",
        "Water and Sanitation": "Water and Sanitation",
        "Health Services": "Health Services",
        "Business and Licensing": "Trade and Licensing",
        "Land and Housing": "Lands and Housing",
        "Environment and Waste": "Environment and Waste Management",
        "Other": "Other / Admin Review",
    }

    department_name = category_to_department.get(
        category, "Other / Admin Review"
    )

    department = Department.query.filter_by(
        name=department_name,
        is_active=True,
    ).first()

    if department is None:
        department = Department.query.filter_by(
            name="Other / Admin Review",
            is_active=True,
        ).first()

    return department


def generate_tracking_code():
    alphabet = string.ascii_uppercase + string.digits
    return "MUR-" + "".join(
        secrets.choice(alphabet) for _ in range(10)
    )


def record_audit(
    actor,
    action,
    details,
    service_request=None,
    old_value=None,
    new_value=None,
    department_id=None,
):
    """Add an audit entry to the current database transaction."""
    entry = AuditLog(
        actor_id=actor.id,
        request_id=(
            service_request.id if service_request else None
        ),
        tracking_code=(
            service_request.tracking_code
            if service_request else None
        ),
        action=action,
        details=details,
        old_value=old_value,
        new_value=new_value,
        actor_role=actor.role,
        department_id=(
            department_id
            if department_id is not None
            else (
                service_request.department_id
                if service_request else actor.department_id
            )
        ),
    )
    db.session.add(entry)
    return entry

# --------------------------------------------------
# PUBLIC ROUTES
# --------------------------------------------------

@app.route("/")
def home():
    return render_template("home.html", page_title="Home")


@app.route("/health")
def health():
    return {"status": "ok"}, 200


@app.route("/track", methods=["GET", "POST"])
def track_request():
    service_request = None
    tracking_code = ""

    if request.method == "POST":
        tracking_code = (
            request.form.get("tracking_code", "").strip().upper()
        )

        if not tracking_code:
            flash("Please enter your tracking code.", "warning")
        else:
            service_request = ServiceRequest.query.filter_by(
                tracking_code=tracking_code
            ).first()

            if service_request is None:
                flash(
                    "No request was found with that tracking code. "
                    "Please check the code and try again.",
                    "warning",
                )

    return render_template(
        "track.html",
        page_title="Track a Service Request",
        service_request=service_request,
        tracking_code=tracking_code,
    )


# --------------------------------------------------
# REGISTRATION AND LOGIN
# --------------------------------------------------

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
        elif (
            len(full_name) > 120
            or len(national_id) > 20
            or len(email) > 150
        ):
            flash(
                "One or more fields exceed the allowed length.",
                "danger",
            )
        elif not national_id.isdigit():
            flash(
                "Enter a valid National ID using digits only.",
                "danger",
            )
        elif len(password) < 8:
            flash(
                "Your password must be at least 8 characters.",
                "danger",
            )
        elif password != confirm_password:
            flash("The passwords do not match.", "danger")
        elif User.query.filter_by(
            national_id=national_id
        ).first():
            flash(
                "An account with that National ID already exists.",
                "warning",
            )
        elif User.query.filter_by(email=email).first():
            flash(
                "An account with that email already exists.",
                "warning",
            )
        else:
            # Public registration can only create citizen accounts.
            user = User(
                full_name=full_name,
                national_id=national_id,
                email=email,
                role="citizen",
                department_id=None,
            )
            user.set_password(password)
            db.session.add(user)

            try:
                db.session.commit()
                flash(
                    "Account created. Log in using your National ID.",
                    "success",
                )
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

        user = User.query.filter_by(
            national_id=national_id
        ).first()

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


# --------------------------------------------------
# DASHBOARDS
# --------------------------------------------------

@app.route("/dashboard")
@login_required
def dashboard():
    if is_overall_admin(current_user):
        return redirect(url_for("admin_dashboard"))

    if current_user.role == "department_admin":
        if not is_department_admin(current_user):
            abort(403)
        return redirect(url_for("admin_dashboard"))

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


@app.route("/admin")
@admin_required
def admin_dashboard():
    # Department admins can query only their own department.
    if is_department_admin(current_user):
        requests_query = ServiceRequest.query.filter_by(
            department_id=current_user.department_id
        )
    else:
        requests_query = ServiceRequest.query

    requests_list = requests_query.order_by(
        ServiceRequest.created_at.desc()
    ).all()

    statuses = [
        "Submitted",
        "Under Review",
        "In Progress",
        "Resolved",
        "Rejected",
    ]

    status_counts = {
        status: sum(
            1 for item in requests_list if item.status == status
        )
        for status in statuses
    }

    today = date.today()
    dates = [
        today - timedelta(days=offset)
        for offset in range(6, -1, -1)
    ]

    daily_counts = {day.isoformat(): 0 for day in dates}

    for item in requests_list:
        if item.created_at:
            request_day = item.created_at.date().isoformat()
            if request_day in daily_counts:
                daily_counts[request_day] += 1

    return render_template(
        "admin/dashboard.html",
        page_title=(
            "Administration"
            if is_overall_admin(current_user)
            else f"{current_user.department.name} Dashboard"
        ),
        service_requests=requests_list,
        status_labels=statuses,
        status_counts=[status_counts[s] for s in statuses],
        total_requests=len(requests_list),
        pending_requests=(
            status_counts["Submitted"]
            + status_counts["Under Review"]
        ),
        in_progress_requests=status_counts["In Progress"],
        resolved_requests=status_counts["Resolved"],
        rejected_requests=status_counts["Rejected"],
        daily_labels=[day.strftime("%d %b") for day in dates],
        daily_counts=[
            daily_counts[day.isoformat()] for day in dates
        ],
                is_overall_admin=is_overall_admin(current_user),
        current_department=(
            current_user.department
            if is_department_admin(current_user)
            else None
        ),
        departments=Department.query.order_by(
            Department.name.asc()
        ).all(),
    )


# --------------------------------------------------
# AUDIT LOG VIEWER
# --------------------------------------------------

@app.route("/admin/audit-logs")
@admin_required
def audit_logs():
    # Overall admin can see all audit records.
    # Department admins can see only records associated
    # with their own department.
    logs_query = AuditLog.query

    if is_department_admin(current_user):
        logs_query = logs_query.filter(
            AuditLog.department_id == current_user.department_id
        )

    # Optional search by tracking code or action.
    search = request.args.get("search", "").strip()

    if search:
        search_term = f"%{search}%"
        logs_query = logs_query.filter(
            db.or_(
                AuditLog.tracking_code.ilike(search_term),
                AuditLog.action.ilike(search_term),
                AuditLog.details.ilike(search_term),
            )
        )

    # Pagination prevents loading every record at once.
    pagination = logs_query.order_by(
        AuditLog.created_at.desc()
    ).paginate(
        page=request.args.get("page", 1, type=int),
        per_page=25,
        error_out=False,
    )

    return render_template(
        "admin/audit_logs.html",
        page_title="Audit Logs",
        logs=pagination.items,
        pagination=pagination,
        search=search,
        is_overall_admin=is_overall_admin(current_user),
    )

# --------------------------------------------------
# CITIZEN SERVICE REQUESTS
# --------------------------------------------------

@app.route("/requests/new", methods=["GET", "POST"])
@login_required
def new_request():
    if current_user.role != "citizen":
        abort(403)

    categories = [
        "Roads and Transport",
        "Water and Sanitation",
        "Health Services",
        "Business and Licensing",
        "Land and Housing",
        "Environment and Waste",
        "Other",
    ]

    selected_category = request.args.get("category", "").strip()
    if selected_category not in categories:
        selected_category = ""

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "").strip()
        location = request.form.get("location", "").strip()
        description = request.form.get("description", "").strip()
        image = request.files.get("image")

        selected_category = category

        if (
            not title
            or not location
            or not description
            or category not in categories
        ):
            flash(
                "Please complete all required fields and choose "
                "a valid category.",
                "danger",
            )
        elif len(title) > 150:
            flash(
                "The request title must be 150 characters or fewer.",
                "danger",
            )
        elif len(location) > 250:
            flash(
                "The location must be 250 characters or fewer.",
                "danger",
            )
        else:
            department = get_department_for_category(category)

            if department is None:
                flash(
                    "Departments are not configured correctly. "
                    "Please contact the system administrator.",
                    "danger",
                )
            else:
                image_url = None
                upload_failed = False

                if image and image.filename:
                    filename = secure_filename(image.filename)
                    extension = (
                        filename.rsplit(".", 1)[-1].lower()
                        if "." in filename else ""
                    )

                    if extension not in ALLOWED_IMAGE_EXTENSIONS:
                        flash(
                            "Upload an image in JPG, JPEG, PNG, or WEBP format.",
                            "danger",
                        )
                        upload_failed = True
                    else:
                        try:
                            if not all([
                                os.getenv("CLOUDINARY_CLOUD_NAME"),
                                os.getenv("CLOUDINARY_API_KEY"),
                                os.getenv("CLOUDINARY_API_SECRET"),
                            ]):
                                raise RuntimeError(
                                    "Cloud image storage is not configured."
                                )

                            image.stream.seek(0, os.SEEK_END)
                            image_size = image.stream.tell()
                            image.stream.seek(0)

                            if image_size > MAX_IMAGE_BYTES:
                                flash(
                                    "The image must be 5 MB or smaller.",
                                    "danger",
                                )
                                upload_failed = True
                            else:
                                uploaded = cloudinary.uploader.upload(
                                    image.stream,
                                    folder="muranga-service-portal",
                                    resource_type="image",
                                    allowed_formats=list(
                                        ALLOWED_IMAGE_EXTENSIONS
                                    ),
                                )
                                image_url = uploaded.get("secure_url")

                        except Exception:
                            app.logger.exception(
                                "Could not upload request evidence"
                            )
                            flash(
                                "The image could not be uploaded. "
                                "Please try again or submit without an image.",
                                "danger",
                            )
                            upload_failed = True

                if not upload_failed:
                    service_request = ServiceRequest(
                        tracking_code=generate_tracking_code(),
                        title=title,
                        category=category,
                        location=location,
                        description=description,
                        image_url=image_url,
                        status="Submitted",
                        user_id=current_user.id,
                        department_id=department.id,
                    )

                    
                    db.session.add(service_request)

                    try:
                        # Save the request first so it receives its database ID.
                        db.session.flush()

                        # Record the citizen's submission in the audit log.
                        record_audit(
                            actor=current_user,
                            action="request_submitted",
                            details=(
                                f"Citizen submitted a service request: "
                                f"{service_request.title}"
                            ),
                            service_request=service_request,
                            new_value=service_request.status,
                            department_id=service_request.department_id,
                        )

                        # Save the request and audit entry together.
                        db.session.commit()

                    except IntegrityError:
                        db.session.rollback()
                        flash(
                            "The request could not be saved. Please try again.",
                            "danger",
                        )
                    else:
                        # Email is best-effort: a mail failure must not undo
                        # the already-saved service request.
                        recipient = (current_user.email or "").strip()

                        if recipient:
                            try:
                                sender = (
                                    app.config.get("MAIL_DEFAULT_SENDER")
                                    or app.config.get("MAIL_USERNAME")
                                )

                                message = Message(
                                    subject=(
                                        "Request Received: "
                                        f"{service_request.tracking_code}"
                                    ),
                                    recipients=[recipient],
                                    sender=sender,
                                    body=(
                                        f"Hello {current_user.full_name},\n\n"
                                        "Your service request has been "
                                        "successfully submitted to the "
                                        "Murang'a County Public Service "
                                        "Request System.\n\n"
                                        f"Request title: {service_request.title}\n"
                                        f"Category: {service_request.category}\n"
                                        f"Location: {service_request.location}\n"
                                        f"Tracking code: "
                                        f"{service_request.tracking_code}\n"
                                        f"Current status: {service_request.status}\n\n"
                                        "Please keep your tracking code to "
                                        "check the progress of your request.\n\n"
                                        "Thank you,\n"
                                        "Murang'a County Public Service "
                                        "Request System"
                                    ),
                                )

                                mail.send(message)
                                flash(
                                    "Request submitted successfully. Your "
                                    "confirmation email has been sent.",
                                    "success",
                                )
                            except Exception:
                                app.logger.exception(
                                    "Failed to send submission email for request %s",
                                    service_request.id,
                                )
                                flash(
                                    "Your request was submitted, but the "
                                    "confirmation email could not be sent.",
                                    "warning",
                                )
                        else:
                            flash(
                                "Your request was submitted, but your account "
                                "has no email address.",
                                "warning",
                            )

                        flash(
                            "Your tracking code is "
                            f"{service_request.tracking_code}.",
                            "info",
                        )
                        return redirect(url_for("dashboard"))

    return render_template(
        "requests/new.html",
        page_title="New Service Request",
        categories=categories,
        selected_category=selected_category,
    )


@app.route("/requests/<int:request_id>")
@login_required
def view_request(request_id):
    service_request = db.get_or_404(ServiceRequest, request_id)

    if not request_is_accessible(service_request):
        abort(403)

    return render_template(
        "requests/detail.html",
        page_title="Request Details",
        service_request=service_request,
    )


# --------------------------------------------------
# OVERALL ADMIN: CREATE DEPARTMENT ADMIN ACCOUNTS
# --------------------------------------------------

@app.route("/admin/department-admins/new", methods=["GET", "POST"])
@overall_admin_required
def create_department_admin():
    departments = Department.query.filter_by(
        is_active=True
    ).order_by(Department.name.asc()).all()

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        national_id = request.form.get("national_id", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        department_id = request.form.get("department_id", "").strip()

        if not all([
            full_name, national_id, email, password, department_id
        ]):
            flash("Please complete all required fields.", "danger")

        elif len(full_name) > 120 or len(national_id) > 20 or len(email) > 150:
            flash("One or more fields exceed the allowed length.", "danger")

        elif not national_id.isdigit():
            flash("National ID must contain digits only.", "danger")

        elif len(password) < 8:
            flash("The password must be at least 8 characters.", "danger")

        elif User.query.filter_by(national_id=national_id).first():
            flash("That National ID is already registered.", "warning")

        elif User.query.filter_by(email=email).first():
            flash("That email address is already registered.", "warning")

        else:
            try:
                selected_department_id = int(department_id)
            except ValueError:
                selected_department_id = None

            department = (
                db.session.get(Department, selected_department_id)
                if selected_department_id is not None
                else None
            )

            if department is None or not department.is_active:
                flash("Select a valid active department.", "danger")
            else:
                admin_user = User(
                    full_name=full_name,
                    national_id=national_id,
                    email=email,
                    role="department_admin",
                    department_id=department.id,
                )
                
                admin_user.set_password(password)
                db.session.add(admin_user)

                try:
                    # Save the new account within the current transaction.
                    # flush() assigns the user ID without committing.
                    db.session.flush()

                    # Record the department-admin account creation.
                    record_audit(
                        actor=current_user,
                        action="department_admin_created",
                        details=(
                            f"Created department administrator "
                            f"for {department.name}."
                        ),
                        new_value=(
                            f"User ID: {admin_user.id}; "
                            f"Role: department_admin"
                        ),
                        department_id=department.id,
                    )

                    # Commit the account and audit entry together.
                    db.session.commit()

                    flash(
                        f"Department administrator created for "
                        f"{department.name}.",
                        "success",
                    )
                    return redirect(
                        url_for("create_department_admin")
                    )

                except IntegrityError:
                    db.session.rollback()
                    flash(
                        "The account could not be created. "
                        "Check whether its National ID or email is already used.",
                        "warning",
                    )


    return render_template(
        "admin/create_department_admin.html",
        page_title="Create Department Admin",
        departments=departments,
    )


# --------------------------------------------------
# OVERALL ADMIN: ASSIGN OR TRANSFER REQUESTS
# --------------------------------------------------


@app.route(
    "/admin/requests/<int:request_id>/assign",
    methods=["POST"],
)
@overall_admin_required
def assign_request_department(request_id):
    service_request = db.get_or_404(ServiceRequest, request_id)

    department_id = request.form.get("department_id", "").strip()

    try:
        department_id = int(department_id)
    except ValueError:
        flash("Please select a valid department.", "danger")
        return redirect(url_for("admin_dashboard"))

    department = db.session.get(Department, department_id)

    if department is None or not department.is_active:
        flash("The selected department is not available.", "danger")
        return redirect(url_for("admin_dashboard"))

    old_department = service_request.department
    old_department_id = service_request.department_id

    if old_department_id == department.id:
        flash(
            "This request is already assigned to that department.",
            "info",
        )
        return redirect(url_for("admin_dashboard"))

    old_name = (
        old_department.name if old_department else "Unassigned"
    )

    service_request.department_id = department.id

    record_audit(
        actor=current_user,
        action="department_transferred",
        details=(
            f"Request {service_request.tracking_code} transferred "
            f"from {old_name} to {department.name}."
        ),
        service_request=service_request,
        old_value=old_name,
        new_value=department.name,
        department_id=department.id,
    )

    try:
        db.session.commit()
        flash(
            f"Request {service_request.tracking_code} assigned to "
            f"{department.name}.",
            "success",
        )
    except Exception:
        db.session.rollback()
        app.logger.exception(
            "Could not assign request %s to department %s",
            service_request.id,
            department.id,
        )
        flash("The request assignment failed.", "danger")

    return redirect(url_for("admin_dashboard"))

# --------------------------------------------------
# ADMIN REQUEST UPDATES
# --------------------------------------------------


@app.route(
    "/admin/requests/<int:request_id>/update",
    methods=["POST"],
)
@admin_required
def update_request(request_id):
    service_request = db.get_or_404(ServiceRequest, request_id)

    # Enforce department-level access before changing anything.
    if not request_is_accessible(service_request):
        abort(403)

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
        return redirect(url_for("admin_dashboard"))

    old_status = service_request.status
    old_notes = service_request.staff_notes or ""
    new_notes = staff_notes

    status_changed = status != old_status
    notes_changed = new_notes != old_notes

    if not status_changed and not notes_changed:
        flash("No changes were made to the request.", "info")
        return redirect(url_for("admin_dashboard"))

    service_request.status = status
    service_request.staff_notes = new_notes or None

    if status_changed:
        record_audit(
            actor=current_user,
            action="status_changed",
            details=(
                f"Status changed for request "
                f"{service_request.tracking_code}."
            ),
            service_request=service_request,
            old_value=old_status,
            new_value=status,
        )

    if notes_changed:
        record_audit(
            actor=current_user,
            action="staff_notes_updated",
            details=(
                f"Staff notes updated for request "
                f"{service_request.tracking_code}."
            ),
            service_request=service_request,
            old_value=old_notes or None,
            new_value=new_notes or None,
        )

    try:
        # Save the request and its audit entries atomically.
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception(
            "Could not update request %s", service_request.id
        )
        flash("The request could not be updated.", "danger")
        return redirect(url_for("admin_dashboard"))

    # Keep the existing citizen status email behaviour.
    if status_changed:
        try:
            recipient = service_request.user.email

            if recipient:
                sender = (
                    app.config.get("MAIL_DEFAULT_SENDER")
                    or app.config.get("MAIL_USERNAME")
                )

                message = Message(
                    subject=f"Service Request Update: {status}",
                    recipients=[recipient],
                    sender=sender,
                    body=(
                        "Hello,\n\n"
                        "There is an update to your Murang'a County "
                        "Public Service Request.\n\n"
                        f"Request: {service_request.title}\n"
                        f"Tracking code: {service_request.tracking_code}\n"
                        f"Previous status: {old_status}\n"
                        f"New status: {status}\n\n"
                        "Please use your tracking code on the portal "
                        "to check your request.\n\n"
                        "Murang'a County Public Service Request System"
                    ),
                )

                mail.send(message)
                flash(
                    "Request updated and notification email sent.",
                    "success",
                )
            else:
                flash(
                    "Request updated, but the citizen has no email address.",
                    "warning",
                )

        except Exception:
            app.logger.exception(
                "Failed to send status notification for request %s",
                service_request.id,
            )
            flash(
                "Request updated, but the notification email could not "
                "be sent. Check the application logs.",
                "warning",
            )
    else:
        flash("Request updated successfully.", "success")

    return redirect(url_for("admin_dashboard"))

# Create missing tables only. This does not migrate existing schemas.
with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG") == "1")
