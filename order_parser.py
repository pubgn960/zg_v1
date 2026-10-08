"""
Email + CP Package Real Customer Order Detection Parser for Telegram Email Image Delivery Bot.
Classifies a customer message as an ORDER ONLY when BOTH core conditions are met:
1. VALID EMAIL / LOGIN INFORMATION
2. CP PACKAGE (recognized CODM/CP package quantity, alias like 880Cp/72k/10800 CP, or addition pattern like 2400+880)

Platform and Password/Credentials are extracted as optional metadata if present.
"""

import re
import logging
from typing import Dict, Any, Optional
from email_parser import extract_email, EMAIL_REGEX

logger = logging.getLogger(__name__)

# Platform keywords (Facebook, FB, Meta, Activision, PSN, Xbox, Nintendo, Guest, Garena, etc.)
PLATFORM_REGEX = re.compile(
    r'\b(facebook|fb|meta|activision\s*id|activision|psn|playstation|xbox|nintendo|guest|garena|line|vk|apple|google)\b',
    re.IGNORECASE
)

# Login / Email keywords
LOGIN_KEYWORDS_REGEX = re.compile(
    r'\b(email|mail|correo|correo\s+electr[oó]nico|correo\s+o\s+n[uú]mero(?:\s+fb)?)\b',
    re.IGNORECASE
)

# Explicit Password / Credential keywords (requires actual credential information)
CREDENTIAL_REGEX = re.compile(
    r'\b(password|pass|pwd|contrase[nñ]a(?:\s+de\s+fb)?|clave|c[oó]digos?|recovery(?:\s+codes?)?|backup\s+codes?|2fa|authenticator)\b',
    re.IGNORECASE
)

# Known CODM/CP package quantities
KNOWN_PACKAGES = {
    5, 80, 420, 880, 2400, 4800, 5000, 5040, 7200, 9600, 10800, 12000, 14400,
    16800, 19200, 21600, 24000, 38400, 43200, 48000, 72000, 96000, 100800, 108000
}

# Package alias and multiplier pattern (e.g. 5k, 10k, 2.4k, 420x2, 880*3, 10800 CP, 880Cp, 5000Cp, 72k, 2400CP)
PACKAGE_ALIAS_REGEX = re.compile(
    r'\b(\d+(?:[\.\,]\d+)?\s*k(?:\s*cp)?|\d+\s*cp|\d+\s*[x×*]\s*\d+|\d+\s*codm)\b',
    re.IGNORECASE
)

# Multi-package addition pattern (e.g. 2400+880, 420+880+2400, 2400 + 880)
ADDITION_PACKAGE_REGEX = re.compile(
    r'\b\d+(?:\s*\+\s*\d+)+\b'
)


def normalize_order_text(text: Optional[str]) -> str:
    r"""
    Normalizes Telegram/Markdown text before parsing:
    - Unescapes Telegram backslash-escaped characters (\@, \_, \., \+, \-, \*, \~, \`, \#)
    - Strips Markdown formatting wrappers (**, __, `, ~)
    - Preserves line breaks and core credential values.
    """
    if not text:
        return ""
    # Unescape Telegram backslash-escaped characters
    s = re.sub(r'\\([@_.\-+*~`#\\])', r'\1', text)
    # Strip Markdown formatting tokens
    s = re.sub(r'(\*\*|__|`|~)', '', s)
    return s.strip()


def is_candidate_credential(line: str) -> bool:
    """
    Evaluates whether an unlabelled line after the email address line
    can be classified as a positional password/credential.
    """
    s = line.strip()
    if not s or len(s) < 4:
        return False
    # Not an email
    if EMAIL_REGEX.search(s):
        return False
    # Not a platform
    if PLATFORM_REGEX.search(s):
        return False
    # Not explicit price / currency (e.g. 14.5$, 120﷼, Free, 30$, 50 SAR, price 2400)
    if re.search(r'^\d+(?:\.\d+)?\s*[\$\﷼€£₹]|^\d+(?:\.\d+)?\s*sar|^free$|\b(price|precio|cost|costo)\b', s, re.IGNORECASE):
        return False
    # Not multi-package addition
    if ADDITION_PACKAGE_REGEX.search(s):
        return False
    # Not package alias (e.g. 880Cp, 72k, 10800 CP)
    if PACKAGE_ALIAS_REGEX.search(s):
        return False
    # Not known standalone package number or small price/quantity number
    if re.match(r'^\d+$', s):
        val = int(s)
        if val in KNOWN_PACKAGES or val < 100000:
            return False
    # Must contain valid password characters
    if not re.search(r'[A-Za-z0-9#@._\-!$]', s):
        return False
    return True


def parse_order_v2(text: Optional[str]) -> Dict[str, Any]:
    """
    Evaluates customer message against Email + CP Package rule:
    VALID EMAIL + VALID CP PACKAGE.

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

    clean_text = normalize_order_text(text)

    # Optional Metadata Extraction: PLATFORM
    plat_match = PLATFORM_REGEX.search(clean_text)
    platform_detected = bool(plat_match)
    platform_name = plat_match.group(0) if plat_match else None

    # Core Condition 1: LOGIN / EMAIL (Reuses email_parser.extract_email)
    extracted_email = extract_email(clean_text)
    login_kw_match = LOGIN_KEYWORDS_REGEX.search(clean_text)
    email_detected = bool(extracted_email or login_kw_match)

    # Optional Metadata Extraction: PASSWORD / CREDENTIALS
    cred_match = CREDENTIAL_REGEX.search(clean_text)
    credential_detected = bool(cred_match)

    lines = [l.strip() for l in clean_text.splitlines() if l.strip()]
    email_line_idx = None
    if extracted_email:
        for idx, line in enumerate(lines):
            if EMAIL_REGEX.search(line):
                email_line_idx = idx
                break

    if not credential_detected and email_line_idx is not None:
        for idx in range(email_line_idx + 1, len(lines)):
            if is_candidate_credential(lines[idx]):
                credential_detected = True
                break

    # Core Condition 2: CP PACKAGE
    package_detected = False
    extracted_pkg = None

    # Check multi-package addition pattern (e.g. 2400+880, 420+880+2400)
    add_match = ADDITION_PACKAGE_REGEX.search(clean_text)
    if add_match:
        package_detected = True
        extracted_pkg = add_match.group(0).strip()
    else:
        # Check alias/multiplier regex (e.g. 10800 CP, 880Cp, 5000Cp, 72k)
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

    # Final Order Detection Rule: EMAIL + CP PACKAGE ONLY
    missing_conditions = []
    if not email_detected:
        missing_conditions.append("Missing email")
    if not package_detected:
        missing_conditions.append("Missing package")

    order_detected = email_detected and package_detected

    if order_detected:
        reason = "All required conditions satisfied (Email + CP Package)"
    else:
        reason = ", ".join(missing_conditions)

    # Structured Debug Logging
    logger.info(
        f"[ORDER DETECTION] email_detected={email_detected}, package_detected={package_detected}, "
        f"email={extracted_email}, package={extracted_pkg}"
    )

    if order_detected:
        logger.info("[ORDER DETECTION] TRUE")
    else:
        logger.info(f"[ORDER DETECTION] FALSE — missing: {reason}")

    return {
        "order_detected": order_detected,
        "platform_detected": platform_detected,
        "login_detected": email_detected,
        "credential_detected": credential_detected,
        "package_detected": package_detected,
        "platform": platform_name,
        "email": extracted_email,
        "package": extracted_pkg,
        "reason": reason
    }
