
from datetime import datetime, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


def utc_now():
    return datetime.now(timezone.utc)


class Department(db.Model):
    __tablename__ = "departments"

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(
        db.String(120),
        unique=True,
        nullable=False,
        index=True,
    )

    description = db.Column(db.Text, nullable=True)

    is_active = db.Column(
        db.Boolean,
        nullable=False,
        default=True,
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    administrators = db.relationship(
        "User",
        back_populates="department",
        foreign_keys="User.department_id",
        lazy=True,
    )

    service_requests = db.relationship(
        "ServiceRequest",
        back_populates="department",
        foreign_keys="ServiceRequest.department_id",
        lazy=True,
    )

    def __repr__(self):
        return f"<Department {self.name}>"


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)

    full_name = db.Column(
        db.String(120),
        nullable=False,
    )

    national_id = db.Column(
        db.String(20),
        unique=True,
        nullable=True,
        index=True,
    )

    email = db.Column(
        db.String(150),
        unique=True,
        nullable=False,
        index=True,
    )

    password_hash = db.Column(
        db.String(256),
        nullable=False,
    )

    role = db.Column(
        db.String(30),
        nullable=False,
        default="citizen",
        index=True,
    )

    department_id = db.Column(
        db.Integer,
        db.ForeignKey("departments.id"),
        nullable=True,
        index=True,
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    department = db.relationship(
        "Department",
        back_populates="administrators",
        foreign_keys=[department_id],
    )

    service_requests = db.relationship(
        "ServiceRequest",
        back_populates="user",
        lazy=True,
    )

    # Audit entries created by this user.
    audit_logs = db.relationship(
        "AuditLog",
        back_populates="actor",
        foreign_keys="AuditLog.actor_id",
        lazy=True,
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_overall_admin(self):
        return self.role in ("overall_admin", "admin")

    @property
    def is_department_admin(self):
        return self.role == "department_admin"

    def __repr__(self):
        return f"<User {self.email} ({self.role})>"


class ServiceRequest(db.Model):
    __tablename__ = "service_requests"

    id = db.Column(
        db.Integer,
        primary_key=True,
    )

    tracking_code = db.Column(
        db.String(30),
        unique=True,
        nullable=False,
        index=True,
    )

    title = db.Column(
        db.String(150),
        nullable=False,
    )

    category = db.Column(
        db.String(80),
        nullable=False,
        index=True,
    )

    location = db.Column(
        db.String(250),
        nullable=False,
    )

    description = db.Column(
        db.Text,
        nullable=False,
    )

    image_url = db.Column(
        db.String(1000),
        nullable=True,
    )

    status = db.Column(
        db.String(30),
        nullable=False,
        default="Submitted",
        index=True,
    )

    staff_notes = db.Column(
        db.Text,
        nullable=True,
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        index=True,
    )

    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    department_id = db.Column(
        db.Integer,
        db.ForeignKey("departments.id"),
        nullable=True,
        index=True,
    )

    user = db.relationship(
        "User",
        back_populates="service_requests",
    )

    department = db.relationship(
        "Department",
        back_populates="service_requests",
        foreign_keys=[department_id],
    )

    # History entries associated with this request.
    audit_logs = db.relationship(
        "AuditLog",
        back_populates="service_request",
        foreign_keys="AuditLog.request_id",
        lazy=True,
        order_by="AuditLog.created_at.desc()",
    )

    def __repr__(self):
        return f"<ServiceRequest {self.tracking_code}>"


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(
        db.Integer,
        primary_key=True,
    )

    # User who performed the action.
    # Nullable so history can survive account deletion.
    actor_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Request affected by the action.
    # Nullable so an audit entry can remain if a request is deleted.
    request_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "service_requests.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    # Preserve the tracking code even if the request is deleted.
    tracking_code = db.Column(
        db.String(30),
        nullable=True,
        index=True,
    )

    # Examples: status_changed, department_transferred,
    # staff_notes_updated, department_admin_created.
    action = db.Column(
        db.String(80),
        nullable=False,
        index=True,
    )

    # Human-readable explanation of the event.
    details = db.Column(
        db.Text,
        nullable=False,
    )

    # Previous and new values for changes, when applicable.
    old_value = db.Column(
        db.Text,
        nullable=True,
    )

    new_value = db.Column(
        db.Text,
        nullable=True,
    )

    # Record the actor's role and department at event time.
    # These are snapshots, not live user relationships.
    actor_role = db.Column(
        db.String(30),
        nullable=True,
    )

    department_id = db.Column(
        db.Integer,
        db.ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        index=True,
    )

    actor = db.relationship(
        "User",
        back_populates="audit_logs",
        foreign_keys=[actor_id],
    )

    service_request = db.relationship(
        "ServiceRequest",
        back_populates="audit_logs",
        foreign_keys=[request_id],
    )

    department = db.relationship(
        "Department",
        foreign_keys=[department_id],
    )

    def __repr__(self):
        return f"<AuditLog {self.action} at {self.created_at}>"
