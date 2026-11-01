r"""Write a compact outline (names, fields, signatures, routes; no bodies).

Usage (from the project root):
  python tools\outline.py <substring> [<substring> ...] [--root backend] [--out docs\OUTLINE.txt]
A file is included when its path contains ANY of the substrings.
"""
import ast
import sys
from pathlib import Path


def sig(fn):
    try:
        args = ast.unparse(fn.args)
    except Exception:
        args = "..."
    ret = ""
    if fn.returns is not None:
        ret = " -> " + ast.unparse(fn.returns)
    kind = "async def" if isinstance(fn, ast.AsyncFunctionDef) else "def"
    return f"{kind} {fn.name}({args}){ret}"


def decos(node):
    out = []
    for d in node.decorator_list:
        try:
            out.append("@" + ast.unparse(d))
        except Exception:
            pass
    return out


def short(expr, limit=110):
    try:
        text = ast.unparse(expr)
    except Exception:
        return "..."
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def class_lines(cls, indent):
    pad = "  " * indent
    bases = ", ".join(short(b, 40) for b in cls.bases)
    lines = [f"{pad}class {cls.name}({bases})"]
    for d in decos(cls):
        lines.append(f"{pad}  {d}")
    for item in cls.body:
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            val = f" = {short(item.value)}" if item.value is not None else ""
            lines.append(f"{pad}  {item.target.id}: {short(item.annotation, 80)}{val}")
        elif isinstance(item, ast.Assign):
            names = [t.id for t in item.targets if isinstance(t, ast.Name)]
            if names:
                lines.append(f"{pad}  {', '.join(names)} = {short(item.value)}")
        elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in decos(item):
                lines.append(f"{pad}  {d}")
            lines.append(f"{pad}  {sig(item)}")
        elif isinstance(item, ast.ClassDef):
            lines.extend(class_lines(item, indent + 1))
    return lines


def outline(path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # unreadable or syntax error
        return [f"  (could not parse: {exc})"]
    lines = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            lines.extend(class_lines(node, 1))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in decos(node):
                lines.append(f"  {d}")
            lines.append(f"  {sig(node)}")
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if names and all(n.isupper() or n in ("router",) for n in names):
                lines.append(f"  {', '.join(names)} = {short(node.value)}")
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id.isupper():
                lines.append(f"  {node.target.id}: {short(node.annotation, 60)} = {short(node.value) if node.value else ''}")
    return lines


def main(argv):
    root, out, subs = "backend", "docs/OUTLINE.txt", []
    i = 0
    while i < len(argv):
        if argv[i] == "--root":
            root = argv[i + 1]
            i += 2
        elif argv[i] == "--out":
            out = argv[i + 1]
            i += 2
        else:
            subs.append(argv[i].replace("\\", "/"))
            i += 1
    if not subs:
        print("Give at least one path substring, e.g. schemas models")
        return 2
    files = []
    for p in sorted(Path(root).rglob("*.py")):
        norm = p.as_posix()
        if any(s in norm for s in subs) and "__pycache__" not in norm and ".venv" not in norm:
            files.append(p)
    chunks = []
    for p in files:
        body = outline(p)
        if body:
            chunks.append(f"### {p.as_posix()}")
            chunks.extend(body)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text("\n".join(chunks) + "\n", encoding="utf-8")
    size = Path(out).stat().st_size
    print(f"files: {len(files)}  wrote: {out}  bytes: {size}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
