#!/usr/bin/env python3
"""Generate an isolated MySQL development schema from this checkout's Java DOs.

This is NOT the upstream production/migration schema. It infers storage types from
the public Java entities, includes inherited fields, and creates no business data.
Run with --check-only to audit mappings without writing SQL.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULES = (
    "yudao-module-member",
    "yudao-module-pay",
    "yudao-module-mall/yudao-module-product",
    "yudao-module-mall/yudao-module-promotion",
    "yudao-module-mall/yudao-module-trade",
)
BASE_FILES = (
    "yudao-framework/yudao-spring-boot-starter-mybatis/src/main/java/"
    "cn/iocoder/yudao/framework/mybatis/core/dataobject/BaseDO.java",
    "yudao-framework/yudao-spring-boot-starter-biz-tenant/src/main/java/"
    "cn/iocoder/yudao/framework/tenant/core/db/TenantBaseDO.java",
)
# Java lexical tokens: comments are ignored but strings are preserved intact.
TOKEN = re.compile(
    r'(?P<space>\s+)|(?P<comment>/\*[\s\S]*?\*/|//[^\n]*)|'
    r'(?P<string>"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')|'
    r'(?P<identifier>[A-Za-z_$][A-Za-z0-9_$]*)|(?P<symbol>.)'
)
IDENTIFIER = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
MODIFIERS = {
    "public", "protected", "private", "static", "final", "transient",
    "volatile", "abstract", "synchronized", "native", "strictfp",
}


@dataclass
class Field:
    name: str
    java_type: str
    annotations: dict[str, str]
    modifiers: set[str]
    declaring_class: str
    source: str

    @property
    def persistent(self) -> bool:
        if self.modifiers & {"static", "transient"}:
            return False
        return not re.search(
            r"\bexist\s*=\s*false\b", self.annotations.get("TableField", "")
        )


@dataclass
class Entity:
    name: str
    parent: str | None
    table: str | None
    fields: list[Field]
    source: str
    sha256: str


def tokens(text: str) -> list[str]:
    return [m.group() for m in TOKEN.finditer(text) if m.lastgroup not in {"space", "comment"}]


def matching(items: list[str], start: int, opening: str, closing: str) -> int:
    level = 0
    for i in range(start, len(items)):
        if items[i] == opening:
            level += 1
        elif items[i] == closing:
            level -= 1
            if level == 0:
                return i
    raise ValueError(f"Unmatched {opening!r}")


def annotations(items: list[str]) -> tuple[list[str], dict[str, str]]:
    remaining: list[str] = []
    result: dict[str, str] = {}
    i = 0
    while i < len(items):
        if items[i] != "@":
            remaining.append(items[i])
            i += 1
            continue
        i += 1
        parts = [items[i]]
        i += 1
        while i + 1 < len(items) and items[i] == ".":
            parts += items[i:i + 2]
            i += 2
        name = parts[-1]
        value = ""
        if i < len(items) and items[i] == "(":
            end = matching(items, i, "(", ")")
            value = " ".join(items[i + 1:end])
            i = end + 1
        result[name] = value
    return remaining, result


def parse_field(statement: list[str], cls: str, source: str) -> Field | None:
    declaration, meta = annotations(statement)
    if not declaration:
        return None
    mods: set[str] = set()
    while declaration and declaration[0] in MODIFIERS:
        mods.add(declaration.pop(0))
    if not declaration:
        return None
    # Method signatures and nested declarations never represent table columns.
    if "class" in declaration or "interface" in declaration or "(" in declaration[:declaration.index("=") if "=" in declaration else len(declaration)]:
        return None
    declaration = declaration[:declaration.index("=")] if "=" in declaration else declaration
    if len(declaration) < 2 or not IDENTIFIER.match(declaration[-1]):
        raise ValueError(f"Unsupported field declaration in {source}: {' '.join(statement)}")
    name = declaration[-1]
    java_type = "".join(declaration[:-1])
    if "," in declaration and "<" not in declaration:
        raise ValueError(f"Multiple field declaration requires review: {source}: {name}")
    return Field(name, java_type, meta, mods, cls, source)


def parse_entity(path: Path) -> Entity:
    raw = path.read_text()
    items = tokens(raw)
    cls_index = next(
        i for i, item in enumerate(items)
        if item == "class" and i + 1 < len(items) and items[i + 1] == path.stem
    )
    start = items.index("{", cls_index)
    end = matching(items, start, "{", "}")
    header = items[cls_index:start]
    parent = header[header.index("extends") + 1] if "extends" in header else None
    _, meta = annotations(items[:cls_index])
    table_meta = meta.get("TableName")
    table = None
    if table_meta is not None:
        match = re.search(r'"([^"\\]+)"', table_meta)
        if not match:
            raise ValueError(f"TableName has no literal table name: {path}")
        table = match.group(1)
    body = items[start + 1:end]
    fields: list[Field] = []
    statement: list[str] = []
    i = 0
    while i < len(body):
        token = body[i]
        if token == "{":
            # Skip method and nested type bodies, including JSON value classes.
            close = matching(body, i, "{", "}")
            if "=" in statement:
                statement += body[i:close + 1]
            else:
                statement = []
            i = close + 1
            continue
        if token == ";":
            field = parse_field(statement, path.stem, str(path.relative_to(ROOT)))
            if field:
                fields.append(field)
            statement = []
        else:
            statement.append(token)
        i += 1
    return Entity(path.stem, parent, table, fields, str(path.relative_to(ROOT)), hashlib.sha256(raw.encode()).hexdigest())


def snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def column_name(field: Field) -> str:
    annotation = field.annotations.get("TableField", "")
    override = re.match(r'^\s*(?:value\s*=\s*)?"([^"\\]+)"', annotation)
    if not override:
        override = re.match(r'^\s*(?:value\s*=\s*)?"([^"\\]+)"', field.annotations.get("TableId", ""))
    return override.group(1) if override else snake(field.name)


def sql_type(field: Field) -> tuple[str, str | None]:
    java_type = field.java_type
    handler = re.search(r"typeHandler\s*=\s*([A-Za-z0-9_$.]+)", field.annotations.get("TableField", ""))
    if handler:
        # CSV list handlers must not use a native JSON column. LONGTEXT supports
        # both their comma-separated representation and JSON type handlers.
        return "LONGTEXT", None
    simple = {
        "Long": "BIGINT", "long": "BIGINT", "Integer": "INT", "int": "INT",
        "Boolean": "BIT(1)", "boolean": "BIT(1)", "Double": "DOUBLE", "double": "DOUBLE",
        "Float": "FLOAT", "float": "FLOAT", "Short": "SMALLINT", "short": "SMALLINT",
        "Byte": "TINYINT", "byte": "TINYINT", "BigDecimal": "DECIMAL(24,8)",
        "LocalDateTime": "DATETIME(6)", "LocalDate": "DATE", "LocalTime": "TIME(6)",
        "Date": "DATETIME(6)", "Instant": "DATETIME(6)", "byte[]": "LONGBLOB",
    }
    if java_type in simple:
        return simple[java_type], None
    if java_type == "String":
        # DOs do not specify a DB string length. Development-only TEXT avoids
        # arbitrary truncation and InnoDB's row-size limit on wide order tables.
        # Audit fields are short and receive explicit safe defaults below.
        return ("VARCHAR(64)" if field.name in {"creator", "updater"} else "TEXT"), None
    return "LONGTEXT", f"{field.source}:{field.name}: {java_type} has no explicit typeHandler"


def inherited_fields(entity: Entity, classes: dict[str, Entity], stack: tuple[str, ...] = ()) -> list[Field]:
    if entity.name in stack:
        raise ValueError("Inheritance cycle: " + " -> ".join(stack + (entity.name,)))
    combined: list[Field] = []
    if entity.parent:
        if entity.parent not in classes:
            raise ValueError(f"Unknown superclass {entity.parent} of {entity.name}")
        combined = inherited_fields(classes[entity.parent], classes, stack + (entity.name,))
    # Java subclasses shadow fields. Match MyBatis-Plus by keeping the subclass.
    by_name = {field.name: field for field in combined}
    by_name.update({field.name: field for field in entity.fields})
    return list(by_name.values())


def quote_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"Unsafe SQL identifier: {value!r}")
    return "`" + value + "`"


def generate(check_only: bool = False) -> dict:
    paths = [ROOT / path for path in BASE_FILES]
    for module in MODULES:
        paths += sorted((ROOT / module / "src/main/java").rglob("*DO.java"))
    classes: dict[str, Entity] = {}
    for path in paths:
        entity = parse_entity(path)
        if entity.name in classes:
            raise ValueError(f"Duplicate simple class name: {entity.name}")
        classes[entity.name] = entity
    entities = sorted((e for e in classes.values() if e.table), key=lambda e: e.table)
    if len({e.table for e in entities}) != len(entities):
        raise ValueError("Duplicate table name")
    lines = [
        "-- GENERATED LOCAL DEVELOPMENT SCHEMA ONLY; NOT THE UPSTREAM MIGRATION SQL.",
        "-- Source: public Java DO classes in this checkout; generated by generate_schema.py.",
        "-- No restricted SQL attachment, demo customer records, credentials, or goods data used.",
        "-- Java types determine column types; String lengths, production indexes, foreign keys,",
        "-- and business nullability cannot be reconstructed from DOs and are not claimed here.",
        "-- String=TEXT; explicit typeHandler=LONGTEXT (supports JSON as well as CSV handlers).",
        "-- Missing tenant_id is added for the default tenant SQL interceptor; local default=1.",
        "-- CREATE TABLE IF NOT EXISTS is non-destructive; it does not migrate existing tables.",
        "SET NAMES utf8mb4;",
        "",
    ]
    uncertainty: list[str] = []
    audit: list[dict] = []
    for entity in entities:
        all_fields = inherited_fields(entity, classes)
        fields = [field for field in all_fields if field.persistent]
        column_fields = {column_name(field): field for field in fields}
        if len(column_fields) != len(fields):
            raise ValueError(f"Duplicate persistent columns in {entity.name}")
        pk = [column_name(field) for field in fields if "TableId" in field.annotations]
        if not pk and "id" in column_fields:
            pk = ["id"]
        if len(pk) != 1:
            raise ValueError(f"Expected one primary key in {entity.name}, found {pk}")
        definitions: list[str] = []
        for column, field in column_fields.items():
            sql, issue = sql_type(field)
            if issue:
                uncertainty.append(issue)
            suffix = " NULL"
            if column == pk[0]:
                suffix = " NOT NULL" + (" AUTO_INCREMENT" if sql in {"BIGINT", "INT"} else "")
            elif column == "deleted":
                suffix = " NOT NULL DEFAULT b'0'"
            elif column == "tenant_id":
                suffix = " NOT NULL DEFAULT 1"
            elif column in {"create_time", "update_time"}:
                suffix = " NOT NULL DEFAULT CURRENT_TIMESTAMP(6)"
            elif column in {"creator", "updater"}:
                suffix = " NULL DEFAULT ''"
            definitions.append(f"  {quote_identifier(column)} {sql}{suffix}")
        added_tenant = "tenant_id" not in column_fields
        if added_tenant:
            definitions.append("  `tenant_id` BIGINT NOT NULL DEFAULT 1")
        definitions.append("  PRIMARY KEY (" + quote_identifier(pk[0]) + ")")
        if "deleted" in column_fields:
            definitions.append("  KEY `idx_local_tenant_deleted` (`tenant_id`, `deleted`)")
        lines += [
            f"-- Entity: {entity.source}",
            f"-- Source SHA-256: {entity.sha256}",
            f"-- Persistent Java fields: {len(fields)}; inherited fields included; extra tenant column: {added_tenant}.",
            "CREATE TABLE IF NOT EXISTS " + quote_identifier(entity.table) + " (",
            ",\n".join(definitions),
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;",
            "",
        ]
        audit.append({
            "table": entity.table,
            "entity": entity.name,
            "source": entity.source,
            "persistentFields": len(fields),
            "mappedColumns": len(column_fields),
            "nonPersistentFields": [f.name for f in all_fields if not f.persistent],
            "addedTenantColumn": added_tenant,
            "columns": list(column_fields),
        })
    summary = {
        "tableCount": len(entities),
        "persistentFieldCount": sum(x["persistentFields"] for x in audit),
        "mappedPersistentFieldCount": sum(x["mappedColumns"] for x in audit),
        "unresolvedTypes": uncertainty,
        "allPersistentFieldsMapped": all(x["persistentFields"] == x["mappedColumns"] for x in audit),
        "developmentAssumptions": [
            "Strings use TEXT because DOs do not specify database lengths.",
            "Explicit MyBatis typeHandler fields use LONGTEXT, including CSV list handlers.",
            "All business tables include tenant_id; missing entity property is added for default tenant interception.",
            "Only primary key and local tenant/deleted index are generated; no production index/constraint claim.",
            "No business seed data or payment/channel credentials are generated.",
        ],
        "tables": audit,
    }
    if uncertainty:
        raise ValueError("Unresolved persistent Java types: " + json.dumps(uncertainty, ensure_ascii=False))
    if not check_only:
        output = Path(__file__).with_name("generated-mall-schema.sql")
        output.write_text("\n".join(lines))
        summary["output"] = str(output)
        summary["outputSha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    print(json.dumps(generate(args.check_only), ensure_ascii=False, indent=2))
