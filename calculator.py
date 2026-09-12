"""
Safe mathematical evaluator and Multi-Message Interactive Calculator Session for Telegram Email Image Delivery Bot.
Provides AST-whitelist arithmetic evaluation, interactive per-user Super Admin calculator sessions, and HTML response formatting.
Exclusively handles math and memory calculations without database queries or eval().
"""

import ast
import re
import logging
from typing import Union, List, Tuple, Dict, Any

logger = logging.getLogger(__name__)

# Maximum allowed expression length to prevent DoS
MAX_EXPR_LENGTH = 200
# Maximum allowed power exponent
MAX_EXPONENT = 1000
# Maximum allowed AST node count
MAX_AST_NODES = 50

# Per-user in-memory calculator session dictionary (user_id -> {"step": "before" | "now", "before": float/int})
CALCULATOR_SESSIONS: Dict[int, Dict[str, Any]] = {}


class SafeEvalVisitor(ast.NodeVisitor):
    """
    AST NodeVisitor that safely evaluates arithmetic expressions using a strict whitelist.
    Allowed operations: +, -, *, /, //, %, **, unary +, unary -, positive/negative numbers, decimals, parentheses.
    Forbidden: function calls, variables, imports, attribute access, strings, tuples/lists/dicts, arbitrary Python code.
    """

    def __init__(self):
        self.node_count = 0

    def visit(self, node: ast.AST) -> Union[int, float]:
        self.node_count += 1
        if self.node_count > MAX_AST_NODES:
            raise ValueError("Expression contains too many operations.")
        return super().visit(node)

    def visit_Expression(self, node: ast.Expression) -> Union[int, float]:
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> Union[int, float]:
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise ValueError("Only numeric constants are allowed.")

    def visit_Num(self, node: ast.Num) -> Union[int, float]:
        # Backward compatibility for Python AST Num node
        if isinstance(node.n, (int, float)) and not isinstance(node.n, bool):
            return node.n
        raise ValueError("Only numeric constants are allowed.")

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Union[int, float]:
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.UAdd):
            return +operand
        elif isinstance(node.op, ast.USub):
            return -operand
        raise ValueError("Unsupported unary operator.")

    def visit_BinOp(self, node: ast.BinOp) -> Union[int, float]:
        left = self.visit(node.left)
        right = self.visit(node.right)

        if isinstance(node.op, ast.Add):
            return left + right
        elif isinstance(node.op, ast.Sub):
            return left - right
        elif isinstance(node.op, ast.Mult):
            return left * right
        elif isinstance(node.op, ast.Div):
            if right == 0:
                raise ZeroDivisionError("Division by zero.")
            return left / right
        elif isinstance(node.op, ast.FloorDiv):
            if right == 0:
                raise ZeroDivisionError("Division by zero.")
            return left // right
        elif isinstance(node.op, ast.Mod):
            if right == 0:
                raise ZeroDivisionError("Division by zero.")
            return left % right
        elif isinstance(node.op, ast.Pow):
            if abs(right) > MAX_EXPONENT or abs(left) > 1e100:
                raise ValueError("Exponent or base too large.")
            return left ** right
        raise ValueError("Unsupported binary operator.")

    def generic_visit(self, node: ast.AST):
        raise ValueError(f"Forbidden syntax: {type(node).__name__}")


def safe_eval(expr: str) -> Union[int, float]:
    """
    Safely parses and evaluates a mathematical string expression using SafeEvalVisitor.
    """
    clean_expr = expr.strip()
    if not clean_expr:
        raise ValueError("Empty expression.")

    if len(clean_expr) > MAX_EXPR_LENGTH:
        raise ValueError("Expression is too long.")

    try:
        parsed_ast = ast.parse(clean_expr, mode='eval')
    except Exception as e:
        raise ValueError("Invalid mathematical syntax.") from e

    visitor = SafeEvalVisitor()
    result = visitor.visit(parsed_ast)

    # Return integer if result is a whole number float (e.g. 150.0 -> 150)
    if isinstance(result, float) and result.is_integer():
        return int(result)
    return result


def format_num(val: Union[int, float]) -> str:
    """Formats numeric value for HTML display without unnecessary trailing zeros."""
    if isinstance(val, float):
        if val.is_integer():
            return str(int(val))
        return f"{val:g}"
    return str(val)


def format_signed_num(val: Union[int, float]) -> str:
    """Formats numeric total with explicit + / - sign."""
    formatted = format_num(val)
    if val > 0:
        return f"+{formatted}"
    return formatted


# ==========================================
# Interactive Multi-Message Session API
# ==========================================

def start_calculator_session(user_id: int) -> str:
    """
    Starts an interactive multi-message calculator session for a Super Admin.
    Initializes step to 'before'.
    """
    CALCULATOR_SESSIONS[user_id] = {"step": "before"}
    logger.info(f"[CALC] Started calculator session for user_id: {user_id}")
    return "🧮 <b>Calculator</b>\n\nEnter BEFORE value:"


def cancel_calculator_session(user_id: int) -> str:
    """
    Cancels an active calculator session for a Super Admin.
    """
    existed = CALCULATOR_SESSIONS.pop(user_id, None)
    if existed:
        logger.info(f"[CALC] Cancelled calculator session for user_id: {user_id}")
    return "❌ Calculator cancelled."


def has_active_calculator_session(user_id: int) -> bool:
    """
    Checks whether a Super Admin has an active calculator session.
    """
    return user_id in CALCULATOR_SESSIONS


def process_calculator_session_input(user_id: int, text: str) -> str:
    """
    Processes numeric input for active calculator session (Step 1 BEFORE / Step 2 NOW).
    """
    session = CALCULATOR_SESSIONS.get(user_id)
    if not session:
        return "❌ No active calculator session."

    try:
        val = safe_eval(text.strip())
    except Exception as e:
        logger.debug(f"[CALC] Invalid numeric input '{text}' from user {user_id}: {e}")
        return "❌ Please enter a valid number."

    step = session.get("step")
    if step == "before":
        CALCULATOR_SESSIONS[user_id] = {
            "step": "now",
            "before": val
        }
        logger.info(f"[CALC] User {user_id} set BEFORE = {val}")
        return "Enter NOW value:"
    elif step == "now":
        before_val = session.get("before", 0)
        now_val = val
        total = now_val - before_val
        CALCULATOR_SESSIONS.pop(user_id, None)
        logger.info(f"[CALC] Completed calculation for user {user_id}: Before={before_val}, Now={now_val}, Total={total}")
        return (
            "🧮 <b>Calculation</b>\n\n"
            f"<b>Before:</b> {format_num(before_val)}\n"
            f"<b>Now:</b> {format_num(now_val)}\n"
            f"<b>Total:</b> {format_signed_num(total)}"
        )

    CALCULATOR_SESSIONS.pop(user_id, None)
    return "❌ Invalid session state."


def parse_before_now(text: str) -> List[Tuple[Union[int, float], Union[int, float], Union[int, float]]]:
    """
    Parses 'before' and 'now' value pairs from input string (Single-line helper).
    """
    results = []

    pattern_bn = re.compile(
        r'before\s*[:=]?\s*([^\s\a-zA-Z]+|\(?[-+*/.0-9()]+\)?)\s*now\s*[:=]?\s*([^\s\a-zA-Z]+|\(?[-+*/.0-9()]+\)?)',
        re.IGNORECASE
    )
    matches_bn = pattern_bn.findall(text)

    if matches_bn:
        for b_str, n_str in matches_bn:
            b_val = safe_eval(b_str)
            n_val = safe_eval(n_str)
            total = n_val - b_val
            results.append((b_val, n_val, total))
        return results

    pattern_nb = re.compile(
        r'now\s*[:=]?\s*([^\s\a-zA-Z]+|\(?[-+*/.0-9()]+\)?)\s*before\s*[:=]?\s*([^\s\a-zA-Z]+|\(?[-+*/.0-9()]+\)?)',
        re.IGNORECASE
    )
    matches_nb = pattern_nb.findall(text)

    if matches_nb:
        for n_str, b_str in matches_nb:
            b_val = safe_eval(b_str)
            n_val = safe_eval(n_str)
            total = n_val - b_val
            results.append((b_val, n_val, total))
        return results

    return []


def calculate_input(raw_args: str) -> str:
    """
    Single-line entry point for processing calculator command input text.
    Handles Before/Now mode and Direct Math mode.
    """
    clean_text = raw_args.strip()
    if not clean_text:
        return (
            "❌ <b>Invalid format.</b>\n\n"
            "<b>Usage Examples:</b>\n"
            "• <code>/calc before 100 now 150</code>\n"
            "• <code>/calc 100+50</code>\n"
            "• <code>/calc before 100 now 150 before 500 now 350</code>"
        )

    if re.search(r'\bbefore\b|\bnow\b', clean_text, re.IGNORECASE):
        try:
            pairs = parse_before_now(clean_text)
            if not pairs:
                return (
                    "❌ <b>Invalid format.</b>\n\n"
                    "Use: <code>/calc before 100 now 150</code>"
                )

            if len(pairs) == 1:
                b_val, n_val, total = pairs[0]
                return (
                    "📊 <b>Calculator</b>\n\n"
                    f"<b>Before:</b> {format_num(b_val)}\n"
                    f"<b>Now:</b> {format_num(n_val)}\n"
                    f"<b>Total:</b> {format_signed_num(total)}"
                )
            else:
                lines = ["📊 <b>Calculator</b>\n"]
                grand_total = 0
                for idx, (b_val, n_val, total) in enumerate(pairs, start=1):
                    grand_total += total
                    lines.append(
                        f"<b>{idx}.</b>\n"
                        f"<b>Before:</b> {format_num(b_val)}\n"
                        f"<b>Now:</b> {format_num(n_val)}\n"
                        f"<b>Total:</b> {format_signed_num(total)}\n"
                    )
                lines.append(f"<b>Grand Total:</b> {format_signed_num(grand_total)}")
                return "\n".join(lines)
        except ZeroDivisionError:
            return "❌ <b>Error:</b> Division by zero"
        except Exception as e:
            logger.warning(f"[CALC] Before/Now parsing failed: {e}")
            return (
                "❌ <b>Invalid format.</b>\n\n"
                "Use: <code>/calc before 100 now 150</code>"
            )

    try:
        val = safe_eval(clean_text)
        return f"🧮 <b>Result:</b> {format_num(val)}"
    except ZeroDivisionError:
        return "❌ <b>Error:</b> Division by zero"
    except Exception as e:
        logger.warning(f"[CALC] Direct math eval failed for '{clean_text}': {e}")
        return "❌ <b>Invalid expression</b>"
