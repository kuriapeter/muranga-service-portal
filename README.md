# Murang’a County Public Service Request System

A web-based public service request portal inspired by eCitizen-style workflows. Citizens can submit and track service requests, while administrators manage requests according to their roles and departments.

## Live Demo

- **Live application:** https://muranga-service-portal.vercel.app
- **GitHub repository:** https://github.com/kuriapeter/muranga-service-portal

> This is a portfolio/learning project. It is not an official Murang’a County Government service unless formally adopted by the county.

## Features

### Citizen features
- Register and log in using a National ID and password.
- Submit service requests with a title, category, location, description, and optional image evidence.
- Receive a unique tracking code for each request.
- View submitted requests and current statuses from the citizen dashboard.
- Track a request using its tracking code.
- Receive a confirmation email after submitting a request.
- Receive an email notification when an administrator changes a request's status.

### Administration features
- Dashboard summaries and charts for request statuses and recent activity.
- Update request statuses: `Submitted`, `Under Review`, `In Progress`, `Resolved`, and `Rejected`.
- Add or update staff notes on requests.
- Separate overall administrator and department administrator permissions.
- Restrict department administrators to requests assigned to their department.
- Create department administrator accounts (overall administrator only).
- Transfer requests between active departments (overall administrator only).
- Audit logs for key actions, including request submission, status changes, staff-note updates, department transfers, and department administrator creation.
- Search and paginate audit log records.

### Request categories and routing
Requests are routed to a configured active department based on category. Categories include Roads and Transport, Water and Sanitation, Health Services, Business and Licensing, Land and Housing, Environment and Waste, and Other.

### File uploads
Optional request evidence images are uploaded to Cloudinary. Supported formats are JPG, JPEG, PNG, and WEBP, with a maximum image size of 5 MB.

## Technology Stack

- **Backend:** Python, Flask
- **Database/ORM:** SQLAlchemy, Flask-SQLAlchemy
- **Authentication:** Flask-Login
- **Forms/security:** Flask-WTF CSRF protection
- **Frontend:** Jinja templates, HTML, CSS, Bootstrap, and Chart.js
- **Production database:** PostgreSQL hosted on Neon
- **Image storage:** Cloudinary
- **Email:** Flask-Mail with SMTP (Gmail SMTP by default)
- **Deployment:** Vercel
- **Version control:** Git and GitHub

## Application Structure

```text
muranga-service-portal/
├── app.py
├── models.py
├── config.py
├── requirements.txt
├── templates/
│   ├── admin/
│   │   ├── audit_logs.html
│   │   ├── create_department_admin.html
│   │   └── dashboard.html
│   ├── requests/
│   │   ├── detail.html
│   │   └── new.html
│   ├── base.html
│   ├── dashboard.html
│   ├── home.html
│   ├── login.html
│   ├── register.html
│   └── track.html
└── ...
```

## Run Locally

### 1. Requirements
- Python 3.10 or newer recommended.
- Git.
- A PostgreSQL database for a production-like setup. The app can use local SQLite when no database URL is configured and it is not running on Vercel.

### 2. Clone the repository

```bash
git clone https://github.com/kuriapeter/muranga-service-portal.git
cd muranga-service-portal
```

### 3. Create and activate a virtual environment

**Windows PowerShell**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

**Git Bash**
```bash
python -m venv venv
source venv/Scripts/activate
```

### 4. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 5. Configure environment variables

Set these in your local environment or in a local `.env` file if your configuration loads one. Never commit credentials or production secrets to GitHub.

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Flask session and security key. Use a long, random value. |
| `SQLALCHEMY_DATABASE_URI` | Database connection URL used by the application configuration. |
| `DATABASE_URL` | Use only if `config.py` maps this variable to the SQLAlchemy database URI. |
| `CLOUDINARY_CLOUD_NAME` | Cloudinary cloud name for image uploads. |
| `CLOUDINARY_API_KEY` | Cloudinary API key. |
| `CLOUDINARY_API_SECRET` | Cloudinary API secret. |
| `MAIL_SERVER` | SMTP host; defaults to `smtp.gmail.com`. |
| `MAIL_PORT` | SMTP port; defaults to `587`. |
| `MAIL_USE_TLS` | Set to `True` for TLS on port 587. |
| `MAIL_USERNAME` | SMTP account username/email. |
| `MAIL_PASSWORD` | SMTP password or provider app password. |
| `MAIL_DEFAULT_SENDER` | Optional sender address; defaults to `MAIL_USERNAME`. |

The application loads `Config` before configuring the database. Confirm the exact database environment-variable mapping in `config.py`. For Gmail, use an app password where required, not your normal account password.

### 6. Start the application

```bash
python app.py
```

Open the local address shown in the terminal (commonly `http://127.0.0.1:5000`).

The application calls `db.create_all()` on startup to create missing tables. This does **not** migrate existing database schemas; apply required schema changes separately before deploying model changes to an existing database.

## Deployment

The project is deployed on Vercel from the GitHub repository.

1. Push changes to the deployment branch (`main`).
2. Confirm the Vercel deployment finishes successfully.
3. Configure required environment variables in Vercel Project Settings → Environment Variables.
4. Ensure the Neon PostgreSQL database, tables, and departments are configured.
5. Verify the live site and test the main citizen and administrator workflows after deployment.

Never commit `.env`, SMTP passwords, Cloudinary secrets, database credentials, or Flask secret keys.

## Verification Checklist

Use test accounts and non-sensitive sample data:

- [ ] Register a citizen account and log in.
- [ ] Submit a request without an image.
- [ ] Submit a request with a valid image and confirm it displays.
- [ ] Confirm the citizen receives a submission confirmation email.
- [ ] Track a request using its tracking code.
- [ ] Change a request status and confirm the citizen receives a status email.
- [ ] Confirm a department administrator sees only requests assigned to their department.
- [ ] Confirm department administrators cannot access overall-administrator-only actions.
- [ ] Confirm an overall administrator can create a department administrator and transfer a request.
- [ ] Confirm relevant actions appear in the audit log.

## Security Notes

- Keep credentials in environment variables and out of version control.
- Use strong, unique passwords for administrator accounts.
- Audit logs record important application actions but are not tamper-proof against someone with direct database administrator access.
- Use HTTPS in deployment and protect administrator accounts.
- Do not use real citizens' personal information in demonstrations or screenshots.

## Future Improvements

Possible next steps include automated test coverage, stronger email verification and password-reset workflows, more detailed audit-log filtering, and formal accessibility testing.

## Author / Portfolio

Developed as an ICT portfolio project demonstrating full-stack web development, role-based access control, database integration, cloud deployment, file uploads, email notifications, and audit logging.
