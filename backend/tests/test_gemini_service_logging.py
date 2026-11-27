"""LOG_ALL_GEMINI_CALLS_V1: every generate_content call in gemini_service must be token-logged."""
import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src/multimodal/gemini_service.py"


def _is_generate_content_assign(node):
    if not isinstance(node, ast.Assign):
        return False
    v = node.value.value if isinstance(node.value, ast.Await) else node.value
    return isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute) and v.func.attr == "generate_content"


def test_every_generate_content_call_is_logged():
    text = SRC.read_text(encoding="utf-8")
    missing = []
    for fn in ast.walk(ast.parse(text)):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            calls = [n for n in ast.walk(fn) if _is_generate_content_assign(n)]
            logs = (ast.get_source_segment(text, fn) or "").count("log_tokens")
            if len(calls) > logs:
                missing.append(f"{fn.name} (line {fn.lineno}): {len(calls)} call(s), {logs} log_tokens")
    assert not missing, "unlogged generate_content calls: " + "; ".join(missing)
