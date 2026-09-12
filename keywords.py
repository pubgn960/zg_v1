"""
Order Detection Keywords Configuration.
Delegates order detection to parse_order_v2 (single source of truth).
"""

from typing import Tuple, Optional
from order_parser import parse_order_v2


def contains_order_keyword(text: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Evaluates customer message text or caption against strict 4-condition order detection system.

    Args:
        text (Optional[str]): Message text, photo caption, or document caption.

    Returns:
        Tuple[bool, Optional[str]]: (is_matched, matched_detail)
    """
    decision = parse_order_v2(text)
    if decision["order_detected"]:
        kw = decision["platform"] or decision["package"] or "order"
        return True, kw

    return False, None
