"""
Strict 4-Condition Order Detection Parser for Telegram Email Image Delivery Bot.
Enforces that a customer message is classified as an ORDER ONLY when ALL 4 conditions are met:
1. PLATFORM (facebook, fb, meta, activision, activision id)
2. LOGIN / EMAIL INFORMATION (valid email or login/email keywords)
3. PASSWORD / CREDENTIALS (password, pass, pwd, login, contraseña, 2fa, recovery code, etc.)
4. PACKAGE (recognized CODM/CP package quantity or format)
"""

import re
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Standard Regex pattern for detecting email addresses
EMAIL_REGEX = re.compile(
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b',
    re.IGNORECASE
)

# Condition 1: Platform keywords
PLATFORM_REGEX = re.compile(
    r'\b(facebook|fb|meta|activision\s*id|activision)\b',
    re.IGNORECASE
)

# Condition 2: Login / Email keywords
LOGIN_KEYWORDS_REGEX = re.compile(
    r'\b(email|mail|correo|correo\s+electr[oó]nico|correo\s+o\s+n[uú]mero(?:\s+fb)?)\b',
    re.IGNORECASE
)

# Condition 3: Password / Credential keywords
CREDENTIAL_REGEX = re.compile(
    r'\b(password|pass|pwd|login|contrase[nñ]a(?:\s+de\s+fb)?|clave|c[oó]digos?|recovery(?:\s+codes?)?|backup\s+codes?|2fa|authenticator|nick|ign|usuario|nombre)\b',
    re.IGNORECASE
)

# Condition 4: Known CODM/CP package quantities
KNOWN_PACKAGES = {
    5, 80, 420, 880, 2400, 5040, 7200, 9600, 10800, 12000, 14400,
    16800, 19200, 21600, 24000, 38400, 43200, 48000, 72000, 96000, 108000
}

# Package alias and multiplier pattern (e.g. 5k, 10k, 2.4k, 420x2, 880*3, 10800 CP)
PACKAGE_ALIAS_REGEX = re.compile(
    r'\b(\d+(?:[\.\,]\d+)?\s*k|\d+\s*cp|\d+\s*[x×*]\s*\d+|\d+\s*codm)\b',
    re.IGNORECASE
)


def parse_order_v2(text: Optional[str]) -> Dict[str, Any]:
    """
    Evaluates customer message against strict 4-condition system.

    Returns:
        Dict[str, Any]: Decision object containing:
            - order_detected: bool
            - platform_detected: bool
            - login_detected: bool
            - credential_detected: bool
            - package_detected: bool
            - platform: Optional[str]
            - email: Optional[str]
            - package: Optional[str]
            - reason: str
    """
    if not text or not text.strip():
        return {
            "order_detected": False,
            "platform_detected": False,
            "login_detected": False,
            "credential_detected": False,
            "package_detected": False,
            "platform": None,
            "email": None,
            "package": None,
            "reason": "Empty text"
        }

    clean_text = text.strip()

    # 1. Condition 1: PLATFORM
    plat_match = PLATFORM_REGEX.search(clean_text)
    platform_detected = bool(plat_match)
    platform_name = plat_match.group(0) if plat_match else None

    # 2. Condition 2: LOGIN / EMAIL
    email_match = EMAIL_REGEX.search(clean_text)
    extracted_email = email_match.group(0).rstrip(".,;!)]>").lower() if email_match else None
    login_kw_match = LOGIN_KEYWORDS_REGEX.search(clean_text)
    login_detected = bool(extracted_email or login_kw_match)

    # 3. Condition 3: PASSWORD / CREDENTIALS
    cred_match = CREDENTIAL_REGEX.search(clean_text)
    credential_detected = bool(cred_match)

    # 4. Condition 4: PACKAGE
    package_detected = False
    extracted_pkg = None

    # Check alias/multiplier regex (e.g. 10800 CP, 5k, 420x2)
    pkg_alias_match = PACKAGE_ALIAS_REGEX.search(clean_text)
    if pkg_alias_match:
        package_detected = True
        extracted_pkg = pkg_alias_match.group(0).strip()
    else:
        # Check known numeric packages
        numbers = re.findall(r'\b\d+\b', clean_text)
        for num_str in numbers:
            num_val = int(num_str)
            if num_val in KNOWN_PACKAGES:
                package_detected = True
                extracted_pkg = f"{num_val} CP"
                break

    # Determine missing conditions for reason
    missing_conditions = []
    if not platform_detected:
        missing_conditions.append("Missing platform")
    if not login_detected:
        missing_conditions.append("Missing email/login info")
    if not credential_detected:
        missing_conditions.append("Missing password/login details")
    if not package_detected:
        missing_conditions.append("Missing package")

    order_detected = platform_detected and login_detected and credential_detected and package_detected

    reason = "All 4 conditions satisfied" if order_detected else ", ".join(missing_conditions)

    return {
        "order_detected": order_detected,
        "platform_detected": platform_detected,
        "login_detected": login_detected,
        "credential_detected": credential_detected,
        "package_detected": package_detected,
        "platform": platform_name,
        "email": extracted_email,
        "package": extracted_pkg,
        "reason": reason
    }
