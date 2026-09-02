# deployed from Glawster/organiseMyProjects release 0.5 -- do not edit directly
"""
guiNamingLinter.py - GUI Code Quality Linter

This linter enforces project-specific guidelines for Python GUI development:
- Module-level function spacing
- Widget naming conventions (Tkinter and Qt/PySide6)
- Constant and variable naming rules
- Logging message formatting
- Misspelling detection (e.g., 'iCloud')
- Function naming using domainAction style
"""

import ast
import os
import re

## constants

DOMAIN_ACTION_PATTERN = r"^_?[a-z]+[A-Z][a-zA-Z0-9]*$"

FUNCTION_NAME_EXCEPTIONS = {
    "main",
    # AST visitor callback names must match ast.NodeVisitor conventions.
    "visit_Assign",
    "visit_ClassDef",
    "visit_Expr",
    "visit_FunctionDef",
    "visit_AsyncFunctionDef",
}

# These names are contracts imposed by Python or a framework. Renaming an
# override to satisfy a project convention would break polymorphic dispatch.
FRAMEWORK_METHOD_EXCEPTIONS = {
    "clear",  # Qt widget override
    "emit",  # logging.Handler
    "process",  # logging.LoggerAdapter
}

LOGGING_METHODS = {
    "action",
    "debug",
    "doing",
    "done",
    "error",
    "info",
    "multiline",
    "value",
    "warning",
}

NAMING_RULES = {
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
    "Class": r"^_?[A-Z][a-zA-Z0-9]*$",
}

QT_WIDGET_TYPES = {
    "QCheckBox",
    "QComboBox",
    "QDoubleSpinBox",
    "QFormLayout",
    "QFrame",
    "QGridLayout",
    "QGroupBox",
    "QHBoxLayout",
    "QLabel",
    "QLineEdit",
    "QListView",
    "QListWidget",
    "QPlainTextEdit",
    "QProgressBar",
    "QPushButton",
    "QRadioButton",
    "QScrollArea",
    "QSlider",
    "QSpacerItem",
    "QSpinBox",
    "QSplitter",
    "QStackedWidget",
    "QTabWidget",
    "QTableView",
    "QTableWidget",
    "QTextEdit",
    "QToolButton",
    "QTreeView",
    "QTreeWidget",
    "QVBoxLayout",
    "QWidget",
}

CLASS_NAME_EXCEPTIONS = {"iCloudSyncFrame"}
CLASS_NAME_PATTERNS = [r"^iCloud[A-Z]\w*"]

WIDGET_CLASSES = set(NAMING_RULES.keys()) - {"Handler", "Constant", "Class"}


## framework


def frameworkDetect(fileContent: str) -> str | None:
    """
    Detect which GUI framework is used in the file.

    Returns:
        tkinter for Tkinter projects
        qt for Qt/PySide6/PyQt5/PyQt6 projects
        None for files without recognized GUI framework
    """
    if "import tkinter" in fileContent or "from tkinter" in fileContent:
        return "tkinter"

    qtKeywords = ["from PySide6", "from PyQt5", "from PyQt6"]
    if any(keyword in fileContent for keyword in qtKeywords):
        return "qt"

    return None


## name


def nameIsSnakeCase(name: str) -> bool:
    """
    Check if name follows snake_case convention.

    Allows lowercase letters, numbers, and underscores.
    Can start with underscore for private members.
    Allows single-character names.
    """
    return bool(re.match(r"^_?[a-z]([a-z0-9_]*)?$", name))


## ast


def astAnnotateParents(tree: ast.AST) -> None:
    """Attach parent references to child AST nodes."""
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node


class GuiNamingVisitor(ast.NodeVisitor):

    ## lifecycle

    def __init__(
        self,
        lines: list[str],
        framework: str | None = None,
        isTestFile: bool = False,
    ):
        self.lines = lines
        self.framework = framework
        self.isTestFile = isTestFile
        self.violations = []
        self.packCalls = 0
        self.gridCalls = 0

    ## ast visitor callbacks

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
                self.widgetCheckHorizontalVerticalName(varName, node, target)
                self.widgetCheckConstantName(varName, node, target)
                self.widgetCheckName(varName, node)

        self.generic_visit(node)

    def visit_ClassDef(self, node):
        if self.isTestFile and re.match(r"^_[A-Z][a-zA-Z0-9]*$", node.name):
            self.generic_visit(node)
            return

        isExplicitlyAllowed = node.name in CLASS_NAME_EXCEPTIONS
        isPatternAllowed = any(
            re.match(pattern, node.name) for pattern in CLASS_NAME_PATTERNS
        )

        if not (isExplicitlyAllowed or isPatternAllowed):
            if not re.match(NAMING_RULES["Class"], node.name):
                self.violations.append((node.name, "Class", node.lineno))

        self.generic_visit(node)

    def visit_Expr(self, node):
        self.loggingCheckExpression(node)
        self.spellingCheckExpression(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        """Check function spacing and domainAction naming."""
        self.functionCheckName(node)
        self.functionCheckSpacing(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        """Apply function rules consistently to asynchronous functions."""
        self.visit_FunctionDef(node)

    ## function

    def functionCheckName(self, node) -> None:
        """Check function names use the domainAction pattern."""
        if self.functionIsNamingExempt(node):
            return

        if not re.match(DOMAIN_ACTION_PATTERN, node.name):
            self.violations.append(
                (node.name, "Function name (domainAction)", node.lineno)
            )

    def functionIsNamingExempt(self, node) -> bool:
        """Return whether Python, a framework, or pytest owns the function name."""
        if node.name.startswith("__") and node.name.endswith("__"):
            return True

        if node.name in FUNCTION_NAME_EXCEPTIONS:
            return True

        if any(
            isinstance(item, ast.Name) and item.id == "property"
            for item in node.decorator_list
        ):
            return True

        if isinstance(getattr(node, "parent", None), ast.ClassDef):
            if node.name in LOGGING_METHODS:
                return True
            if node.name in FRAMEWORK_METHOD_EXCEPTIONS:
                return True

        if not self.isTestFile:
            return False

        # Pytest fixture names are dependency-injection keys and commonly use
        # snake_case. Decorators may be @fixture, @pytest.fixture, or calls of
        # either form.
        if any(self.functionDecoratorIsFixture(item) for item in node.decorator_list):
            return True

        # Private helpers and non-test module helpers in test modules follow
        # normal Python helper conventions rather than production domainAction.
        if node.name.startswith("_"):
            return True
        if isinstance(getattr(node, "parent", None), ast.Module):
            return not node.name.startswith("test")

        return False

    def functionDecoratorIsFixture(self, decorator) -> bool:
        """Recognize common pytest fixture decorator forms."""
        if isinstance(decorator, ast.Call):
            decorator = decorator.func
        if isinstance(decorator, ast.Name):
            return decorator.id == "fixture"
        if isinstance(decorator, ast.Attribute):
            return decorator.attr == "fixture"
        return False

    def functionCheckSpacing(self, node) -> None:
        """Check that module-level functions have two preceding blank lines."""
        if not isinstance(getattr(node, "parent", None), ast.Module):
            return

        startLine = min([node.lineno, *(item.lineno for item in node.decorator_list)])
        if startLine <= 1:
            return

        precedingLines = self.lines[max(0, startLine - 3) : startLine - 1]
        blankLineCount = sum(not line.strip() for line in precedingLines)
        if blankLineCount < 2:
            self.violations.append(
                (
                    node.name,
                    "Function spacing (two blank lines before top-level def)",
                    node.lineno,
                )
            )

    ## logging

    def loggingCheckExpression(self, node) -> None:
        """Check project logging message formatting."""
        if not isinstance(node.value, ast.Call):
            return

        func = node.value.func
        if not isinstance(func, ast.Attribute):
            return

        if func.attr == "pack":
            self.packCalls += 1
            return

        if func.attr == "grid":
            self.gridCalls += 1
            return

        isLoggerCall = isinstance(func.value, ast.Name) and func.value.id == "logger"

        if not isLoggerCall:
            return

        if func.attr not in LOGGING_METHODS:
            return

        if not node.value.args:
            return

        messageNode = node.value.args[0]
        variableCount = len(node.value.args) - 1

        if variableCount > 0 and func.attr not in {"info", "value"}:
            self.violations.append(
                (
                    func.attr,
                    "Logging variables (only logger.info/logger.value accept variables)",
                    node.lineno,
                )
            )

        if func.attr == "value" and variableCount != 1:
            self.violations.append(
                (
                    "logger.value",
                    "Logging variables (logger.value requires exactly one variable)",
                    node.lineno,
                )
            )
        if func.attr == "info" and variableCount == 1:
            self.violations.append(
                (
                    "logger.info",
                    "Logging variables (use logger.value for a single variable)",
                    node.lineno,
                )
            )

        if func.attr == "value" and variableCount < 1:
            self.violations.append(
                (
                    "logger.value",
                    "Logging variables (logger.value requires a value argument)",
                    node.lineno,
                )
            )

        if not isinstance(messageNode, ast.Constant):
            return

        msg = messageNode.value
        if not isinstance(msg, str):
            return

        if "..." in msg:
            self.violations.append((msg, "Logging (ellipsis misuse)", node.lineno))

        if func.attr in {"info", "warning"} and not msg.islower():
            self.violations.append((msg, f"Logging ({func.attr})", node.lineno))

        elif func.attr == "error" and msg != msg.capitalize():
            self.violations.append((msg, "Logging (error)", node.lineno))

    ## spelling

    def spellingCheckExpression(self, node) -> None:
        """Check common spelling and capitalisation mistakes."""
        if not isinstance(node.value, ast.Constant):
            return

        value = node.value.value
        if not isinstance(value, str):
            return

        icloudMatches = re.findall(r"\b[iI][cC]loud\b", value)
        for match in icloudMatches:
            if match != "iCloud":
                self.violations.append((match, "Spelling (iCloud)", node.lineno))

    ## widget

    def widgetCheckConstantName(self, varName: str, node, target) -> None:
        """Check module-level constants use uppercase names."""
        if not isinstance(node.value, (ast.Constant, ast.List, ast.Tuple)):
            return

        if not isinstance(target, ast.Name):
            return

        if not isinstance(getattr(node, "parent", None), ast.Module):
            return

        if varName.startswith("__") and varName.endswith("__"):
            return

        if not re.match(NAMING_RULES["Constant"], varName):
            self.violations.append((varName, "Constant", node.lineno))

    def widgetCheckHorizontalVerticalName(self, varName: str, node, target) -> None:
        """Check horizontal and vertical widget names use hrz/vrt prefixes."""
        del target

        if varName.startswith("horizontal"):
            suggested = "hrz" + varName[10:]
            self.violations.append(
                (varName, f'Horizontal widget (use "{suggested}" instead)', node.lineno)
            )

        elif varName.startswith("vertical"):
            suggested = "vrt" + varName[8:]
            self.violations.append(
                (varName, f'Vertical widget (use "{suggested}" instead)', node.lineno)
            )

    def widgetCheckName(self, varName: str, node) -> None:
        """Check framework-specific widget naming conventions."""
        if not isinstance(node.value, ast.Call):
            return

        # widgetCheckHorizontalVerticalName handles horizontal/vertical prefixes
        if varName.startswith("horizontal") or varName.startswith("vertical"):
            return

        widgetType = self.widgetGetType(node)
        if not widgetType:
            return

        if self.framework == "tkinter" and widgetType in WIDGET_CLASSES:
            pattern = NAMING_RULES[widgetType]
            if not re.match(pattern, varName):
                self.violations.append((varName, widgetType, node.lineno))

        elif self.framework == "qt" and widgetType == "QSpacerItem":
            self.widgetCheckQtSpacerName(varName, node)

        elif self.framework == "qt" and widgetType in QT_WIDGET_TYPES:
            if not nameIsSnakeCase(varName):
                self.violations.append(
                    (varName, f"Qt {widgetType} (snake_case)", node.lineno)
                )

    def widgetCheckQtSpacerName(self, varName: str, node) -> None:
        """Check Qt spacer variables use hrz/vrt prefixes."""
        isHorizontal = varName.startswith("horizontal")
        isVertical = varName.startswith("vertical")

        if not (isHorizontal or isVertical):
            return

        expectedPrefix = "hrz" if isHorizontal else "vrt"
        oldPrefix = "horizontal" if isHorizontal else "vertical"
        suggestedName = expectedPrefix + varName[len(oldPrefix) :]

        self.violations.append(
            (
                varName,
                f"Qt horizontal/vertical widget (use {expectedPrefix} prefix, e.g., {suggestedName})",
                node.lineno,
            )
        )

    def widgetGetType(self, node) -> str | None:
        """Return the widget type from an assignment call."""
        try:
            if isinstance(node.value.func, ast.Attribute):
                return node.value.func.attr

            if isinstance(node.value.func, ast.Name):
                return node.value.func.id

        except AttributeError:
            return None

        return None


## file


def fileCheck(filepath: str) -> list[tuple[str, str, int]]:
    """Check one Python file and return lint violations."""
    with open(filepath, "r", encoding="utf-8") as file:
        text = file.read()

    framework = frameworkDetect(text)

    lines = text.splitlines()
    tree = ast.parse(text, filename=filepath)
    astAnnotateParents(tree)

    filename = os.path.basename(filepath)
    isTestFile = filename.startswith("test_") or "tests" in os.path.normpath(
        filepath
    ).split(os.sep)
    visitor = GuiNamingVisitor(lines, framework=framework, isTestFile=isTestFile)
    visitor.violations.extend(testFileCheck(filepath))

    visitor.visit(tree)

    if framework == "tkinter" and visitor.gridCalls > 0 and visitor.packCalls == 0:
        visitor.violations.append(("layout", "Use 'pack()' instead of 'grid()'", 0))

    return visitor.violations


## test file naming


def testFileCheck(filepath: str) -> list[tuple[str, str, int]]:
    """Check test file naming convention."""
    filename = os.path.basename(filepath)

    if filename.startswith("test_"):
        namePart = filename[5:].split(".")[0]
        if not re.fullmatch(r"[a-z][A-Za-z0-9]*", namePart):
            return [
                (
                    filename,
                    "Test file naming (test_camelCaseName.py)",
                    0,
                )
            ]

    return []


## lint


def lintFile(filepath: str) -> None:
    """Lint a single Python file."""
    print(f"\nLinting: {filepath}\n" + "-" * 50)

    try:
        violations = fileCheck(filepath)
        reportViolations(filepath, violations)
    except FileNotFoundError:
        print(f"  Error: File '{filepath}' does not exist.")
    except Exception as exc:
        print(f"  Error: Failed to lint file: {exc}")


def lintGuiNaming(directory: str) -> None:
    """Lint all Python files below a directory."""
    print(f"\nChecking GUI naming in: {directory}\n" + "-" * 50)

    ignoredDirectories = {
        ".git",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "output",
    }
    for root, directories, files in os.walk(directory):
        directories[:] = [
            item for item in directories if item not in ignoredDirectories
        ]
        for filename in files:
            if filename.endswith(".py"):
                path = os.path.join(root, filename)
                violations = fileCheck(path)
                reportViolations(filename, violations)


## report


def reportViolations(label: str, violations: list[tuple[str, str, int]]) -> None:
    """Print lint violations for a file or OK when none exist."""
    if not violations:
        print(f"{label}: OK")
        return

    print(f"\n{label}:")
    for name, ruleType, lineno in violations:
        print(f"  Line {lineno}: '{name}' should follow naming rule for {ruleType}.")


## main

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        lintFile(sys.argv[1])
    else:
        print("Usage: python guiNamingLinter.py <script.py>")
