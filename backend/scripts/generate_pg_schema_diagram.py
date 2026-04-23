#!/usr/bin/env python3
"""
Generate a database "class"/ER diagram image directly from a live PostgreSQL database.

This script introspects *schema only* (tables/columns/PK/FK). It never reads table data.

Usage:
  python3 backend/scripts/generate_pg_schema_diagram.py \
    --db-url "postgresql://user:pass@localhost:5432/db" \
    --schema public \
    --out Doc/db_schema.png

If --db-url is omitted, it uses DATABASE_URL env var, falling back to the backend default.
Requires: psycopg2, graphviz (dot).
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor


DEFAULT_DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://lovable:lovable123@localhost:5432/lovable",
)


def _port(s: str) -> str:
    # Graphviz "port" identifiers must be simple; normalize anything odd.
    return re.sub(r"[^a-zA-Z0-9_]", "_", s)


def _escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


@dataclass(frozen=True)
class Column:
    name: str
    data_type: str
    is_nullable: bool
    default: Optional[str]
    is_pk: bool = False


@dataclass(frozen=True)
class ForeignKey:
    constraint_name: str
    src_table: str
    src_column: str
    ref_table: str
    ref_column: str


def _fetch_tables(conn, schema: str) -> List[str]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s
              AND table_type = 'BASE TABLE'
            ORDER BY table_name;
            """,
            (schema,),
        )
        return [r["table_name"] for r in cur.fetchall()]


def _fetch_columns(conn, schema: str, table: str) -> List[Column]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
              column_name,
              data_type,
              is_nullable,
              column_default
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
            ORDER BY ordinal_position;
            """,
            (schema, table),
        )
        cols = []
        for r in cur.fetchall():
            cols.append(
                Column(
                    name=r["column_name"],
                    data_type=r["data_type"],
                    is_nullable=(r["is_nullable"] == "YES"),
                    default=r["column_default"],
                    is_pk=False,
                )
            )
        return cols


def _fetch_primary_keys(conn, schema: str) -> Dict[str, List[str]]:
    """
    Returns: {table_name: [pk_col1, pk_col2, ...]}
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
              tc.table_name,
              kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema = %s
            ORDER BY tc.table_name, kcu.ordinal_position;
            """,
            (schema,),
        )
        out: Dict[str, List[str]] = {}
        for r in cur.fetchall():
            out.setdefault(r["table_name"], []).append(r["column_name"])
        return out


def _fetch_foreign_keys(conn, schema: str) -> List[ForeignKey]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
              tc.constraint_name,
              tc.table_name AS src_table,
              kcu.column_name AS src_column,
              ccu.table_name AS ref_table,
              ccu.column_name AS ref_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = %s
            ORDER BY tc.table_name, kcu.column_name;
            """,
            (schema,),
        )
        fks: List[ForeignKey] = []
        for r in cur.fetchall():
            fks.append(
                ForeignKey(
                    constraint_name=r["constraint_name"],
                    src_table=r["src_table"],
                    src_column=r["src_column"],
                    ref_table=r["ref_table"],
                    ref_column=r["ref_column"],
                )
            )
        return fks


def _build_dot(
    schema: str,
    tables: List[str],
    columns_by_table: Dict[str, List[Column]],
    foreign_keys: List[ForeignKey],
) -> str:
    # Plain, readable left-to-right diagram
    lines: List[str] = []
    lines.append("digraph ERD {")
    lines.append("  graph [rankdir=LR, bgcolor=\"white\", fontname=\"Helvetica\"];")
    lines.append("  node  [shape=plaintext, fontname=\"Helvetica\"];")
    lines.append("  edge  [fontname=\"Helvetica\", color=\"#334155\"];")
    lines.append("")

    # Nodes (tables)
    for t in tables:
        cols = columns_by_table.get(t, [])
        header = _escape_html(f"{schema}.{t}")
        lines.append(f"  \"{t}\" [label=<")
        lines.append("    <table border=\"0\" cellborder=\"1\" cellspacing=\"0\" cellpadding=\"4\">")
        lines.append(f"      <tr><td bgcolor=\"#0f172a\"><font color=\"#ffffff\"><b>{header}</b></font></td></tr>")
        for c in cols:
            label_bits = [c.name, f"({c.data_type})"]
            if c.is_pk:
                label_bits.append("PK")
            if not c.is_nullable:
                label_bits.append("NOT NULL")
            row_label = _escape_html(" ".join(label_bits))
            lines.append(f"      <tr><td align=\"left\" port=\"{_port(c.name)}\">{row_label}</td></tr>")
        lines.append("    </table>")
        lines.append("  >];")
        lines.append("")

    # Edges (FKs)
    for fk in foreign_keys:
        # Use ports when possible for nicer lines.
        src_port = _port(fk.src_column)
        ref_port = _port(fk.ref_column)
        edge_label = _escape_html(f"{fk.src_column} → {fk.ref_table}.{fk.ref_column}")
        lines.append(
            f"  \"{fk.src_table}\":\"{src_port}\" -> \"{fk.ref_table}\":\"{ref_port}\" "
            f"[label=\"{edge_label}\", color=\"#64748b\"];"
        )

    lines.append("}")
    return "\n".join(lines) + "\n"


def _render_dot_to_png(dot: str, out_png: str) -> Tuple[str, str]:
    if shutil.which("dot") is None:
        raise RuntimeError("Graphviz 'dot' is not installed or not on PATH.")

    out_dir = os.path.dirname(os.path.abspath(out_png)) or "."
    os.makedirs(out_dir, exist_ok=True)

    dot_path = os.path.splitext(out_png)[0] + ".dot"
    with open(dot_path, "w", encoding="utf-8") as f:
        f.write(dot)

    cmd = ["dot", "-Tpng", dot_path, "-o", out_png]
    subprocess.check_call(cmd)
    return dot_path, out_png


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-url", default=DEFAULT_DB_URL, help="PostgreSQL connection URL")
    ap.add_argument("--schema", default="public", help="Schema to introspect (default: public)")
    ap.add_argument("--out", default="Doc/db_schema.png", help="Output PNG path")
    args = ap.parse_args()

    conn = psycopg2.connect(args.db_url)
    try:
        tables = _fetch_tables(conn, args.schema)
        pks = _fetch_primary_keys(conn, args.schema)
        fks = _fetch_foreign_keys(conn, args.schema)

        columns_by_table: Dict[str, List[Column]] = {}
        for t in tables:
            cols = _fetch_columns(conn, args.schema, t)
            pk_cols = set(pks.get(t, []))
            cols2 = [
                Column(
                    name=c.name,
                    data_type=c.data_type,
                    is_nullable=c.is_nullable,
                    default=c.default,
                    is_pk=(c.name in pk_cols),
                )
                for c in cols
            ]
            columns_by_table[t] = cols2

        dot = _build_dot(args.schema, tables, columns_by_table, fks)
        dot_path, png_path = _render_dot_to_png(dot, args.out)

        print(f"OK: wrote {png_path}")
        print(f"DOT: {dot_path}")
        print(f"Tables: {len(tables)} | FKs: {len(fks)}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

