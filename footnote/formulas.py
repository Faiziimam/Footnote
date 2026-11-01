"""Custom computed fields. A formula is a small, SAFE expression (no code execution): arithmetic, comparisons,
if/else, and a short list of functions.   e.g.   days_since(started)      est_left * 1.2      "Late" if is_overdue else "OK"
"""
import ast
import datetime as dt
import operator as op

BIN = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv, ast.FloorDiv: op.floordiv, ast.Mod: op.mod, ast.Pow: op.pow}
CMP = {ast.Eq: op.eq, ast.NotEq: op.ne, ast.Lt: op.lt, ast.LtE: op.le, ast.Gt: op.gt, ast.GtE: op.ge}


class FormulaError(Exception):
    pass


def _date(v):
    if not v:
        raise FormulaError("empty date")
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        raise FormulaError(f"not a date: {v!r}")


def days_since(d, today=None):
    return ((today or dt.date.today()) - _date(d)).days


def days_until(d, today=None):
    return (_date(d) - (today or dt.date.today())).days


def days_between(a, b):
    return (_date(b) - _date(a)).days


FUNCS = {"days_since": days_since, "days_until": days_until, "days_between": days_between, "round": round, "abs": abs,
         "min": min, "max": max, "len": len, "int": int, "float": float, "str": str, "sum": sum,
         "iif": lambda c, a, b: a if c else b}
MAX_NODES = 200


def check(expr):
    """Validate without evaluating. Raises FormulaError with a plain message."""
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError:
        raise FormulaError("I couldn't read that formula. Example: days_since(started)")
    n = 0
    for node in ast.walk(tree):
        n += 1
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            r = node.right
            if not (isinstance(r, ast.Constant) and isinstance(r.value, (int, float)) and abs(r.value) <= 10):
                raise FormulaError("powers are limited to small fixed exponents (up to 10)")
        if n > MAX_NODES:
            raise FormulaError("formula is too long")
        if isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Compare, ast.BoolOp, ast.IfExp, ast.Constant,
                             ast.Name, ast.Load, ast.Call, ast.List, ast.Tuple, ast.And, ast.Or, ast.Not, ast.USub, ast.UAdd,
                             ast.operator, ast.cmpop)):
            if isinstance(node, ast.Call) and not (isinstance(node.func, ast.Name) and node.func.id in FUNCS):
                raise FormulaError("only these functions are allowed: " + ", ".join(sorted(FUNCS)))
            if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float, str, bool, type(None))):
                raise FormulaError("unsupported value")
            continue
        raise FormulaError(f"“{type(node).__name__}” isn't allowed in formulas (only arithmetic, comparisons, if/else and the listed functions)")
    return tree


def evaluate(expr, env):
    tree = check(expr)

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.Name):
            if n.id in env:
                return env[n.id]
            if n.id in ("True", "False", "None"):
                return {"True": True, "False": False, "None": None}[n.id]
            raise FormulaError(f"unknown field “{n.id}”")
        if isinstance(n, ast.BinOp):
            a, b = ev(n.left), ev(n.right)
            if a in ("", None) or b in ("", None):
                raise FormulaError("a field used here is empty")
            if type(n.op) is ast.Pow and abs(b) > 10:
                raise FormulaError("exponent too large")
            return BIN[type(n.op)](a, b)
        if isinstance(n, ast.UnaryOp):
            v = ev(n.operand)
            return (not v) if isinstance(n.op, ast.Not) else (-v if isinstance(n.op, ast.USub) else +v)
        if isinstance(n, ast.Compare):
            left = ev(n.left)
            for o, c in zip(n.ops, n.comparators):
                right = ev(c)
                if not CMP[type(o)](left, right):
                    return False
                left = right
            return True
        if isinstance(n, ast.BoolOp):
            vals = [ev(v) for v in n.values]
            return all(vals) if isinstance(n.op, ast.And) else any(vals)
        if isinstance(n, ast.IfExp):
            return ev(n.body) if ev(n.test) else ev(n.orelse)
        if isinstance(n, (ast.List, ast.Tuple)):
            return [ev(e) for e in n.elts]
        if isinstance(n, ast.Call):
            return FUNCS[n.func.id](*[ev(a) for a in n.args])
        raise FormulaError("unsupported")
    try:
        v = ev(tree)
    except FormulaError:
        raise
    except ZeroDivisionError:
        raise FormulaError("division by zero")
    except (TypeError, ValueError, OverflowError) as e:
        raise FormulaError(str(e))
    return round(v, 2) if isinstance(v, float) else v


def task_env(fm, children=(), waiting=()):
    today = dt.date.today()
    env = dict(fm)
    env.update({"today": today.isoformat(), "n_children": len(children), "n_blockers": len(waiting),
                "children_done": sum(1 for c in children if c["status"] == "done")})
    due = fm.get("due")
    env["is_overdue"] = bool(due and fm.get("status") != "done" and str(due) < today.isoformat())
    env["age_days"] = days_since(fm["created"]) if fm.get("created") else 0
    est = fm.get("estimate") or 0
    env["est_left"] = 0 if fm.get("status") == "done" else est
    for k in ("estimate", "priority", "owner", "started", "done", "due", "cycle_days"):
        env.setdefault(k, "" if k not in ("estimate",) else 0)
    return env
