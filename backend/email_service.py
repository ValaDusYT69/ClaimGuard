import smtplib
from email.message import EmailMessage

from config import (
    SMTP_HOST,
    SMTP_PORT,
    EMAIL_USER,
    EMAIL_APP_PASSWORD,
)


def send_otp_email(
    recipient_email: str,
    otp_code: str,
    purpose: str = "email_verification",
) -> None:
    """
    Send a ClaimGuard OTP email through Gmail SMTP.

    This function is used for:
    - Email verification
    - Password reset
    """

    if not EMAIL_USER or not EMAIL_APP_PASSWORD:
        print(
            f"[ClaimGuard dev mail] {purpose} OTP for {recipient_email}: {otp_code}"
        )
        return


    # -----------------------------------------------------
    # Email subject
    # -----------------------------------------------------

    if purpose == "password_reset":

        subject = "ClaimGuard - Password Reset Code"

    else:

        subject = "ClaimGuard - Email Verification Code"


    # -----------------------------------------------------
    # Purpose text
    # -----------------------------------------------------

    if purpose == "password_reset":

        heading = "Reset your ClaimGuard password"

        description = (
            "Use the verification code below to reset "
            "your ClaimGuard password."
        )

    else:

        heading = "Verify your ClaimGuard account"

        description = (
            "Use the verification code below to verify "
            "your ClaimGuard email address."
        )


    # -----------------------------------------------------
    # Plain-text email
    # -----------------------------------------------------

    plain_text = f"""
ClaimGuard

{heading}

{description}

Your verification code is:

{otp_code}

This code will expire in 10 minutes.

For your security, never share this code with anyone.

If you did not request this code, you can safely ignore this email.

ClaimGuard
Intelligent Invoice Verification & Anomaly Detection
"""


    # -----------------------------------------------------
    # HTML email
    # -----------------------------------------------------

    html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>ClaimGuard</title>
</head>

<body style="
    margin:0;
    padding:0;
    background:#f5f7fb;
    font-family:Arial,Helvetica,sans-serif;
">

    <div style="
        max-width:600px;
        margin:40px auto;
        background:#ffffff;
        border:1px solid #e5e7eb;
        border-radius:16px;
        overflow:hidden;
    ">

        <div style="
            background:#0f172a;
            padding:28px;
            color:#ffffff;
        ">

            <div style="
                font-size:22px;
                font-weight:700;
            ">
                ClaimGuard
            </div>

            <div style="
                margin-top:4px;
                font-size:12px;
                color:#94a3b8;
            ">
                Invoice Intelligence
            </div>

        </div>


        <div style="
            padding:38px 32px;
        ">

            <h1 style="
                margin:0 0 12px;
                font-size:25px;
                color:#0f172a;
            ">
                {heading}
            </h1>


            <p style="
                margin:0;
                color:#64748b;
                font-size:14px;
                line-height:1.7;
            ">
                {description}
            </p>


            <div style="
                margin:28px 0;
                padding:24px;
                background:#eff6ff;
                border:1px solid #dbeafe;
                border-radius:12px;
                text-align:center;
            ">

                <div style="
                    font-size:11px;
                    color:#64748b;
                    margin-bottom:8px;
                ">
                    VERIFICATION CODE
                </div>


                <div style="
                    font-size:34px;
                    font-weight:700;
                    letter-spacing:8px;
                    color:#2563eb;
                ">
                    {otp_code}
                </div>


                <div style="
                    margin-top:10px;
                    font-size:11px;
                    color:#94a3b8;
                ">
                    Expires in 10 minutes
                </div>

            </div>


            <p style="
                margin:0;
                color:#64748b;
                font-size:12px;
                line-height:1.7;
            ">
                For your security, never share this code with
                anyone. If you did not request this code, you
                can safely ignore this email.
            </p>

        </div>


        <div style="
            padding:20px 32px;
            background:#f8fafc;
            border-top:1px solid #e5e7eb;
            color:#94a3b8;
            font-size:11px;
        ">
            ClaimGuard — Intelligent Invoice Verification
            & Anomaly Detection
        </div>

    </div>

</body>
</html>
"""


    # -----------------------------------------------------
    # Build email
    # -----------------------------------------------------

    message = EmailMessage()

    message["Subject"] = subject
    message["From"] = EMAIL_USER
    message["To"] = recipient_email

    message.set_content(
        plain_text
    )

    message.add_alternative(
        html_content,
        subtype="html"
    )


    # -----------------------------------------------------
    # Send through Gmail SMTP
    # -----------------------------------------------------

    try:

        with smtplib.SMTP_SSL(
            SMTP_HOST,
            SMTP_PORT
        ) as smtp:

            smtp.login(
                EMAIL_USER,
                EMAIL_APP_PASSWORD
            )

            smtp.send_message(
                message
            )


    except smtplib.SMTPAuthenticationError as error:

        raise RuntimeError(
            "Gmail authentication failed. "
            "Check your email address, 2-Step Verification, "
            "and App Password."
        ) from error


    except Exception as error:

        raise RuntimeError(
            f"Unable to send email: {error}"
        ) from error