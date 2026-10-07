/**
 * =========================================================
 * CLAIMGUARD FRONTEND
 * =========================================================
 */

const API_BASE_URL = "http://127.0.0.1:8000";


document.addEventListener(
    "DOMContentLoaded",
    () => {

        initializePasswordToggles();

        initializeOTPInputs();

        initializeLoginForm();

        initializeRegisterForm();

        initializeVerificationForm();

        initializeVerificationEmailDisplay();

        initializeForgotPasswordForm();

        initializeResetPasswordForm();

        initializeGoogleButtons();

        initializeResendButton();

    }
);


/**
 * =========================================================
 * PASSWORD SHOW / HIDE
 * =========================================================
 */

function initializePasswordToggles() {

    const toggles = [

        {
            buttonId: "togglePassword",
            inputId: "password"
        },

        {
            buttonId: "toggleRegisterPassword",
            inputId: "registerPassword"
        },

        {
            buttonId: "toggleConfirmPassword",
            inputId: "confirmPassword"
        },

        {
            buttonId: "toggleNewPassword",
            inputId: "newPassword"
        },

        {
            buttonId: "toggleConfirmNewPassword",
            inputId: "confirmNewPassword"
        }

    ];


    toggles.forEach(
        ({ buttonId, inputId }) => {

            const button =
                document.getElementById(
                    buttonId
                );

            const input =
                document.getElementById(
                    inputId
                );


            if (!button || !input) {
                return;
            }


            button.addEventListener(
                "click",
                () => {

                    if (
                        input.type ===
                        "password"
                    ) {

                        input.type = "text";

                        button.textContent =
                            "Hide";

                    } else {

                        input.type =
                            "password";

                        button.textContent =
                            "Show";

                    }

                }
            );

        }
    );

}


/**
 * =========================================================
 * OTP INPUTS
 * =========================================================
 */

function initializeOTPInputs() {

    const inputs =
        document.querySelectorAll(
            ".otp-input"
        );


    if (inputs.length === 0) {
        return;
    }


    inputs.forEach(
        (input, index) => {

            input.addEventListener(
                "input",
                () => {

                    input.value =
                        input.value
                            .replace(/\D/g, "")
                            .slice(0, 1);


                    if (
                        input.value &&
                        index <
                        inputs.length - 1
                    ) {

                        inputs[index + 1]
                            .focus();

                    }

                }
            );


            input.addEventListener(
                "keydown",
                (event) => {

                    if (
                        event.key ===
                        "Backspace" &&
                        !input.value &&
                        index > 0
                    ) {

                        inputs[index - 1]
                            .focus();

                    }


                    if (
                        event.key ===
                        "ArrowLeft" &&
                        index > 0
                    ) {

                        inputs[index - 1]
                            .focus();

                    }


                    if (
                        event.key ===
                        "ArrowRight" &&
                        index <
                        inputs.length - 1
                    ) {

                        inputs[index + 1]
                            .focus();

                    }

                }
            );

        }
    );


    // Paste complete OTP
    inputs[0].addEventListener(
        "paste",
        (event) => {

            event.preventDefault();


            const pasted =
                event.clipboardData
                    .getData("text")
                    .replace(/\D/g, "")
                    .slice(
                        0,
                        inputs.length
                    );


            pasted
                .split("")
                .forEach(
                    (digit, index) => {

                        if (inputs[index]) {

                            inputs[index].value =
                                digit;

                        }

                    }
                );


            if (pasted.length > 0) {

                const focusIndex =
                    Math.min(
                        pasted.length,
                        inputs.length - 1
                    );

                inputs[focusIndex]
                    .focus();

            }

        }
    );

}


/**
 * =========================================================
 * LOGIN
 * =========================================================
 */

function initializeLoginForm() {

    const form =
        document.getElementById(
            "loginForm"
        );


    if (!form) {
        return;
    }


    form.addEventListener(
        "submit",
        async (event) => {

            event.preventDefault();


            const email =
                document.getElementById(
                    "email"
                )
                ?.value
                .trim();


            const password =
                document.getElementById(
                    "password"
                )
                ?.value;


            const message =
                document.getElementById(
                    "loginMessage"
                );


            const button =
                form.querySelector(
                    ".login-submit"
                );


            if (!email || !password) {

                showMessage(
                    message,
                    "Please enter your email and password."
                );

                return;
            }


            try {

                button.disabled = true;

                button.textContent =
                    "Signing in...";


                const response =
                    await fetch(
                        `${API_BASE_URL}/api/auth/login`,
                        {
                            method: "POST",

                            headers: {
                                "Content-Type":
                                    "application/json"
                            },

                            body: JSON.stringify({
                                email,
                                password
                            })
                        }
                    );


                const data =
                    await response.json();


                if (!response.ok) {

                    throw new Error(
                        data.detail ||
                        "Login failed."
                    );

                }


                localStorage.setItem(
                    "claimguard_access_token",
                    data.access_token
                );


                localStorage.setItem(
                    "claimguard_user",
                    JSON.stringify(
                        data.user
                    )
                );


                showMessage(
                    message,
                    "Login successful. Redirecting..."
                );


                setTimeout(
                    () => {

                        redirectByRole(
                            data.user.role
                        );

                    },
                    500
                );


            } catch (error) {

                console.error(
                    "Login error:",
                    error
                );


                showMessage(
                    message,
                    error.message
                );


            } finally {

                button.disabled =
                    false;

                button.textContent =
                    "Sign In";

            }

        }
    );

}


/**
 * =========================================================
 * ROLE REDIRECTION
 * =========================================================
 */

function normalizeRole(role) {

    const normalized = String(
        role ?? ""
    )
        .trim()
        .toLowerCase()
        .replace(/[_/\s]+/g, "-")
        .replace(/-+/g, "-");

    if (!normalized || normalized === "user") {
        return "user";
    }

    if (["admin", "administrator"].includes(normalized)) {
        return "admin";
    }

    if (["reviewer", "finance", "finance-reviewer", "finance-reviewer-role", "finance-reviewer-role"].includes(normalized)) {
        return "reviewer";
    }

    return normalized;
}


function redirectByRole(role) {

    const normalizedRole =
        normalizeRole(role);

    if (normalizedRole === "admin") {
        window.location.href = "admin-dashboard.html";
        return;
    }

    if (["reviewer", "finance", "finance-reviewer"].includes(normalizedRole)) {
        window.location.href = "reviewer-dashboard.html";
        return;
    }

    window.location.href = "user-dashboard.html";
}


/**
 * =========================================================
 * REGISTER
 * =========================================================
 */

function initializeRegisterForm() {

    const form =
        document.getElementById(
            "registerForm"
        );


    if (!form) {
        return;
    }


    form.addEventListener(
        "submit",
        async (event) => {

            event.preventDefault();


            const name =
                document.getElementById(
                    "fullName"
                )
                ?.value
                .trim();


            const email =
                document.getElementById(
                    "registerEmail"
                )
                ?.value
                .trim();


            const password =
                document.getElementById(
                    "registerPassword"
                )
                ?.value;


            const confirmPassword =
                document.getElementById(
                    "confirmPassword"
                )
                ?.value;


            const terms =
                document.getElementById(
                    "terms"
                )
                ?.checked;


            const message =
                document.getElementById(
                    "registerMessage"
                );


            const button =
                form.querySelector(
                    ".login-submit"
                );


            if (
                !name ||
                !email ||
                !password ||
                !confirmPassword
            ) {

                showMessage(
                    message,
                    "Please complete all required fields."
                );

                return;
            }


            if (password.length < 8) {

                showMessage(
                    message,
                    "Password must contain at least 8 characters."
                );

                return;
            }


            if (
                password !==
                confirmPassword
            ) {

                showMessage(
                    message,
                    "Passwords do not match."
                );

                return;
            }


            if (!terms) {

                showMessage(
                    message,
                    "Please accept the Terms of Service and Privacy Policy."
                );

                return;
            }


            try {

                button.disabled = true;

                button.textContent =
                    "Creating account...";


                const response =
                    await fetch(
                        `${API_BASE_URL}/api/auth/register`,
                        {
                            method: "POST",

                            headers: {
                                "Content-Type":
                                    "application/json"
                            },

                            body: JSON.stringify({
                                full_name: name,
                                email,
                                password
                            })
                        }
                    );


                const data =
                    await response.json();


                if (!response.ok) {

                    throw new Error(
                        data.detail ||
                        "Registration failed."
                    );

                }


                // Store pending verification
                localStorage.setItem(
                    "claimguard_pending_verification_email",
                    data.email
                );


                showMessage(
                    message,
                    "Account ready. Opening email verification..."
                );


                // ALWAYS redirect after successful register
                setTimeout(
                    () => {

                        window.location.href =
                            `verify-email.html?email=${encodeURIComponent(
                                data.email
                            )}`;

                    },
                    400
                );


            } catch (error) {

                console.error(
                    "Registration error:",
                    error
                );


                showMessage(
                    message,
                    error.message
                );


            } finally {

                button.disabled =
                    false;

                button.textContent =
                    "Create Account";

            }

        }
    );

}


/**
 * =========================================================
 * VERIFICATION EMAIL DISPLAY
 * =========================================================
 */

function initializeVerificationEmailDisplay() {

    const emailInput =
        document.getElementById(
            "verificationEmailInput"
        );


    if (!emailInput) {
        return;
    }


    const params =
        new URLSearchParams(
            window.location.search
        );


    const urlEmail =
        params.get("email");


    const savedEmail =
        localStorage.getItem(
            "claimguard_pending_verification_email"
        );


    const email =
        urlEmail ||
        savedEmail;


    if (email) {

        emailInput.value =
            email;

        emailInput.readOnly =
            true;

        localStorage.setItem(
            "claimguard_pending_verification_email",
            email
        );

    } else {

        emailInput.readOnly =
            false;

        emailInput.placeholder =
            "Enter the email you registered with";

    }

}


/**
 * =========================================================
 * VERIFY EMAIL
 * =========================================================
 */

function initializeVerificationForm() {

    const form =
        document.getElementById(
            "verificationForm"
        );


    if (!form) {
        return;
    }


    const message =
        document.getElementById(
            "verificationMessage"
        );


    form.addEventListener(
        "submit",
        async (event) => {

            event.preventDefault();


            const email =
                document.getElementById(
                    "verificationEmailInput"
                )
                ?.value
                .trim();


            const inputs =
                document.querySelectorAll(
                    ".otp-input"
                );


            const otp =
                Array.from(inputs)
                    .map(
                        input => input.value
                    )
                    .join("");


            const button =
                form.querySelector(
                    ".login-submit"
                );


            if (!email) {

                showMessage(
                    message,
                    "Please enter your verification email."
                );

                return;
            }


            if (otp.length !== 6) {

                showMessage(
                    message,
                    "Please enter the complete 6-digit code."
                );

                return;
            }


            try {

                button.disabled = true;

                button.textContent =
                    "Verifying...";


                const response =
                    await fetch(
                        `${API_BASE_URL}/api/auth/verify-email`,
                        {
                            method: "POST",

                            headers: {
                                "Content-Type":
                                    "application/json"
                            },

                            body: JSON.stringify({
                                email,
                                otp
                            })
                        }
                    );


                const data =
                    await response.json();


                if (!response.ok) {

                    throw new Error(
                        data.detail ||
                        "Email verification failed."
                    );

                }


                localStorage.removeItem(
                    "claimguard_pending_verification_email"
                );


                showMessage(
                    message,
                    "Email verified successfully. Redirecting to login..."
                );


                setTimeout(
                    () => {

                        window.location.href =
                            "login.html";

                    },
                    800
                );


            } catch (error) {

                console.error(
                    "Verification error:",
                    error
                );


                showMessage(
                    message,
                    error.message
                );


            } finally {

                button.disabled =
                    false;

                button.textContent =
                    "Verify Email";

            }

        }
    );

}


/**
 * =========================================================
 * RESEND VERIFICATION CODE
 * =========================================================
 */

function initializeResendButton() {

    const button =
        document.getElementById(
            "resendCodeBtn"
        );


    const timer =
        document.getElementById(
            "resendTimer"
        );


    const message =
        document.getElementById(
            "verificationMessage"
        );


    if (!button || !timer) {
        return;
    }


    let seconds = 0;


    button.addEventListener(
        "click",
        async () => {

            if (seconds > 0) {
                return;
            }


            const email =
                document.getElementById(
                    "verificationEmailInput"
                )
                ?.value
                .trim();


            if (!email) {

                showMessage(
                    message,
                    "Please enter your verification email."
                );

                return;
            }


            try {

                button.disabled = true;

                button.textContent =
                    "Sending...";


                const response =
                    await fetch(
                        `${API_BASE_URL}/api/auth/resend-verification`,
                        {
                            method: "POST",

                            headers: {
                                "Content-Type":
                                    "application/json"
                            },

                            body: JSON.stringify({
                                email
                            })
                        }
                    );


                const data =
                    await response.json();


                if (!response.ok) {

                    throw new Error(
                        data.detail ||
                        "Unable to resend the code."
                    );

                }


                localStorage.setItem(
                    "claimguard_pending_verification_email",
                    data.email
                );


                showMessage(
                    message,
                    "A new verification code has been sent to your email."
                );


                startResendTimer(
                    button,
                    timer
                );


            } catch (error) {

                console.error(
                    "Resend error:",
                    error
                );


                showMessage(
                    message,
                    error.message
                );


                button.disabled =
                    false;

                button.textContent =
                    "Resend Code";

            }

        }
    );

}


/**
 * =========================================================
 * RESEND TIMER
 * =========================================================
 */

function startResendTimer(
    button,
    timer
) {

    let seconds = 30;


    button.disabled = true;

    button.textContent =
        "Code Sent";


    timer.textContent =
        `You can resend the code in ${seconds}s.`;


    const interval =
        setInterval(
            () => {

                seconds--;


                if (seconds <= 0) {

                    clearInterval(
                        interval
                    );


                    button.disabled =
                        false;

                    button.textContent =
                        "Resend Code";

                    timer.textContent =
                        "You can request a new code.";

                    return;
                }


                timer.textContent =
                    `You can resend the code in ${seconds}s.`;

            },
            1000
        );

}


/**
 * =========================================================
 * FORGOT PASSWORD
 * =========================================================
 */

function initializeForgotPasswordForm() {

    const form =
        document.getElementById(
            "forgotPasswordForm"
        );


    if (!form) {
        return;
    }


    const message =
        document.getElementById(
            "forgotPasswordMessage"
        );


    form.addEventListener(
        "submit",
        async (event) => {

            event.preventDefault();


            const email =
                document.getElementById(
                    "forgotEmail"
                )
                ?.value
                .trim();


            const button =
                form.querySelector(
                    ".login-submit"
                );


            if (!email) {

                showMessage(
                    message,
                    "Please enter your email address."
                );

                return;
            }


            try {

                button.disabled =
                    true;

                button.textContent =
                    "Sending...";


                const response =
                    await fetch(
                        `${API_BASE_URL}/api/auth/forgot-password`,
                        {
                            method: "POST",

                            headers: {
                                "Content-Type":
                                    "application/json"
                            },

                            body: JSON.stringify({
                                email
                            })
                        }
                    );


                const data =
                    await response.json();


                if (!response.ok) {

                    throw new Error(
                        data.detail ||
                        "Password reset request failed."
                    );

                }


                localStorage.setItem(
                    "claimguard_reset_email",
                    data.email
                );


                window.location.href =
                    `reset-password.html?email=${encodeURIComponent(
                        data.email
                    )}`;


            } catch (error) {

                console.error(
                    "Forgot password error:",
                    error
                );


                showMessage(
                    message,
                    error.message
                );


            } finally {

                button.disabled =
                    false;

                button.textContent =
                    "Send Reset Code";

            }

        }
    );

}


/**
 * =========================================================
 * RESET PASSWORD
 * =========================================================
 */

function initializeResetPasswordForm() {

    const form =
        document.getElementById(
            "resetPasswordForm"
        );


    if (!form) {
        return;
    }


    const message =
        document.getElementById(
            "resetPasswordMessage"
        );


    form.addEventListener(
        "submit",
        async (event) => {

            event.preventDefault();


            const params =
                new URLSearchParams(
                    window.location.search
                );


            const email =
                params.get("email") ||
                localStorage.getItem(
                    "claimguard_reset_email"
                );


            const inputs =
                document.querySelectorAll(
                    ".otp-input"
                );


            const otp =
                Array.from(inputs)
                    .map(
                        input => input.value
                    )
                    .join("");


            const newPassword =
                document.getElementById(
                    "newPassword"
                )
                ?.value;


            const confirmPassword =
                document.getElementById(
                    "confirmNewPassword"
                )
                ?.value;


            const button =
                form.querySelector(
                    ".login-submit"
                );


            if (!email) {

                showMessage(
                    message,
                    "No password reset email was found."
                );

                return;
            }


            if (otp.length !== 6) {

                showMessage(
                    message,
                    "Please enter the complete 6-digit code."
                );

                return;
            }


            if (
                !newPassword ||
                newPassword.length < 8
            ) {

                showMessage(
                    message,
                    "Password must contain at least 8 characters."
                );

                return;
            }


            if (
                newPassword !==
                confirmPassword
            ) {

                showMessage(
                    message,
                    "Passwords do not match."
                );

                return;
            }


            try {

                button.disabled =
                    true;

                button.textContent =
                    "Resetting...";


                const response =
                    await fetch(
                        `${API_BASE_URL}/api/auth/reset-password`,
                        {
                            method: "POST",

                            headers: {
                                "Content-Type":
                                    "application/json"
                            },

                            body: JSON.stringify({
                                email,
                                otp,
                                new_password:
                                    newPassword
                            })
                        }
                    );


                const data =
                    await response.json();


                if (!response.ok) {

                    throw new Error(
                        data.detail ||
                        "Password reset failed."
                    );

                }


                localStorage.removeItem(
                    "claimguard_reset_email"
                );


                showMessage(
                    message,
                    "Password reset successfully. Redirecting to login..."
                );


                setTimeout(
                    () => {

                        window.location.href =
                            "login.html";

                    },
                    800
                );


            } catch (error) {

                console.error(
                    "Reset password error:",
                    error
                );


                showMessage(
                    message,
                    error.message
                );


            } finally {

                button.disabled =
                    false;

                button.textContent =
                    "Reset Password";

            }

        }
    );

}


/**
 * =========================================================
 * GOOGLE BUTTONS
 * =========================================================
 */

function initializeGoogleButtons() {

    const loginButton =
        document.getElementById(
            "googleLoginBtn"
        );


    const registerButton =
        document.getElementById(
            "googleRegisterBtn"
        );


    if (loginButton) {

        loginButton.addEventListener(
            "click",
            () => {

                alert(
                    "Google authentication will be connected next."
                );

            }
        );

    }


    if (registerButton) {

        registerButton.addEventListener(
            "click",
            () => {

                alert(
                    "Google authentication will be connected next."
                );

            }
        );

    }

}


/**
 * =========================================================
 * COMMON MESSAGE
 * =========================================================
 */

function showMessage(
    element,
    message
) {

    if (!element) {
        return;
    }


    element.textContent =
        message;

    element.style.display =
        "block";

}