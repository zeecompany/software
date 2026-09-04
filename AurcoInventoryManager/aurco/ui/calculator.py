"""Small built-in calculator — always one keystroke away (Ctrl+Alt+C / F4).

Deliberately warehouse-flavoured rather than a plain desktop calculator:

  ·  keyboard-first: type the whole expression and press Enter
  ·  a real expression engine (2+3*4, brackets, %, powers) — not click-only
  ·  a running tape so you can see how a figure was reached
  ·  memory keys, and Copy so the result can go straight into a quantity cell
  ·  quick VAT / discount / unit-price helpers used every day in the store
"""
from __future__ import annotations

import ast
import math
import operator

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QDialog, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QPushButton, QVBoxLayout, QWidget)

from . import widgets as W

# ------------------------------------------------------------ safe evaluator
_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv, ast.USub: operator.neg, ast.UAdd: operator.pos,
}
_FUNCS = {
    "sqrt": math.sqrt, "abs": abs, "round": round, "min": min, "max": max,
    "floor": math.floor, "ceil": math.ceil, "log": math.log10, "ln": math.log,
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "pow": pow,
}
_CONSTS = {"pi": math.pi, "e": math.e}


def evaluate(expr: str) -> float:
    """Evaluate an arithmetic expression safely.

    Uses an AST walk with a whitelist — never `eval` — so a typo or a pasted
    string can't execute anything.
    """
    import re as _re
    text = (expr or "").strip().replace("×", "*").replace("÷", "/").replace("^", "**")
    # Strip thousands separators (1,234.5) but keep commas that separate
    # function arguments, e.g. round(7.777, 1) or max(3, 9, 2).
    text = _re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)
    if not text:
        raise ValueError("empty")
    # trailing "%" means "percent of the preceding value", e.g. 200+15%
    tree = ast.parse(text, mode="eval")

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                return float(node.value)
            raise ValueError("only numbers are allowed")
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](walk(node.operand))
        if isinstance(node, ast.Name):
            if node.id in _CONSTS:
                return _CONSTS[node.id]
            raise ValueError(f"unknown name '{node.id}'")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
                raise ValueError("unknown function")
            args = [walk(a) for a in node.args]
            # every literal is parsed as a float, but round()/floor-style
            # functions need a real int for their second argument
            if node.func.id == "round" and len(args) > 1:
                args[1] = int(args[1])
            try:
                return _FUNCS[node.func.id](*args)
            except ZeroDivisionError:
                raise
            except (TypeError, ValueError) as exc:
                raise ValueError(f"bad arguments to {node.func.id}(): {exc}") from exc
        if isinstance(node, (ast.Tuple, ast.List)):
            return [walk(e) for e in node.elts]
        raise ValueError("unsupported expression")

    val = walk(tree)
    if isinstance(val, (list, tuple)):
        raise ValueError("unsupported expression")
    return float(val)


def _pct(expr: str) -> str:
    """Rewrite 'a+15%' / 'a-15%' / 'a*15%' into plain arithmetic."""
    import re
    text = expr.replace(" ", "")
    m = re.fullmatch(r"(.+?)([+\-])([\d.]+)%", text)
    if m:
        base, sign, p = m.group(1), m.group(2), m.group(3)
        return f"({base})*(1{sign}{p}/100)"
    m = re.fullmatch(r"(.+?)\*([\d.]+)%", text)
    if m:
        return f"({m.group(1)})*{m.group(2)}/100"
    m = re.fullmatch(r"([\d.]+)%", text)
    if m:
        return f"{m.group(1)}/100"
    return expr


class CalculatorDialog(QDialog):
    """Compact calculator with a tape. Non-modal so it can sit beside a form."""

    def __init__(self, db=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Calculator")
        self.setModal(False)
        self.resize(430, 560)
        self.memory = 0.0
        self._last = 0.0

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(8)

        self.entry = QLineEdit()
        self.entry.setPlaceholderText("Type an expression and press Enter — e.g. 12*8+150")
        self.entry.setAlignment(Qt.AlignRight)
        f = self.entry.font()
        f.setPointSize(16)
        f.setBold(True)
        self.entry.setFont(f)
        self.entry.setMinimumHeight(46)
        self.entry.returnPressed.connect(self.compute)
        v.addWidget(self.entry)

        self.result = QLabel("0")
        self.result.setAlignment(Qt.AlignRight)
        rf = self.result.font()
        rf.setPointSize(20)
        rf.setBold(True)
        self.result.setFont(rf)
        self.result.setStyleSheet(f"color:{W.NAVY}; padding:2px 6px;")
        v.addWidget(self.result)

        self.hint = QLabel("Percent: 200+15%  ·  Functions: sqrt round min max  ·  "
                           "Ctrl+C copies the result")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(f"color:{W.MUTED}; font-size:11px;")
        v.addWidget(self.hint)

        grid = QGridLayout()
        grid.setSpacing(5)
        keys = [
            ("MC", 0, 0), ("MR", 0, 1), ("M+", 0, 2), ("M-", 0, 3), ("C", 0, 4),
            ("7", 1, 0), ("8", 1, 1), ("9", 1, 2), ("÷", 1, 3), ("⌫", 1, 4),
            ("4", 2, 0), ("5", 2, 1), ("6", 2, 2), ("×", 2, 3), ("(", 2, 4),
            ("1", 3, 0), ("2", 3, 1), ("3", 3, 2), ("−", 3, 3), (")", 3, 4),
            ("0", 4, 0), (".", 4, 1), ("%", 4, 2), ("+", 4, 3), ("=", 4, 4),
        ]
        for label, r, c in keys:
            b = QPushButton(label)
            b.setMinimumHeight(38)
            b.setCursor(Qt.PointingHandCursor)
            if label == "=":
                b.setObjectName("Primary")
            elif label in ("C", "⌫", "MC", "MR", "M+", "M-"):
                b.setObjectName("Accent")
            b.clicked.connect(lambda _=False, k=label: self.press(k))
            grid.addWidget(b, r, c)
        v.addLayout(grid)

        quick = QHBoxLayout()
        for label, tip, fn in (
                ("+VAT 15%", "Add 15% VAT to the result", lambda: self._apply("*1.15")),
                ("−VAT 15%", "Remove 15% VAT from the result",
                 lambda: self._apply("/1.15")),
                ("÷ Qty", "Divide the result by a quantity", self._per_unit),
                ("½", "Half", lambda: self._apply("/2")),
                ("×2", "Double", lambda: self._apply("*2"))):
            b = W.button(label, slot=fn, tip=tip)
            quick.addWidget(b)
        v.addLayout(quick)

        v.addWidget(QLabel("Tape  —  double-click a line to reuse it"))
        self.tape = QListWidget()
        self.tape.setMaximumHeight(140)
        self.tape.itemDoubleClicked.connect(
            lambda it: self.entry.setText(it.text().split("=")[0].strip()))
        v.addWidget(self.tape, 1)

        bar = QHBoxLayout()
        bar.addWidget(W.button("📋  Copy Result", "Primary", self.copy_result,
                               tip="Copy the figure to the clipboard"))
        bar.addWidget(W.button("🧹  Clear Tape", slot=self.tape.clear))
        bar.addStretch(1)
        bar.addWidget(W.button("Close", slot=self.close))
        v.addLayout(bar)

        QShortcut(QKeySequence("Escape"), self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+C"), self, activated=self.copy_result)
        self.entry.setFocus()

    # ------------------------------------------------------------- behaviour
    def press(self, key: str):
        if key == "C":
            self.entry.clear()
            self.result.setText("0")
            return
        if key == "⌫":
            self.entry.setText(self.entry.text()[:-1])
            return
        if key == "=":
            self.compute()
            return
        if key == "MC":
            self.memory = 0.0
            W.toast(self, "Memory cleared.")
            return
        if key == "MR":
            self.entry.insert(self._fmt(self.memory))
            return
        if key in ("M+", "M-"):
            self.compute(silent=True)
            self.memory += self._last if key == "M+" else -self._last
            W.toast(self, f"Memory = {self._fmt(self.memory)}")
            return
        self.entry.insert({"×": "*", "÷": "/", "−": "-"}.get(key, key))
        self.entry.setFocus()

    def _apply(self, suffix: str):
        """Continue calculating from the current result."""
        self.compute(silent=True)
        self.entry.setText(f"{self._fmt(self._last)}{suffix}")
        self.compute()

    def _per_unit(self):
        from PySide6.QtWidgets import QInputDialog
        self.compute(silent=True)
        qty, ok = QInputDialog.getDouble(self, "Divide by quantity", "Quantity:",
                                         1.0, 0.0001, 1e9, 4)
        if ok:
            self.entry.setText(f"{self._fmt(self._last)}/{qty:g}")
            self.compute()

    @staticmethod
    def _fmt(v: float) -> str:
        if v == int(v) and abs(v) < 1e15:
            return str(int(v))
        return f"{v:.10g}"

    def compute(self, silent: bool = False):
        raw = self.entry.text().strip()
        if not raw:
            return
        try:
            val = evaluate(_pct(raw))
        except ZeroDivisionError:
            self.result.setText("Cannot divide by zero")
            self.result.setStyleSheet(f"color:{W.RED}; padding:2px 6px;")
            return
        except Exception:
            self.result.setText("Invalid expression")
            self.result.setStyleSheet(f"color:{W.RED}; padding:2px 6px;")
            return
        self._last = val
        self.result.setStyleSheet(f"color:{W.NAVY}; padding:2px 6px;")
        self.result.setText(f"{val:,.10g}")
        if not silent:
            self.tape.insertItem(0, f"{raw}  =  {val:,.10g}")
            if self.tape.count() > 200:
                self.tape.takeItem(200)

    def copy_result(self):
        QApplication.clipboard().setText(self._fmt(self._last))
        W.toast(self, f"Copied {self._fmt(self._last)} to the clipboard.")
