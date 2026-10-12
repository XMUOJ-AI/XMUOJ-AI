"""Conservative student text policy; this is not a parser for every programming language."""
import ast
import html
import math
import re
import textwrap
import unicodedata
import warnings


_MATHEMATICS = re.compile(r"\b(?:O|Theta|Omega|[fgh])\([A-Za-z0-9 _+*^/.-]{1,80}\)")
_MATHEMATICAL_LINE = re.compile(
    r"^[ \t]*[A-Za-z_]\w*(?:[ \t]*[-+*/^][ \t]*(?:[A-Za-z_]\w*|\d+(?:\.\d+)?))+[ \t]*$", re.MULTILINE)
_PROSE_EQUALITY = re.compile(
    r"(?:当|若|如果|假设|设|其中|令|\bwhen\b|\bassuming\b|\bgiven\b)\s*"
    r"[A-Za-z_]\w*\s*=\s*(?:-?\d+(?:\.\d+)?|[A-Za-z_]\w*)"
    r"(?:\s*[-+*/^]\s*(?:\d+(?:\.\d+)?|[A-Za-z_]\w*))*"
    r"(?=\s*(?:时|则|[，,.。;；!?？]|$))", re.IGNORECASE)
_PARENTHETICAL = re.compile(
    r"(?<=[A-Za-z])\s+\((?:[A-Z][A-Z0-9]{1,15}|[A-Za-z]+(?:[ -][A-Za-z]+)+)\)(?=\s+[A-Za-z])"
    r"|\b[A-Z]{2,10}\([\u3400-\u9fff、， ]{2,40}\)")
_EXECUTABLE_CALL = re.compile(
    r"\b(?:print|input|raw_input|eval|exec|open|compile|__import__|getattr|setattr|globals|locals)\s*\(", re.IGNORECASE)
_CODE_OR_ENCODING = re.compile(
    r"```|~~~|[{}]|<\s*/?\s*(?:code|pre|script)\b"
    r"|\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\s*\("
    r"|\b(?:int|long|double|float|char|bool|void|const|let|var)\s+[A-Za-z_]\w*\b"
    r"|\$\(|^\s*#!"
    r"|^\s*(?:print|println|puts|echo|printf|read|eval|exec|import|from\s+\S+\s+import)\s+\S"
    r"|^\s*p\s+\S"
    r"|^\s*(?:for|while|if|elif|else|try|except|with|def|class)\b[^\n]*:\s*(?:#.*)?$"
    r"|(?<![<>=!])=(?!=)|:=|=>|\b\w+(?:\+\+|--)"
    r"|#\s*(?:include|define)\b|\b(?:cout|cin)\s*(?:<<|>>)"
    r"|\\(?:[uUx][0-9a-fA-F]{2,}|[0-7]{3}|[nrt])|%[0-9a-fA-F]{2}"
    r"|\bdata:[^\s]+|\b[A-Za-z0-9+/]{48,}={0,2}\b"
    r"|&(?:#[xX]?[0-9a-fA-F]+|[A-Za-z]+);"
    r"|BEGIN [A-Z ]*PRIVATE KEY|(?:api[_-]?key|authorization)\s*[:=]\s*[^\s]{8,}",
    re.IGNORECASE | re.MULTILINE,
)


def _executable_python(text):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(text)
    except SyntaxError:
        return False
    except (ValueError, RecursionError, MemoryError):
        return True
    # Bare names, formulas and natural-language headings are not programs.
    if any(not isinstance(node, ast.Expr) and not (isinstance(node, ast.AnnAssign) and node.value is None) for node in tree.body):
        return True
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # Chinese prose followed by an explanation in parentheses can also parse as a call.
            if not isinstance(node.func, ast.Name) or node.func.id.isascii():
                return True
        elif isinstance(node, (ast.Await, ast.Yield, ast.YieldFrom, ast.NamedExpr, ast.Lambda,
                               ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            return True
    return False


def normalize_text(text):
    # Use the same bounded normalization for code, paths, addresses and credentials.
    for _ in range(4):
        normalized = unicodedata.normalize("NFKC", html.unescape(text))
        if normalized == text:
            break
        text = normalized
    return text


def normalized_texts(value, _depth=0):
    if _depth > 8:
        raise ValueError("Text nesting exceeds policy limit")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Text keys must be strings")
            yield normalize_text(key)
            yield from normalized_texts(item, _depth + 1)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from normalized_texts(item, _depth + 1)
    elif isinstance(value, str):
        yield normalize_text(value)
    elif value is not None and (not isinstance(value, (bool, int, float)) or not math.isfinite(value)):
        raise ValueError("Unsupported text value")


def _unsafe_text(text):
    if any(unicodedata.category(char) in ("Cc", "Cf") and char not in "\n\r\t" for char in text):
        return True
    # These are mathematical notation; actual input/output/evaluation calls are never exempted by prose.
    if _EXECUTABLE_CALL.search(text):
        return True
    text = _MATHEMATICS.sub("mathematics", text)
    text = _PROSE_EQUALITY.sub("mathematical condition", text)
    # Check the whole suite before a sentence's parenthetical text is simplified.
    if _executable_python(textwrap.dedent(text)):
        return True
    text = _PARENTHETICAL.sub(" parenthetical explanation ", text)
    text = _MATHEMATICAL_LINE.sub("mathematical expression", text)
    if _CODE_OR_ENCODING.search(text):
        return True
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:[-*>]|\d+[.)])\s+", "", line).strip().strip("`")
        # Natural-language parenthetical explanations are not Python calls.
        if line and _executable_python(line):
            return True
    return False


def unsafe_content(value):
    """Reject executable/encoded/ambiguous text, including every string inside JSON."""
    try:
        return any(_unsafe_text(text) for text in normalized_texts(value))
    except (ValueError, TypeError, OverflowError, RecursionError):
        return True
