"""
guiNamingLinter.py - GUI Code Quality Linter

This linter enforces project-specific guidelines for Python GUI development:
- Function formatting (blank line after def if >4 statements)
- Widget naming conventions (Tkinter and Qt/PySide6)
- Constant and variable naming rules
- Logging message formatting
- Misspelling detection (e.g., 'iCloud')
"""

import ast
import os
import re

# Naming rules for Tkinter GUI elements and handlers
namingRules = {
    "Button": r"^btn[A-Z]\w+",
    "Entry": r"^entry[A-Z]\w+",
    "Label": r"^lbl[A-Z]\w+",
    "Frame": r"^frm[A-Z]\w+",
    "Text": r"^txt[A-Z]\w+",
    "Listbox": r"^lst[A-Z]\w+",
    "Checkbutton": r"^chk[A-Z]\w+",
    "Radiobutton": r"^rdo[A-Z]\w+",
    "Combobox": r"^cmb[A-Z]\w+",
    "Handler": r"^on[A-Z]\w+",
    "Constant": r"^[A-Z_]+$",
    "Class": r"^[A-Z][a-zA-Z0-9]*$",
}

# Qt widget types that should use snake_case (no prefix requirement)
qtWidgetTypes = {
    "QPushButton",
    "QToolButton",
    "QLabel",
    "QLineEdit",
    "QTextEdit",
    "QPlainTextEdit",
    "QListWidget",
    "QListView",
    "QComboBox",
    "QCheckBox",
    "QRadioButton",
    "QWidget",
    "QFrame",
    "QGroupBox",
    "QTableWidget",
    "QTableView",
    "QTreeWidget",
    "QTreeView",
    "QSpinBox",
    "QDoubleSpinBox",
    "QSlider",
    "QProgressBar",
    "QTabWidget",
    "QScrollArea",
    "QSplitter",
    "QStackedWidget",
    "QSpacerItem",
    "QHBoxLayout",
    "QVBoxLayout",
    "QGridLayout",
    "QFormLayout",
}

# Allow patterns or names to bypass class rule
classNameExceptions = {"iCloudSyncFrame"}
classNamePatterns = [r"^iCloud[A-Z]\w*"]

widgetClasses = set(namingRules.keys()) - {"Handler", "Constant", "Class"}


def detectFramework(fileContent: str) -> str:
    """
    Detect which GUI framework is used in the file.

    Returns:
        'tkinter' for Tkinter projects
        'qt' for Qt/PySide6/PyQt5/PyQt6 projects
        None for files without recognized GUI framework
    """
    if "import tkinter" in fileContent or "from tkinter" in fileContent:
        return "tkinter"
    elif any(
        keyword in fileContent
        for keyword in ["from PySide6", "from PyQt5", "from PyQt6"]
    ):
        return "qt"
    return None


def isSnakeCase(name: str) -> bool:
    """
    Check if name follows snake_case convention.

    Allows lowercase letters, numbers, and underscores.
    Can start with underscore (for private members).
    Allows single-character names (e.g., 'x', 'i').
    """
    return bool(re.match(r"^_?[a-z]([a-z0-9_]*)?$", name))


class GuiNamingVisitor(ast.NodeVisitor):
    def __init__(self, lines: list[str], framework: str = None):
        self.lines = lines
        self.framework = framework
        self.violations = []
        self.packCalls = 0
        self.gridCalls = 0

    def visit_Assign(self, node):
        # Handle both simple names (varName = ...) and attributes (self.varName = ...)
        if len(node.targets) > 0:
            target = node.targets[0]
            varName = None

            if isinstance(target, ast.Name):
                varName = target.id
            elif isinstance(target, ast.Attribute):
                varName = target.attr

            if varName:
                # Check for horizontal/vertical naming (both Tkinter and Qt)
                hasHorizontalVerticalViolation = False
                if varName.startswith("horizontal"):
                    # Suggest using hrz prefix instead
                    suggested = (
                        "hrz" + varName[10:]
                    )  # Replace 'horizontal' (10 chars) with 'hrz'
                    self.violations.append(
                        (
                            varName,
                            f'Horizontal widget (use "{suggested}" instead)',
                            node.lineno,
                        )
                    )
                    hasHorizontalVerticalViolation = True
                elif varName.startswith("vertical"):
                    # Suggest using vrt prefix instead
                    suggested = (
                        "vrt" + varName[8:]
                    )  # Replace 'vertical' (8 chars) with 'vrt'
                    self.violations.append(
                        (
                            varName,
                            f'Vertical widget (use "{suggested}" instead)',
                            node.lineno,
                        )
                    )
                    hasHorizontalVerticalViolation = True

                # Check for constants (only for module-level simple names)
                # Exclude Python directives (dunder names like __version__, __all__, __init__, etc.)
                if isinstance(node.value, (ast.Constant, ast.List, ast.Tuple)):
                    if isinstance(target, ast.Name) and isinstance(
                        getattr(node, "parent", None), ast.Module
                    ):
                        # Skip Python directives (dunder names)
                        if not (varName.startswith("__") and varName.endswith("__")):
                            if not re.match(namingRules["Constant"], varName):
                                self.violations.append(
                                    (varName, "Constant", node.lineno)
                                )

                # Check for widget naming conventions (skip if already reported horizontal/vertical violation)
                if not hasHorizontalVerticalViolation and isinstance(
                    node.value, ast.Call
                ):
                    try:
                        # Get widget type from the call
                        widgetType = None
                        if isinstance(node.value.func, ast.Attribute):
                            widgetType = node.value.func.attr
                        elif isinstance(node.value.func, ast.Name):
                            widgetType = node.value.func.id

                        if widgetType:
                            # Check Tkinter widgets (prefix-based naming)
                            if (
                                self.framework == "tkinter"
                                and widgetType in widgetClasses
                            ):
                                pattern = namingRules[widgetType]
                                if not re.match(pattern, varName):
                                    self.violations.append(
                                        (varName, widgetType, node.lineno)
                                    )

                            # Check Qt horizontal/vertical widgets (hrz/vrt prefix for QSpacerItem)
                            elif self.framework == "qt" and widgetType == "QSpacerItem":
                                # Check if variable name starts with horizontal or vertical
                                is_horizontal = varName.startswith("horizontal")
                                is_vertical = varName.startswith("vertical")
                                if is_horizontal or is_vertical:
                                    expected_prefix = "hrz" if is_horizontal else "vrt"
                                    old_prefix = (
                                        "horizontal" if is_horizontal else "vertical"
                                    )
                                    suggested_name = (
                                        expected_prefix + varName[len(old_prefix) :]
                                    )
                                    self.violations.append(
                                        (
                                            varName,
                                            f"Qt horizontal/vertical widget (use {expected_prefix} prefix, e.g., {suggested_name})",
                                            node.lineno,
                                        )
                                    )

                            # Check Qt widgets (snake_case naming)
                            elif self.framework == "qt" and widgetType in qtWidgetTypes:
                                if not isSnakeCase(varName):
                                    self.violations.append(
                                        (
                                            varName,
                                            f"Qt {widgetType} (snake_case)",
                                            node.lineno,
                                        )
                                    )
                    except AttributeError:
                        pass

        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        """Check for a blank line immediately after the ``def`` line."""

        if len(node.body) > 4 and node.lineno < len(self.lines):
            # Check if first statement is a docstring
            first_stmt = node.body[0]
            is_docstring = (
                isinstance(first_stmt, ast.Expr)
                and isinstance(first_stmt.value, ast.Constant)
                and isinstance(first_stmt.value.value, str)
            )

            # Skip blank line requirement if function starts with a docstring
            # (per PEP 257, docstrings should come immediately after def)
            if not is_docstring:
                # ``lineno`` is 1-indexed; check the next line in the file
                line_after_def = self.lines[node.lineno].strip()
                if line_after_def:
                    self.violations.append(
                        (
                            node.name,
                            "Function spacing (no blank line after def)",
                            node.lineno,
                        )
                    )

        self.generic_visit(node)

    def visit_ClassDef(self, node):
        isExplicitlyAllowed = node.name in classNameExceptions
        isPatternAllowed = any(re.match(pat, node.name) for pat in classNamePatterns)
        if not (isExplicitlyAllowed or isPatternAllowed):
            if not re.match(namingRules["Class"], node.name):
                self.violations.append((node.name, "Class", node.lineno))
        self.generic_visit(node)

    def visit_Expr(self, node):
        if isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Attribute):
                if func.attr == "pack":
                    self.packCalls += 1
                elif func.attr == "grid":
                    self.gridCalls += 1

                if func.attr in {"info", "warning", "error"}:
                    if node.value.args and isinstance(node.value.args[0], ast.Constant):
                        msg = node.value.args[0].value
                        if func.attr in {"info", "warning"}:
                            if not msg.islower() and not re.match(
                                r"[.]{3}.*|.*[.]{3}|[.]{3}.*:.*", msg
                            ):
                                self.violations.append(
                                    (msg, f"Logging ({func.attr})", node.lineno)
                                )
                        elif func.attr == "error":
                            if msg != msg.capitalize():
                                self.violations.append(
                                    (msg, "Logging (error)", node.lineno)
                                )

        if isinstance(node.value, ast.Constant):
            val = node.value.value
            if isinstance(val, str):
                icloudMatches = re.findall(r"\b[iI][cC]loud\b", val)
                for match in icloudMatches:
                    if match != "iCloud":
                        self.violations.append(
                            (match, "Spelling (iCloud)", node.lineno)
                        )

        self.generic_visit(node)


def annotateParents(tree):
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node


def checkFile(filepath):

    with open(filepath, "r", encoding="utf-8") as file:
        text = file.read()

    # Detect GUI framework from file content
    framework = detectFramework(text)

    lines = text.splitlines()
    tree = ast.parse(text, filename=filepath)
    annotateParents(tree)
    visitor = GuiNamingVisitor(lines, framework=framework)
    visitor.visit(tree)

    # Only check for grid/pack usage in Tkinter files
    if framework == "tkinter" and visitor.gridCalls > 0 and visitor.packCalls == 0:
        visitor.violations.append(("layout", "Use 'pack()' instead of 'grid()'", 0))

    return visitor.violations


def lintGuiNaming(directory):

    print(f"\nChecking GUI naming in: {directory}\n" + "-" * 50)
    for root, _, files in os.walk(directory):
        for filename in files:
            if filename.endswith(".py"):
                path = os.path.join(root, filename)
                violations = checkFile(path)
                if violations:
                    print(f"\n{filename}:")
                    for name, ruleType, lineno in violations:
                        print(
                            f"  Line {lineno}: '{name}' should follow naming rule for {ruleType}."
                        )
                else:
                    print(f"{filename}: OK")


def lintFile(filepath):
    print(f"\nLinting: {filepath}\n" + "-" * 50)

    try:
        violations = checkFile(filepath)
        if violations:
            for name, ruleType, lineno in violations:
                print(
                    f"  Line {lineno}: '{name}' should follow naming rule for {ruleType}."
                )
        else:
            print("  OK")
    except FileNotFoundError:
        print(f"  Error: File '{filepath}' does not exist.")
    except Exception as e:
        print(f"  Error: Failed to lint file: {e}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        lintFile(sys.argv[1])
    else:
        print("Usage: python guiNamingLinter.py <script.py>")
