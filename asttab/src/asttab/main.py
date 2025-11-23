"""Utilities for moving there-and-back between AST dumps and code."""

from __future__ import annotations

import argparse
import ast
import inspect
import re
from collections.abc import AsyncGenerator, Callable
from pathlib import Path
from typing import Any

OK = 0


def _ast_class(name: str) -> str:
    return f"ast.{name}"


class ASTParser:
    """
    Parses the text format produced by ast.dump(..., indent=4)
    and generates Python code that reconstructs the AST.
    """

    node_re = re.compile(r"([A-Za-z0-9_]+)\(")
    field_re = re.compile(r"([A-Za-z_]+)=")

    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.length = len(text)
        self.indent = " " * 4

    # ------------------- low-level movement -------------------

    def peek(self) -> str:
        return self.text[self.pos : self.pos + 1]

    def eat(self, s: str) -> None:
        assert self.text.startswith(s, self.pos), f"Expected '{s}' at pos {self.pos}"
        self.pos += len(s)

    def skip_ws(self) -> None:
        while self.peek().isspace():
            self.pos += 1

    # ------------------- high-level parsing -------------------

    def parse_value(self) -> Any:
        self.skip_ws()

        ch = self.peek()

        if not ch:
            raise ValueError("Unexpected end of input")

        # AST node
        m = self.node_re.match(self.text, self.pos)
        if m:
            return self.parse_node()

        # List
        if ch == "[":
            return self.parse_list()

        # Tuple
        if ch == "(":
            return self.parse_tuple()

        # String literal (Python repr)
        if ch in ("'", '"'):
            return self.parse_string()

        # Number / True / False / None
        return self.parse_atom()

    def parse_node(self) -> str:
        """
        Parse Node(foo=..., bar=...)
        Returns Python code string: ast.Node(foo=..., bar=...)
        """

        # Get node name
        m = self.node_re.match(self.text, self.pos)
        if m is None:
            raise ValueError(f"Expected AST node at pos {self.pos}")
        name = m.group(1)
        self.pos = m.end()

        code = f"{_ast_class(name)}("

        args: list[str] = []

        # Read fields
        while True:
            self.skip_ws()
            if self.peek() == ")":
                break

            # Field name
            m = self.field_re.match(self.text, self.pos)
            if not m:
                break
            field = m.group(1)
            self.pos = m.end()

            value = self.parse_value()
            args.append(f"{field}={value}")

            self.skip_ws()
            if self.peek() == ",":
                self.eat(",")
                continue
            else:
                break

        self.eat(")")
        return code + ", ".join(args) + ")"

    def parse_list(self) -> str:
        self.eat("[")
        items: list[str] = []
        while True:
            self.skip_ws()
            if self.peek() == "]":
                break
            items.append(self.parse_value())
            self.skip_ws()
            if self.peek() == ",":
                self.eat(",")
                continue
            else:
                break
        self.eat("]")
        return "[" + ", ".join(items) + "]"

    def parse_tuple(self) -> str:
        self.eat("(")
        items: list[str] = []
        while True:
            self.skip_ws()
            if self.peek() == ")":
                break
            items.append(self.parse_value())
            self.skip_ws()
            if self.peek() == ",":
                self.eat(",")
                continue
            else:
                break
        self.eat(")")
        if len(items) == 1:
            return "(" + items[0] + ",)"
        return "(" + ", ".join(items) + ")"

    def parse_string(self) -> str:
        quote = self.peek()
        assert quote in ("'", '"')
        self.pos += 1
        start = self.pos
        while self.peek() != quote:
            if not self.peek():
                raise ValueError("Unterminated string")
            self.pos += 1
        s = self.text[start : self.pos]
        self.pos += 1
        return repr(s)

    def parse_atom(self) -> str:
        """
        Parse numbers, True/False, None
        """
        start = self.pos
        while self.peek() and re.match(r"[A-Za-z0-9_.+-]", self.peek()):
            self.pos += 1
        atom = self.text[start : self.pos]

        # Validate atoms / return literal Python code
        if atom in ("True", "False", "None"):
            return atom

        # Numbers?
        if re.fullmatch(r"[+-]?\d+", atom):
            return atom

        raise ValueError(f"Unknown atom: {atom!r}")


def there(target: str | Callable[..., Any], *, indent: int = 4) -> str:
    """Return ast.dump output for a source string or callable."""

    if isinstance(target, str):
        source = target
    elif callable(target):
        try:
            source = inspect.getsource(target)
        except (OSError, TypeError) as exc:
            raise ValueError("Callable source unavailable") from exc
    else:
        raise TypeError("there() expects a source string or callable")

    node = ast.parse(source)
    return ast.dump(node, indent=indent)


def back(
    builder_code: str,
    *,
    return_callable: bool = False,
) -> str | Callable[..., Any]:
    """Convert ASTParser output back into source, optionally returning a callable."""

    try:
        built_ast = eval(builder_code, {"ast": ast})
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError("Invalid builder code") from exc

    if not isinstance(built_ast, ast.AST):
        raise TypeError("Builder code did not produce an AST instance")

    built_ast = ast.fix_missing_locations(built_ast)
    source = ast.unparse(built_ast)

    if not return_callable:
        return source

    if not isinstance(built_ast, ast.Module):
        raise ValueError("Callable reconstruction requires a module AST")

    func_defs = [
        node.name
        for node in built_ast.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]

    if len(func_defs) != 1:
        raise ValueError(
            "Callable reconstruction expects exactly one function definition"
        )

    namespace: dict[str, Any] = {
        "__builtins__": __builtins__,
        "Any": Any,
        "AsyncGenerator": AsyncGenerator,
    }
    namespace.update(globals())
    exec(compile(built_ast, "<back>", "exec"), namespace)
    func = namespace.get(func_defs[0])
    if not callable(func):
        raise ValueError("Failed to locate callable in rebuilt source")
    return func


def _emit_builder_script(builder_code: str) -> None:
    print("import ast")
    print()
    print("node = ", builder_code, sep="")
    print()
    print("print(ast.dump(node, indent=4))  # validation")


def _cmd_parse(args: argparse.Namespace) -> None:
    dump_text = Path(args.dump_file).read_text(encoding="utf-8")
    parser = ASTParser(dump_text)
    builder_code = parser.parse_value()
    _emit_builder_script(builder_code)


def _cmd_there(args: argparse.Namespace) -> None:
    source = (
        args.code
        if args.code is not None
        else Path(args.file).read_text(encoding="utf-8")
    )
    print(there(source, indent=args.indent))


def _cmd_back(args: argparse.Namespace) -> None:
    builder_code = (
        args.builder
        if args.builder is not None
        else Path(args.file).read_text(encoding="utf-8")
    )
    result = back(builder_code)
    if isinstance(result, str):
        print(result)
    else:
        print(f"Callable reconstructed: {result.__name__}")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    parse_cmd = subparsers.add_parser(
        "parse",
        help="Convert ast.dump output (indent=4) into builder code",
    )
    parse_cmd.add_argument(
        "dump_file",
        type=Path,
        help="Path to file containing ast.dump output",
    )
    parse_cmd.set_defaults(handler=_cmd_parse)

    there_cmd = subparsers.add_parser(
        "there",
        help="Produce ast.dump output for inline code or a file",
    )
    there_cmd.add_argument(
        "--indent",
        "-i",
        type=int,
        default=4,
        help="Indent width to pass to ast.dump (default: 4)",
    )
    group_there = there_cmd.add_mutually_exclusive_group(required=True)
    group_there.add_argument(
        "--code",
        "-c",
        help="Inline Python source to inspect",
    )
    group_there.add_argument(
        "--file",
        "-f",
        type=Path,
        help="Path to Python file whose source will be dumped",
    )
    there_cmd.set_defaults(handler=_cmd_there)

    back_cmd = subparsers.add_parser(
        "back",
        help="Rebuild Python source (or callable) from AST builder code",
    )
    group_back = back_cmd.add_mutually_exclusive_group(required=True)
    group_back.add_argument(
        "--builder",
        "-b",
        help="Inline builder expression emitted by ASTParser",
    )
    group_back.add_argument(
        "--file",
        "-f",
        type=Path,
        help="Path to file containing builder expression",
    )
    back_cmd.set_defaults(handler=_cmd_back)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    args.handler(args)
    return OK


if __name__ == "__main__":
    raise SystemExit(main())
