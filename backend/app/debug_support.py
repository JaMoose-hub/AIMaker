"""Pure helpers: identity, redaction and strictly bounded application-logic edits."""
import ast
import difflib
import hashlib
import json
import re
import subprocess
import sys

from app.component_testing import TEMPLATE_VERSION, wire_key
from app.designs import CATALOG, MODULES, profile_versions, render_code, validate_logic, wiring_for

DEBUG_VERSION = "debug-v1"


def digest(value):
    return hashlib.sha256((value if isinstance(value, str) else json.dumps(value, sort_keys=True)).encode()).hexdigest()


def sanitize(value, password=""):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if re.search(r"password|secret|token|authorization|private.?key", k, re.I)
                else sanitize(v, password) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v, password) for v in value]
    if not isinstance(value, str):
        return value
    if password:
        value = value.replace(password, "[REDACTED]")
    value = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|$)", "[REDACTED KEY]", value, flags=re.S)
    value = re.sub(r"(?i)\b(?:Bearer|Basic)\s+[^\s\"']+", "[REDACTED]", value)
    value = re.sub(r"(?i)([\"']?(?:api[_-]?key|password|passwd|secret|token|authorization)[\"']?\s*[:=]\s*)(?:[\"'][^\"'\n]*[\"']|[^\s,;]+)", r"\1[REDACTED]", value)
    value = re.sub(r"(?i)\bBearer\s+\S+|\b(?:sk-[\w-]{10,}|gh[pousr]_[\w]{10,}|github_pat_[\w]+)", "[REDACTED]", value)
    return re.sub(r"(https?://)[^/@\s]+:[^/@\s]+@", r"\1[REDACTED]@", value)


def validate_project(project):
    if not project or not project.get("id"):
        raise ValueError("project_required")
    ids = project.get("component_ids", [])
    if not ids or len(ids) > 2 or len(set(ids)) != len(ids) or any(cid not in MODULES for cid in ids):
        raise ValueError("unsupported_component")
    if project.get("catalog_version") != CATALOG["version"] or project.get("profile_versions") != profile_versions(ids):
        raise ValueError("profile_changed")
    if wire_key(project.get("wiring", [])) != wire_key(wiring_for(ids)):
        raise ValueError("wiring_changed")
    return dict(imports=sorted({v for cid in ids for v in MODULES[cid]["runtime"]["imports"]}),
                devices=sorted({v for cid in ids for v in MODULES[cid]["runtime"]["devices"]}))


def identity(context, target):
    p = context.get("project") or {}
    return dict(target_id=target, project_id=p.get("id"), code_hash=digest(context.get("code", "")),
                wiring_hash=digest(wire_key(p.get("wiring", []))), profiles=p.get("profile_versions"),
                test_keys=context.get("test_keys", {}),
                template_version=TEMPLATE_VERSION, debug_version=DEBUG_VERSION)


def generated_logic(code, project=None):
    """Fail closed unless the entire hardware scaffold matches our current template."""
    tree = ast.parse(code)
    assigns = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body
               if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
               and n.targets[0].id in {"PINS", "SETTINGS"}}
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "exec"]
    if len(calls) != 1 or not calls[0].args or not isinstance(calls[0].args[0], ast.Constant):
        raise ValueError("unsupported_draft")
    logic = calls[0].args[0].value
    if not isinstance(logic, str) or not assigns.get("PINS") or "SETTINGS" not in assigns:
        raise ValueError("unsupported_draft")
    ids = list(assigns["PINS"])
    if project:
        validate_project(project)
        if set(ids) != set(project["component_ids"]):
            raise ValueError("unsupported_draft")
    canonical = render_code(wiring_for(ids), assigns["SETTINGS"], logic, [])
    if ast.dump(tree) != ast.dump(ast.parse(canonical)):
        raise ValueError("unsupported_draft")
    return logic, calls[0].args[0], assigns["SETTINGS"]


def repair(code, project, new_logic):
    old_logic, node, params = generated_logic(code, project)
    validate_logic(new_logic)
    offline = offline_logic(new_logic, params)
    # Replace exactly one literal; leave comments, GPIO, parameters and drivers untouched.
    lines = code.splitlines(keepends=True)
    start = sum(len(s.encode()) for s in lines[:node.lineno-1]) + node.col_offset
    end = sum(len(s.encode()) for s in lines[:node.end_lineno-1]) + node.end_col_offset
    raw = code.encode()
    candidate = (raw[:start] + repr(new_logic).encode() + raw[end:]).decode()
    compile(candidate, "candidate.py", "exec")
    generated_logic(candidate, project)
    return dict(code=candidate, logic=new_logic, offline=offline,
                diff="\n".join(difflib.unified_diff(old_logic.splitlines(), new_logic.splitlines(), fromfile="before/on_sample", tofile="candidate/on_sample", lineterm="")))


def offline_logic(logic, params):
    validate_logic(logic)
    tree = ast.parse(logic)
    # This is a logic validator, not an OS sandbox. Bound expensive syntax before execution.
    if len(logic) > 8000 or sum(1 for _ in ast.walk(tree)) > 500:
        raise ValueError("logic_too_large")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Subscript, ast.Attribute)) and isinstance(node.ctx, (ast.Store, ast.Del)):
            raise ValueError("logic_must_not_mutate_inputs")
        if isinstance(node, ast.Name) and node.id in {"settings", "readings"} and isinstance(node.ctx, (ast.Store, ast.Del)):
            raise ValueError("logic_must_not_replace_inputs")
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Pow, ast.LShift, ast.RShift, ast.Mult)):
            raise ValueError("unbounded_logic_operation")
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, int)) and len(str(node.value)) > 2000:
            raise ValueError("logic_literal_too_large")
    cases = [0, 5, params["distance_cm"] - .1, params["distance_cm"], params["distance_cm"] + .1, 100, 399]
    script = "import json,sys\np=json.load(sys.stdin)\nns={'__builtins__':{n:__builtins__.__dict__[n] for n in ['str','round','int','float','abs','min','max','bool','len']}}\nexec(p['logic'],ns)\nfor d in p['cases']:\n r=ns['on_sample']({'distance_cm':d},p['params'])\n assert isinstance(r,str) and len(r)<4096, 'invalid_result'\nprint('ok')"
    proc = subprocess.run([sys.executable, "-I", "-c", script], input=json.dumps(dict(logic=logic, cases=cases, params=params)), text=True, capture_output=True, timeout=3)
    if proc.returncode:
        raise ValueError("offline_logic_failed: " + proc.stderr[-1000:])
    return dict(status="passed", cases=cases, scope="Offline execution only; expected semantics and hardware require trial")


def observed_source(code):
    """Instrument only our unmodified scaffold; unknown code still gets heartbeat/exit evidence."""
    try:
        generated_logic(code)
    except (ValueError, SyntaxError, KeyError, TypeError):
        return code, False
    class Observe(ast.NodeTransformer):
        def visit_Expr(self, node):
            call = node.value
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) and call.func.value.id == "display" and call.func.attr in {"show_distance", "test_card"}:
                return [node, ast.parse("__bv_emit('display', None)").body[0]]
            return node
        def visit_Assign(self, node):
            if any(isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self" and t.attr == "latest" for t in node.targets) and isinstance(node.value, ast.Tuple):
                return [node, ast.parse("__bv_emit('sample', self.latest)").body[0]]
            return node
    return ast.unparse(ast.fix_missing_locations(Observe().visit(ast.parse(code)))), True
