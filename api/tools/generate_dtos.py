"""Turn the edge's OpenAPI schema into TypeScript interfaces.

    python api/tools/generate_dtos.py web/src/app/core/contract/openapi.json \
                                      web/src/app/core/contract/dto.ts
    python api/tools/generate_dtos.py ... --check     # fail if out of date

The front end must not hand-write interfaces mirroring the Python models. They
drift the first time somebody renames a field, and the drift arrives as
`undefined` at runtime rather than as a red build.

Why this exists rather than `openapi-typescript`, which is the usual answer:
that package peer-depends on TypeScript 5, and Angular 22 ships TypeScript 6.
Installing it means forcing a resolution npm itself calls potentially broken.
The schema here is nine flat models, so the cost of owning the conversion is
low and the cost of a conflicting toolchain is not.

What makes owning it safe is the refusal below. Every construct this
understands is listed explicitly and anything else raises, naming the schema
and property. A generator that guessed would reintroduce exactly the silent
drift the generation exists to prevent, so it does not guess.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

HEADER = """\
// Generated from the edge's OpenAPI schema. Do not edit by hand.
//
// Regenerate after changing any response model in api/app/main.py:
//
//     python api/tools/dump_openapi.py  web/src/app/core/contract/openapi.json
//     python api/tools/generate_dtos.py web/src/app/core/contract/openapi.json \\
//                                       web/src/app/core/contract/dto.ts
//
// A hand-edit here is a lie about what the server sends, and it will be
// overwritten. Change the Python model instead.
"""

# Only what the schema actually uses. Anything else raises rather than
# guessing; see the module docstring.
_SCALARS = {
    "string": "string",
    "boolean": "boolean",
    "integer": "number",
    "number": "number",
    "null": "null",
}

# What TypeScript accepts as a bare property name.
_IDENTIFIER = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")

# Keys that carry documentation rather than type information.
_PROSE = {"title", "description", "default", "examples"}


class SchemaError(Exception):
    """The schema holds something this generator will not guess at."""


def _ts_type(spec: dict[str, Any], where: str) -> str:
    if "$ref" in spec:
        ref = spec["$ref"]
        prefix = "#/components/schemas/"
        if not ref.startswith(prefix):
            raise SchemaError(f"{where}: reference outside components ({ref})")
        return ref[len(prefix):]

    if "anyOf" in spec:
        parts = [_ts_type(part, where) for part in spec["anyOf"]]
        # Deduped while keeping order, so `string | null` never doubles up.
        seen: list[str] = []
        for part in parts:
            if part not in seen:
                seen.append(part)
        return " | ".join(seen)

    kind = spec.get("type")
    if kind in _SCALARS:
        return _SCALARS[kind]
    if kind == "array":
        items = spec.get("items")
        if not isinstance(items, dict):
            raise SchemaError(f"{where}: array without a single item type")
        return f"Array<{_ts_type(items, where)}>"
    if kind == "object":
        # A free-form mapping with no declared properties, which is what
        # pydantic emits for a bare dict. FastAPI's ValidationError.ctx is the
        # only one. A named object arrives as a $ref instead, so declared
        # properties here would mean a shape nobody has looked at.
        if "properties" in spec:
            raise SchemaError(
                f"{where}: an inline object with properties. Give it a name in\n"
                "    the Python model so it arrives as its own interface.")
        values = spec.get("additionalProperties")
        inner = _ts_type(values, where) if isinstance(values, dict) else "unknown"
        return f"Record<string, {inner}>"

    # Pydantic's `Any`. FastAPI's own ValidationError.input is the only one.
    if not [k for k in spec if k not in _PROSE]:
        return "unknown"

    raise SchemaError(
        f"{where}: no rule for {sorted(k for k in spec if k not in _PROSE)}.\n"
        "    Add one to api/tools/generate_dtos.py rather than hand-writing\n"
        "    the interface, or the contract stops being generated."
    )


def _key(prop: str) -> str:
    """A property name TypeScript will accept.

    Field names come from Python and need not be valid JavaScript
    identifiers: an alias like `content-type` is legal in pydantic and legal
    in JSON. Emitted bare it produced `content-type?: string`, which is a
    syntax error, so the failure arrived as a parse error in a generated file
    rather than as anything naming the field. Quoting is valid TypeScript and
    reads the same to a caller using dot access where dot access works.

    Reserved words are deliberately NOT quoted: `class` and `default` are
    perfectly good property names in TypeScript, and quoting them would be
    noise.
    """
    return prop if _IDENTIFIER.fullmatch(prop) else json.dumps(prop)


def _interface(name: str, body: dict[str, Any]) -> str:
    properties = body.get("properties") or {}
    required = set(body.get("required") or ())

    lines: list[str] = []
    description = body.get("description")
    if description:
        lines.append("/**")
        for line in description.strip().splitlines():
            lines.append(f" * {line}".rstrip())
        lines.append(" */")
    lines.append(f"export interface {name} {{")

    for prop, spec in properties.items():
        ts = _ts_type(spec, f"{name}.{prop}")
        # Optional in the schema means the key may be absent, which is not the
        # same as present-and-null. Both are expressed, so a caller cannot
        # treat a missing field as a null one by accident.
        mark = "" if prop in required else "?"
        lines.append(f"  {_key(prop)}{mark}: {ts};")

    lines.append("}")
    return "\n".join(lines)


def render(schema: dict[str, Any]) -> str:
    models = (schema.get("components") or {}).get("schemas") or {}
    if not models:
        raise SchemaError("the schema declares no components.schemas")

    blocks = [_interface(name, body) for name, body in sorted(models.items())]
    return HEADER + "\n" + "\n\n".join(blocks) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    check = "--check" in args
    if check:
        args.remove("--check")
    if len(args) != 2:
        print(__doc__, file=sys.stderr)
        return 2

    source, target = Path(args[0]), Path(args[1])
    try:
        text = render(json.loads(source.read_text(encoding="utf-8")))
    except SchemaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if check:
        current = target.read_text(encoding="utf-8") if target.is_file() else ""
        if current != text:
            print(f"error: {target} is out of date.\n"
                  f"    Regenerate it: python {Path(__file__).name} "
                  f"{source} {target}", file=sys.stderr)
            return 1
        print(f"{target} is current")
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
