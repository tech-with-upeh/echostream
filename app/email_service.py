from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType
from app.config import settings

use_credentials = bool(settings.MAIL_USERNAME and settings.MAIL_USERNAME.strip())

conf = ConnectionConfig(
    MAIL_USERNAME=settings.MAIL_USERNAME,
    MAIL_PASSWORD=settings.MAIL_PASSWORD,
    MAIL_FROM=settings.MAIL_FROM,
    MAIL_PORT=settings.MAIL_PORT,
    MAIL_SERVER=settings.MAIL_SERVER,
    MAIL_STARTTLS=settings.MAIL_STARTTLS,
    MAIL_SSL_TLS=settings.MAIL_SSL_TLS,
    USE_CREDENTIALS=use_credentials,  # <-- Dynamic toggle fix here
    VALIDATE_CERTS=False if settings.MAIL_SERVER == "localhost" else True
)

async def send_combined_verification_email(email: str, token: str, code: str):
    verification_url = f"{settings.FRONTEND_URL}/verify-email?token={token}"
    
    html_content = f"""
    <h3>Welcome Aboard!</h3>
    <p>Please verify your email address to unlock your account features.</p>
    
    <p><strong>Option 1:</strong> Click the button below to verify instantly:</p>
    <a href="{verification_url}" style="background-color:#4CAF50;color:white;padding:10px 20px;text-decoration:none;border-radius:5px;display:inline-block;">Verify Email</a>
    
    <p><strong>Option 2:</strong> Enter this 6-digit verification code in your app screen:</p>
    <div style="background-color:#f1f1f1; padding:15px; text-align:center; font-size:24px; font-weight:bold; letter-spacing:5px; border-radius:5px; color:#333; max-width:200px; margin:10px 0;">
        {code}
    </div>
    
    <p>Both the link and verification code will expire in 2 hours.</p>
    """
    
    message = MessageSchema(
        subject="Verify Your Email Address",
        recipients=[email],
        body=html_content,
        subtype=MessageType.html
    )
    
    fm = FastMail(conf)
    await fm.send_message(message)



async def send_combined_reset_pass_email(email: str, token: str, code: str):
    verification_url = f"{settings.FRONTEND_URL}/verify-email?token={token}"
    
    html_content = f"""
    <h3>Sorry You Lost Your Pass!</h3>
    <p>Please verify your email address to unlock your account features.</p>
    
    <p><strong>Option 1:</strong> Click the button below to verify instantly:</p>
    <a href="{verification_url}" style="background-color:#4CAF50;color:white;padding:10px 20px;text-decoration:none;border-radius:5px;display:inline-block;">Verify Email</a>
    
    <p><strong>Option 2:</strong> Enter this 6-digit verification code in your app screen:</p>
    <div style="background-color:#f1f1f1; padding:15px; text-align:center; font-size:24px; font-weight:bold; letter-spacing:5px; border-radius:5px; color:#333; max-width:200px; margin:10px 0;">
        {code}
    </div>
    
    <p>Both the link and verification code will expire in 30 minutes.</p>
    """
    
    message = MessageSchema(
        subject="Reset EchoStream Account",
        recipients=[email],
        body=html_content,
        subtype=MessageType.html
    )
    
    fm = FastMail(conf)
    await fm.send_message(message)
