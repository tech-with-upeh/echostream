from pathlib import Path

from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType
from app.config import settings


use_credentials = bool(
    settings.MAIL_USERNAME and settings.MAIL_USERNAME.strip()
)

conf = ConnectionConfig(
    MAIL_USERNAME=settings.MAIL_USERNAME,
    MAIL_PASSWORD=settings.MAIL_PASSWORD,
    MAIL_FROM=settings.MAIL_FROM,
    MAIL_PORT=settings.MAIL_PORT,
    MAIL_SERVER=settings.MAIL_SERVER,
    MAIL_STARTTLS=settings.MAIL_STARTTLS,
    MAIL_SSL_TLS=settings.MAIL_SSL_TLS,
    USE_CREDENTIALS=use_credentials,
    VALIDATE_CERTS=False if settings.MAIL_SERVER == "localhost" else True,
)


TEMPLATE_DIR = Path(__file__).resolve().parent / "email-template"


def load_email_template(template_name: str, **values: str) -> str:
    template_path = TEMPLATE_DIR / template_name

    html = template_path.read_text(encoding="utf-8")

    for key, value in values.items():
        html = html.replace(f"{{{{{key}}}}}", value)

    return html


async def send_combined_verification_email(
    email: str,
    token: str,
    code: str,
):
    verification_url = (
        f"{settings.FRONTEND_URL}/verify-email?token={token}"
    )

    html_content = load_email_template(
        "verify-email.html",
        verification_url=verification_url,
        code=code,
    )

    await FastMail(conf).send_message(
        MessageSchema(
            subject="Verify Your Email Address",
            recipients=[email],
            body=html_content,
            subtype=MessageType.html,
        )
    )


async def send_combined_reset_pass_email(
    email: str,
    token: str,
    code: str,
):
    reset_url = (
        f"{settings.FRONTEND_URL}/reset-password?token={token}"
    )

    html_content = load_email_template(
        "reset-password.html",
        reset_url=reset_url,
        code=code,
    )

    await FastMail(conf).send_message(
        MessageSchema(
            subject="Reset Your Echostream Password",
            recipients=[email],
            body=html_content,
            subtype=MessageType.html,
        )
    )