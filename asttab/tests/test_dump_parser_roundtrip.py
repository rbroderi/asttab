"""Pytest coverage for DumpParser round-tripping async_yield_from."""

from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path
from typing import Any

import pytest  # type: ignore[import-not-found]
from async_yield_from import async_yield_from

from asttab import ASTParser, back, there  # type: ignore[import-not-found]
from asttab.main import main as cli_main  # type: ignore[import-not-found]


def _build_roundtrip_ast() -> tuple[str, ast.AST, ast.AST]:
    """Return builder code plus original and rebuilt ASTs for async_yield_from."""

    snippet = inspect.getsource(async_yield_from)
    original_ast = ast.parse(snippet)
    dump_text = ast.dump(original_ast, indent=4)

    parser = ASTParser(dump_text)
    builder_code = parser.parse_value()

    namespace: dict[str, object] = {"ast": ast}
    rebuilt_ast = eval(builder_code, namespace)
    rebuilt_ast = ast.fix_missing_locations(rebuilt_ast)

    return builder_code, original_ast, rebuilt_ast


def test_dump_parser_roundtrip_async_yield_from() -> None:
    _, original_ast, rebuilt_ast = _build_roundtrip_ast()

    assert isinstance(rebuilt_ast, ast.AST)

    assert ast.dump(original_ast, include_attributes=False) == ast.dump(
        rebuilt_ast, include_attributes=False
    ), "Reconstructed AST should match dump source"

    regenerated_ast = ast.parse(ast.unparse(rebuilt_ast))
    assert ast.dump(original_ast, include_attributes=False) == ast.dump(
        regenerated_ast, include_attributes=False
    ), "Re-unparsing rebuilt AST should remain identical"


def test_there_accepts_callable_and_string() -> None:
    source = inspect.getsource(async_yield_from)
    expected = ast.dump(ast.parse(source), indent=4)

    assert there(async_yield_from) == expected
    assert there(source) == expected


def test_back_returns_source_string() -> None:
    builder_code, _, _ = _build_roundtrip_ast()
    recovered = back(builder_code)

    assert isinstance(recovered, str)
    assert "async def async_yield_from" in recovered


def test_cli_there_outputs_dump(capsys: Any) -> None:
    cli_main(["there", "--code", "x = 1"])
    out = capsys.readouterr().out
    assert "Module(" in out


def test_cli_back_prints_source(capsys: Any) -> None:
    builder_code, _, _ = _build_roundtrip_ast()
    cli_main(["back", "--builder", builder_code])
    out = capsys.readouterr().out
    assert "async def async_yield_from" in out


def test_cli_back_reads_builder_file(tmp_path: Path, capsys: Any) -> None:
    builder_code, _, _ = _build_roundtrip_ast()
    builder_file = tmp_path / "builder.txt"
    builder_file.write_text(builder_code, encoding="utf-8")

    cli_main(["back", "--file", str(builder_file)])
    out = capsys.readouterr().out
    assert "async def async_yield_from" in out


def test_cli_parse_emits_builder(tmp_path: Path, capsys: Any) -> None:
    snippet = inspect.getsource(async_yield_from)
    dump_text = ast.dump(ast.parse(snippet), indent=4)
    dump_path = tmp_path / "dump.txt"
    dump_path.write_text(dump_text, encoding="utf-8")

    cli_main(["parse", str(dump_path)])
    out = capsys.readouterr().out
    assert "node =" in out


def test_cli_there_reads_file(tmp_path: Path, capsys: Any) -> None:
    source_path = tmp_path / "snippet.py"
    source_path.write_text("value = 42", encoding="utf-8")

    cli_main(["there", "--file", str(source_path), "--indent", "2"])
    out = capsys.readouterr().out
    assert "Module(" in out


@pytest.mark.parametrize(
    "snippet",
    [
        "x = (1, 2, 3)",
        "def add(a: int, b: int = 0):\n    return a + b",
        "class Greeter:\n    def greet(self, who: str):\n        return f'hi {who}'",
        "async def fetch(data):\n    return await coro(data)",
        "result = [n * n for n in range(5)]",
        "match value:\n    case 1:\n        out = 'one'\n    case _:\n        out = 'many'",
    ],
)
def test_ast_parser_handles_varied_snippets(snippet: str) -> None:
    normalized = textwrap.dedent(snippet).strip()
    dump_text = ast.dump(ast.parse(normalized), indent=4)

    parser = ASTParser(dump_text)
    builder_code = parser.parse_value()

    namespace: dict[str, Any] = {"ast": ast}
    rebuilt_ast = eval(builder_code, namespace)
    rebuilt_ast = ast.fix_missing_locations(rebuilt_ast)

    assert ast.dump(ast.parse(normalized), include_attributes=False) == ast.dump(
        rebuilt_ast, include_attributes=False
    )

    roundtripped_source = ast.unparse(rebuilt_ast)
    assert ast.dump(
        ast.parse(roundtripped_source), include_attributes=False
    ) == ast.dump(ast.parse(normalized), include_attributes=False)


def test_back_returns_callable() -> None:
    builder_code, _, _ = _build_roundtrip_ast()
    func = back(builder_code, return_callable=True)

    assert inspect.isasyncgenfunction(func)
