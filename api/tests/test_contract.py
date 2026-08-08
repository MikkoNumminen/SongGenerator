"""The contract the front end compiles against, and whether it is still true.

Two different lies are possible here and both arrive as `undefined` at runtime
rather than as a failing build, which is the whole reason the contract is
generated rather than written:

- a Python model changed and nobody re-dumped the schema
- the schema changed and nobody re-generated the TypeScript

Each has a guard below. The rest pin that the generator refuses what it does
not understand instead of guessing, because a generator that guessed would
reintroduce exactly the drift it exists to prevent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tools.dump_openapi import schema
from tools.generate_dtos import SchemaError, render

REPO = Path(__file__).resolve().parents[2]
CONTRACT = REPO / "web" / "src" / "app" / "core" / "contract"
OPENAPI = CONTRACT / "openapi.json"
DTO = CONTRACT / "dto.ts"


class TestTheCommittedContractIsCurrent:
    def test_the_schema_matches_the_app_it_came_from(self):
        """Renaming a field in a response model and forgetting to re-dump
        leaves the front end compiling against a server that no longer speaks
        that way."""
        committed = json.loads(OPENAPI.read_text(encoding="utf-8"))

        assert committed == schema(), (
            "web/src/app/core/contract/openapi.json is out of date.\n"
            "    python api/tools/dump_openapi.py "
            "web/src/app/core/contract/openapi.json")

    def test_the_typescript_matches_the_schema(self):
        committed = DTO.read_text(encoding="utf-8")
        current = render(json.loads(OPENAPI.read_text(encoding="utf-8")))

        assert committed == current, (
            "web/src/app/core/contract/dto.ts is out of date.\n"
            "    python api/tools/generate_dtos.py "
            "web/src/app/core/contract/openapi.json "
            "web/src/app/core/contract/dto.ts")


class TestGeneratedTypes:
    def _render(self, properties: dict, required: list[str] | None = None) -> str:
        return render({"components": {"schemas": {"Thing": {
            "properties": properties, "required": required or []}}}})

    def test_a_required_field_is_not_optional(self):
        assert "  name: string;" in self._render({"name": {"type": "string"}}, ["name"])

    def test_absent_and_null_are_different_things(self):
        """A key that may be missing is not a key that may be null. Collapsing
        them lets a caller read a missing field as an explicit null."""
        out = self._render({"level": {"anyOf": [{"type": "string"},
                                                {"type": "null"}]}})

        assert "  level?: string | null;" in out

    def test_an_integer_is_a_number_because_typescript_has_no_other(self):
        assert "  code?: number;" in self._render({"code": {"type": "integer"}})

    def test_a_reference_becomes_the_interface_name(self):
        out = self._render({"bank": {"$ref": "#/components/schemas/BankReply"}})

        assert "  bank?: BankReply;" in out

    def test_an_array_of_references_keeps_its_element_type(self):
        out = self._render({"banks": {"type": "array", "items": {
            "$ref": "#/components/schemas/BankReply"}}})

        assert "  banks?: Array<BankReply>;" in out

    def test_a_bare_dict_is_a_record_rather_than_an_empty_interface(self):
        assert "Record<string, unknown>" in self._render({"ctx": {"type": "object"}})

    def test_pydantic_any_becomes_unknown_not_any(self):
        """`any` would switch type checking off for everything downstream of
        it, which is the opposite of why the contract is generated."""
        assert "  input?: unknown;" in self._render({"input": {"title": "Input"}})

    def test_a_field_name_typescript_would_reject_is_quoted(self):
        """Field names come from Python and need not be valid JavaScript
        identifiers. Emitted bare, `content-type` produced a syntax error in a
        generated file, which names nothing and points nowhere."""
        out = self._render({"content-type": {"type": "string"}})

        assert '  "content-type"?: string;' in out

    def test_a_reserved_word_is_left_alone(self):
        """`class` is a perfectly good property name in TypeScript, and
        quoting every one of them would be noise."""
        assert "  class?: string;" in self._render({"class": {"type": "string"}})

    def test_a_description_survives_as_a_comment(self):
        """The reasoning in the Python docstrings is most of what makes this
        codebase readable, and it is free to carry it across."""
        out = render({"components": {"schemas": {"Thing": {
            "description": "What an unauthenticated caller may learn.",
            "properties": {}}}}})

        assert "What an unauthenticated caller may learn." in out


class TestItRefusesRatherThanGuesses:
    """The property that makes owning this generator safe instead of reckless.

    `openapi-typescript` is the usual answer and cannot be used here: it peer
    depends on TypeScript 5 while Angular 22 ships TypeScript 6. Owning the
    conversion is only defensible while anything unrecognised stops the build.
    """

    def test_an_unknown_construct_raises_and_says_where(self):
        with pytest.raises(SchemaError, match="Thing.weird"):
            render({"components": {"schemas": {"Thing": {
                "properties": {"weird": {"oneOf": [{"type": "string"}]}}}}}})

    def test_an_inline_object_is_refused_rather_than_flattened(self):
        """It would generate an untyped `Record` and lose every field. Naming
        it in the Python model makes it arrive as its own interface."""
        with pytest.raises(SchemaError, match="Give it a name"):
            render({"components": {"schemas": {"Thing": {"properties": {
                "nested": {"type": "object",
                           "properties": {"a": {"type": "string"}}}}}}}})

    def test_a_reference_out_of_the_schema_is_refused(self):
        with pytest.raises(SchemaError, match="outside components"):
            render({"components": {"schemas": {"Thing": {"properties": {
                "x": {"$ref": "https://example.invalid/other.json#/Thing"}}}}}})

    def test_an_array_without_an_item_type_is_refused(self):
        with pytest.raises(SchemaError, match="single item type"):
            render({"components": {"schemas": {"Thing": {"properties": {
                "xs": {"type": "array"}}}}}})

    def test_a_schema_with_no_models_is_refused(self):
        """An empty file would generate an empty contract and every import in
        the front end would fail with nothing saying why."""
        with pytest.raises(SchemaError, match="no components"):
            render({"openapi": "3.1.0", "paths": {}})
