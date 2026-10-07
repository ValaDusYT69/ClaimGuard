import random
import uuid
import jwt
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from config import SECRET_KEY, ACCESS_TOKEN_EXPIRE_MINUTES

from auth.security import (
    create_access_token,
    hash_password,
    verify_password,
)

from auth.storage import (
    read_otps,
    read_users,
    write_otps,
    write_users,
)

from email_service import send_otp_email


# =========================================================
# ROUTER
# =========================================================

router = APIRouter(
    prefix="/api/auth",
    tags=["Authentication"],
)


# =========================================================
# REQUEST MODELS
# =========================================================

class RegisterRequest(BaseModel):
    full_name: str = Field(
        min_length=2,
        max_length=100
    )

    email: EmailStr

    password: str = Field(
        min_length=8,
        max_length=128
    )


class VerifyEmailRequest(BaseModel):
    email: EmailStr

    otp: str = Field(
        min_length=6,
        max_length=6
    )


class LoginRequest(BaseModel):
    email: EmailStr

    password: str = Field(
        min_length=1,
        max_length=128
    )


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr

    otp: str = Field(
        min_length=6,
        max_length=6
    )

    new_password: str = Field(
        min_length=8,
        max_length=128
    )


# =========================================================
# HELPER FUNCTIONS
# =========================================================

def normalize_email(email: str) -> str:
    return email.lower().strip()


def generate_otp() -> str:
    return str(
        random.randint(100000, 999999)
    )


def otp_expiration():
    return (
        datetime.now(timezone.utc)
        + timedelta(minutes=10)
    )


def get_user_by_email(email: str):
    email = normalize_email(email)

    users = read_users()

    return next(
        (
            user
            for user in users
            if user["email"].lower() == email
        ),
        None
    )


def save_verification_otp(
    email: str,
    purpose: str,
):
    otp_code = generate_otp()

    expires_at = otp_expiration()

    otps = read_otps()

    otps[email] = {
        "otp": otp_code,
        "expires_at": expires_at.isoformat(),
        "purpose": purpose,
    }

    write_otps(otps)

    return otp_code


# =========================================================
# REGISTER
# =========================================================

@router.post("/register")
def register_user(
    request: RegisterRequest
):

    email = normalize_email(
        request.email
    )

    users = read_users()


    # -----------------------------------------------------
    # Check existing user
    # -----------------------------------------------------

    existing_user = next(
        (
            user
            for user in users
            if user["email"].lower() == email
        ),
        None
    )


    # =====================================================
    # EXISTING BUT NOT VERIFIED
    # =====================================================

    if (
        existing_user
        and not existing_user["is_verified"]
    ):

        # Update entered information
        existing_user["full_name"] = (
            request.full_name.strip()
        )

        existing_user["hashed_password"] = (
            hash_password(request.password)
        )

        existing_user["is_active"] = False

        write_users(users)


        # Generate NEW OTP
        otp_code = save_verification_otp(
            email=email,
            purpose="email_verification",
        )


        # Send NEW OTP
        try:

            send_otp_email(
                recipient_email=email,
                otp_code=otp_code,
                purpose="email_verification",
            )

        except Exception as error:

            # Remove OTP because email failed
            otps = read_otps()

            if email in otps:
                del otps[email]

            write_otps(otps)


            raise HTTPException(
                status_code=500,
                detail=(
                    "A new verification email could not "
                    "be sent. "
                    f"Email service error: {error}"
                )
            )


        return {
            "success": True,
            "status": "verification_required",
            "message": (
                "This account already exists but has "
                "not been verified. A new verification "
                "code has been sent."
            ),
            "email": email,
            "user_id": existing_user["id"],
        }


    # =====================================================
    # EXISTING AND VERIFIED
    # =====================================================

    if existing_user:

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "An account with this email "
                "already exists and is verified. "
                "Please sign in."
            )
        )


    # =====================================================
    # CREATE NEW USER
    # =====================================================

    user_id = str(uuid.uuid4())

    user = {
        "id": user_id,
        "full_name": request.full_name.strip(),
        "email": email,
        "hashed_password": hash_password(
            request.password
        ),
        "role": "user",
        "is_verified": False,
        "is_active": False,
        "created_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }


    users.append(user)

    write_users(users)


    # =====================================================
    # CREATE VERIFICATION OTP
    # =====================================================

    otp_code = save_verification_otp(
        email=email,
        purpose="email_verification",
    )


    # =====================================================
    # SEND EMAIL
    # =====================================================

    try:

        send_otp_email(
            recipient_email=email,
            otp_code=otp_code,
            purpose="email_verification",
        )

    except Exception as error:

        # Roll back user creation
        users = [
            item
            for item in users
            if item["id"] != user_id
        ]

        write_users(users)


        # Remove OTP
        otps = read_otps()

        if email in otps:
            del otps[email]

        write_otps(otps)


        raise HTTPException(
            status_code=500,
            detail=(
                "Account could not be created because "
                "the verification email could not be sent. "
                f"Email service error: {error}"
            )
        )


    return {
        "success": True,
        "status": "verification_required",
        "message": (
            "Registration successful. "
            "Please check your email for the "
            "verification code."
        ),
        "email": email,
        "user_id": user_id,
    }


# =========================================================
# RESEND VERIFICATION CODE
# =========================================================

@router.post("/resend-verification")
def resend_verification(
    request: ResendVerificationRequest
):

    email = normalize_email(
        request.email
    )


    user = get_user_by_email(email)


    if not user:

        raise HTTPException(
            status_code=404,
            detail=(
                "No ClaimGuard account was found "
                "with this email address."
            )
        )


    if user["is_verified"]:

        raise HTTPException(
            status_code=400,
            detail=(
                "This email is already verified. "
                "Please sign in."
            )
        )


    # Create new OTP
    otp_code = save_verification_otp(
        email=email,
        purpose="email_verification",
    )


    # Send new OTP
    try:

        send_otp_email(
            recipient_email=email,
            otp_code=otp_code,
            purpose="email_verification",
        )

    except Exception as error:

        otps = read_otps()

        if email in otps:
            del otps[email]

        write_otps(otps)


        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to send a new verification code. "
                f"Email service error: {error}"
            )
        )


    return {
        "success": True,
        "message": (
            "A new verification code has been "
            "sent to your email."
        ),
        "email": email,
    }


# =========================================================
# VERIFY EMAIL
# =========================================================

@router.post("/verify-email")
def verify_email(
    request: VerifyEmailRequest
):

    email = normalize_email(
        request.email
    )

    users = read_users()

    otps = read_otps()


    # Find user
    user = next(
        (
            user
            for user in users
            if user["email"].lower() == email
        ),
        None
    )


    if not user:

        raise HTTPException(
            status_code=404,
            detail="Account not found."
        )


    if user["is_verified"]:

        raise HTTPException(
            status_code=400,
            detail="Email is already verified."
        )


    # Find OTP
    otp_record = otps.get(email)


    if not otp_record:

        raise HTTPException(
            status_code=400,
            detail=(
                "No active verification code found. "
                "Please request a new code."
            )
        )


    # Correct OTP purpose
    if otp_record.get(
        "purpose"
    ) != "email_verification":

        raise HTTPException(
            status_code=400,
            detail="Invalid verification request."
        )


    # Check expiration
    try:

        expires_at = datetime.fromisoformat(
            otp_record["expires_at"]
        )

    except (ValueError, KeyError):

        raise HTTPException(
            status_code=400,
            detail="Invalid verification session."
        )


    if datetime.now(
        timezone.utc
    ) > expires_at:

        del otps[email]

        write_otps(otps)

        raise HTTPException(
            status_code=400,
            detail=(
                "Verification code has expired. "
                "Please request a new code."
            )
        )


    # Check OTP
    if request.otp != otp_record["otp"]:

        raise HTTPException(
            status_code=400,
            detail="Invalid verification code."
        )


    # Activate account
    user["is_verified"] = True
    user["is_active"] = True


    write_users(users)


    # Delete used OTP
    del otps[email]

    write_otps(otps)


    return {
        "success": True,
        "message": (
            "Email verified successfully."
        ),
    }


# =========================================================
# LOGIN
# =========================================================

@router.post("/login")
def login_user(
    request: LoginRequest
):

    email = normalize_email(
        request.email
    )

    users = read_users()


    user = next(
        (
            user
            for user in users
            if user["email"].lower() == email
        ),
        None
    )


    if not user:

        raise HTTPException(
            status_code=401,
            detail="Invalid email or password."
        )


    if not verify_password(
        request.password,
        user["hashed_password"]
    ):

        raise HTTPException(
            status_code=401,
            detail="Invalid email or password."
        )


    if not user["is_verified"]:

        raise HTTPException(
            status_code=403,
            detail=(
                "Email verification is not complete. "
                "Please verify your email first."
            )
        )


    if not user["is_active"]:

        raise HTTPException(
            status_code=403,
            detail="This account is inactive."
        )


    access_token = create_access_token(
        user_id=user["id"],
        email=user["email"],
        role=user["role"],
        secret_key=SECRET_KEY,
        expires_minutes=ACCESS_TOKEN_EXPIRE_MINUTES,
    )


    return {
        "success": True,
        "message": "Login successful.",
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "full_name": user["full_name"],
            "email": user["email"],
            "role": user["role"],
        },
    }


# =========================================================
# FORGOT PASSWORD
# =========================================================

@router.post("/forgot-password")
def forgot_password(
    request: ForgotPasswordRequest
):

    email = normalize_email(
        request.email
    )


    user = get_user_by_email(email)


    if not user:

        raise HTTPException(
            status_code=404,
            detail=(
                "No account found with "
                "this email address."
            )
        )


    otp_code = save_verification_otp(
        email=email,
        purpose="password_reset",
    )


    try:

        send_otp_email(
            recipient_email=email,
            otp_code=otp_code,
            purpose="password_reset",
        )

    except Exception as error:

        otps = read_otps()

        if email in otps:
            del otps[email]

        write_otps(otps)


        raise HTTPException(
            status_code=500,
            detail=(
                "Password reset email could not be sent. "
                f"Email service error: {error}"
            )
        )


    return {
        "success": True,
        "message": (
            "Password reset code has been "
            "sent to your email."
        ),
        "email": email,
    }


# =========================================================
# RESET PASSWORD
# =========================================================

@router.post("/reset-password")
def reset_password(
    request: ResetPasswordRequest
):

    email = normalize_email(
        request.email
    )

    users = read_users()

    otps = read_otps()


    user = next(
        (
            user
            for user in users
            if user["email"].lower() == email
        ),
        None
    )


    if not user:

        raise HTTPException(
            status_code=404,
            detail="Account not found."
        )


    otp_record = otps.get(email)


    if not otp_record:

        raise HTTPException(
            status_code=400,
            detail=(
                "No active password reset code found."
            )
        )


    if otp_record.get(
        "purpose"
    ) != "password_reset":

        raise HTTPException(
            status_code=400,
            detail="Invalid password reset request."
        )


    try:

        expires_at = datetime.fromisoformat(
            otp_record["expires_at"]
        )

    except (ValueError, KeyError):

        raise HTTPException(
            status_code=400,
            detail="Invalid password reset session."
        )


    if datetime.now(
        timezone.utc
    ) > expires_at:

        del otps[email]

        write_otps(otps)

        raise HTTPException(
            status_code=400,
            detail=(
                "Password reset code has expired."
            )
        )


    if request.otp != otp_record["otp"]:

        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid password reset code."
            )
        )


    user["hashed_password"] = hash_password(
        request.new_password
    )


    write_users(users)


    del otps[email]

    write_otps(otps)


    return {
        "success": True,
        "message": (
            "Password reset successfully."
        ),
    }
# =========================================================
# ADMIN ACCESS & USER MANAGEMENT
# =========================================================

ADMIN_ROLE = "admin"


def normalize_role_value(role: object) -> str:
    """
    Normalize legacy and alias role values to a canonical form.
    """

    normalized = str(role or "").strip().lower()
    normalized = normalized.replace("_", "-").replace("/", "-").replace(" ", "-")

    while "--" in normalized:
        normalized = normalized.replace("--", "-")

    normalized = normalized.strip("-")

    role_aliases = {
        "admin": "admin",
        "administrator": "admin",
        "reviewer": "reviewer",
        "finance": "reviewer",
        "finance-reviewer": "reviewer",
        "finance-reviewer-role": "reviewer",
        "finance-reviewer-role-name": "reviewer",
        "user": "user",
    }

    return role_aliases.get(normalized, normalized or "user")


def normalize_managed_role(role: object) -> str:
    """
    Normalize admin-managed account roles while accepting legacy aliases.
    """

    normalized = normalize_role_value(role)

    if normalized not in MANAGED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role must be either 'user' or 'reviewer'.",
        )

    return normalized


MANAGED_ROLES = {
    "user",
    "reviewer",
}


class AdminCreateManagedUserRequest(BaseModel):
    full_name: str = Field(
        min_length=2,
        max_length=100
    )

    email: EmailStr

    password: str = Field(
        min_length=8,
        max_length=128
    )

    role: str = Field(
        default="reviewer",
        min_length=1,
        max_length=30
    )


class AdminRoleUpdateRequest(BaseModel):
    role: str = Field(
        min_length=1,
        max_length=30
    )


class AdminStatusUpdateRequest(BaseModel):
    is_active: bool


def _decode_admin_jwt(
    token: str
) -> dict:
    """
    Decode the existing ClaimGuard JWT using the same secret
    and algorithm already used by login.
    """

    try:

        return jwt.decode(
            token,
            SECRET_KEY,
            algorithms=["HS256"]
        )

    except jwt.ExpiredSignatureError:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Session expired. "
                "Please sign in again."
            )
        )

    except jwt.InvalidTokenError:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Invalid authentication token."
            )
        )


def _get_admin_current_user(
    authorization: str | None
) -> dict:
    """
    Authenticate the caller and return the current user record.
    """

    if not authorization:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required."
        )

    if not authorization.startswith(
        "Bearer "
    ):

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header."
        )

    token = authorization.split(
        " ",
        1
    )[1]

    payload = _decode_admin_jwt(
        token
    )

    user_id = payload.get(
        "sub"
    )

    if not user_id:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token."
        )

    users = read_users()

    user = next(
        (
            item
            for item in users
            if item.get(
                "id"
            ) == user_id
        ),
        None
    )

    if not user:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account was not found."
        )

    if not user.get(
        "is_verified"
    ):

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email verification is required."
        )

    if not user.get(
        "is_active"
    ):

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is inactive."
        )

    return user


def _require_admin(
    authorization: str | None
) -> dict:
    """
    Only the Admin role can use user-management endpoints.
    """

    user = _get_admin_current_user(
        authorization
    )

    role = str(
        user.get(
            "role",
            ""
        )
    ).strip().lower()

    if role != ADMIN_ROLE:

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access is required."
        )

    return user


def _admin_safe_user(
    user: dict
) -> dict:
    """
    Never expose password hashes through admin APIs.
    """

    return {
        "id":
            user.get(
                "id"
            ),

        "full_name":
            user.get(
                "full_name"
            ),

        "email":
            user.get(
                "email"
            ),

        "role":
            user.get(
                "role"
            ),

        "is_verified":
            bool(
                user.get(
                    "is_verified"
                )
            ),

        "is_active":
            bool(
                user.get(
                    "is_active"
                )
            ),

        "created_at":
            user.get(
                "created_at"
            ),
    }


@router.get(
    "/admin/users"
)
def admin_list_users(
    authorization: str | None = Header(default=None),
):
    """
    List all ClaimGuard user accounts for the Admin dashboard.
    """

    _require_admin(
        authorization
    )

    users = read_users()

    return {
        "success":
            True,

        "count":
            len(users),

        "users":
            [
                _admin_safe_user(
                    user
                )
                for user in users
            ],
    }


@router.post(
    "/admin/users"
)
def admin_create_managed_user(
    request: AdminCreateManagedUserRequest,
    authorization: str | None = Header(default=None),
):
    """
    Admin creates a normal user or a Finance/Reviewer account.

    Admin-provisioned internal accounts are immediately active and
    verified; no public role self-selection is exposed.
    """

    admin_user = _require_admin(
        authorization
    )

    requested_role = str(
        request.role
    ).strip().lower()

    if requested_role not in MANAGED_ROLES:

        raise HTTPException(
            status_code=400,
            detail=(
                "Role must be either 'user' or 'reviewer'."
            )
        )

    email = normalize_email(
        request.email
    )

    users = read_users()

    existing = next(
        (
            user
            for user in users
            if user.get(
                "email",
                ""
            ).lower() == email
        ),
        None
    )

    if existing:

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "An account with this email already exists."
            )
        )

    user_id = str(
        uuid.uuid4()
    )

    managed_user = {
        "id":
            user_id,

        "full_name":
            request.full_name.strip(),

        "email":
            email,

        "hashed_password":
            hash_password(
                request.password
            ),

        "role":
            requested_role,

        "is_verified":
            True,

        "is_active":
            True,

        "created_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "created_by_admin_id":
            admin_user.get(
                "id"
            ),
    }

    users.append(
        managed_user
    )

    write_users(
        users
    )

    return {
        "success":
            True,

        "message":
            "Managed account created successfully.",

        "user":
            _admin_safe_user(
                managed_user
            ),
    }


@router.patch(
    "/admin/users/{user_id}/role"
)
def admin_update_user_role(
    user_id: str,
    request: AdminRoleUpdateRequest,
    authorization: str | None = Header(default=None),
):
    """
    Admin assigns a managed account to Normal User or Reviewer.
    """

    admin_user = _require_admin(
        authorization
    )

    requested_role = str(
        request.role
    ).strip().lower()

    if requested_role not in MANAGED_ROLES:

        raise HTTPException(
            status_code=400,
            detail=(
                "Role must be either 'user' or 'reviewer'."
            )
        )

    if user_id == admin_user.get(
        "id"
    ):

        raise HTTPException(
            status_code=400,
            detail=(
                "The current Admin account cannot be changed "
                "through this endpoint."
            )
        )

    users = read_users()

    target = next(
        (
            user
            for user in users
            if user.get(
                "id"
            ) == user_id
        ),
        None
    )

    if not target:

        raise HTTPException(
            status_code=404,
            detail="User account not found."
        )

    target["role"] = requested_role

    write_users(
        users
    )

    return {
        "success":
            True,

        "message":
            "User role updated successfully.",

        "user":
            _admin_safe_user(
                target
            ),
    }


@router.patch(
    "/admin/users/{user_id}/status"
)
def admin_update_user_status(
    user_id: str,
    request: AdminStatusUpdateRequest,
    authorization: str | None = Header(default=None),
):
    """
    Admin activates or deactivates a managed account.
    """

    admin_user = _require_admin(
        authorization
    )

    if user_id == admin_user.get(
        "id"
    ):

        raise HTTPException(
            status_code=400,
            detail=(
                "The current Admin account cannot be deactivated."
            )
        )

    users = read_users()

    target = next(
        (
            user
            for user in users
            if user.get(
                "id"
            ) == user_id
        ),
        None
    )

    if not target:

        raise HTTPException(
            status_code=404,
            detail="User account not found."
        )

    target["is_active"] = bool(
        request.is_active
    )

    write_users(
        users
    )

    return {
        "success":
            True,

        "message":
            (
                "User account activated."
                if target["is_active"]
                else
                "User account deactivated."
            ),

        "user":
            _admin_safe_user(
                target
            ),
    }
