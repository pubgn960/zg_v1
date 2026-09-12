"""
Safe mathematical evaluator and Accounting Calculator Engine for Telegram Email Image Delivery Bot.
Provides AST-whitelist arithmetic evaluation, string number formatting, and math expression detection.
Exclusively handles math evaluation without database queries or eval().
"""

import ast
import re
import logging
from typing import Union, Tuple, Optional

logger = logging.getLogger(__name__)

# Maximum allowed expression length to prevent DoS
MAX_EXPR_LENGTH = 200
# Maximum allowed power exponent
MAX_EXPONENT = 1000
# Maximum allowed AST node count
MAX_AST_NODES = 50


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

    if isinstance(result, float) and result.is_integer():
        return int(result)
    return result


def format_num(val: Optional[Union[int, float]]) -> str:
    """Formats numeric value for display without unnecessary trailing zeros."""
    if val is None:
        return "0"
    if isinstance(val, float):
        if val.is_integer():
            return str(int(val))
        return f"{val:g}"
    return str(val)


def is_math_expression(text: str) -> bool:
    """
    Determines if text string looks like a numeric value or arithmetic expression.
    Checks for digits and basic arithmetic operators while excluding words/emails.
    """
    clean = text.strip()
    if not clean:
        return False
    # Exclude text containing alphabetic letters or underscore
    if re.search(r'[a-zA-Z_]', clean):
        return False
    # Must contain at least one digit
    return bool(re.search(r'\d', clean))


def evaluate_math_expression(text: str) -> Tuple[bool, Optional[Union[int, float]]]:
    """
    Evaluates math expression safely.
    Returns (is_valid, numeric_result_or_None).
    """
    if not is_math_expression(text):
        return False, None

    try:
        res = safe_eval(text)
        return True, res
    except Exception as e:
        logger.debug(f"[CALC] Safe math eval failed for '{text}': {e}")
        return False, None
