# json_sql_copilot.py
# Stateless JSON-to-SQL calculator using DuckDB
# Single source of truth: input/form.json

from __future__ import annotations
import os
import re
import csv
import io
import time
import json
import argparse
from typing import Any, Dict, List, Tuple, Optional
from pathlib import Path

import duckdb
import pandas as pd

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# =========================================
# Form loader
# =========================================

def load_form(path: str = "input/form.json") -> Dict[str, Any]:
    """Load BA input form - single source of truth."""
    with open(path, "r") as f:
        return json.load(f)

def expand_env_vars(text: str) -> str:
    """Expand ${VAR} style environment variables in strings."""
    def replacer(match):
        var_name = match.group(1)
        return os.getenv(var_name, match.group(0))
    return re.sub(r'\$\{([^}]+)\}', replacer, text)

# =========================================
# Data loading (file or API)
# =========================================

def fetch_json(url: str, headers: Dict[str, str] = None, timeout: int = 30) -> Dict[str, Any]:
    """Fetch JSON from REST API."""
    import requests
    
    # Expand environment variables in headers
    if headers:
        headers = {k: expand_env_vars(v) for k, v in headers.items()}
    
    r = requests.get(url, headers=headers or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()

def df_from_csv_rows_in_json(
    payload: Dict[str, Any],
    *,
    columns_key: str = "columns",
    row_key: str = "rows",
    field_key: Optional[str] = None,
    delimiter: str = ","
) -> pd.DataFrame:
    """Parse JSON payload where data is CSV strings embedded in JSON."""
    # 1) Get column names (header)
    header = payload.get(columns_key)
    if not header or not isinstance(header, list):
        raise ValueError(f"Missing or invalid '{columns_key}' array in JSON payload.")
    
    # 2) Get rows (CSV strings or objects containing CSV strings)
    raw_rows = payload.get(row_key, [])
    if not raw_rows:
        return pd.DataFrame(columns=header)
    
    lines: List[str] = []
    if field_key is None:
        lines = [str(r) for r in raw_rows]
    else:
        lines = [str(r.get(field_key, "")) for r in raw_rows]
    
    # 3) Parse with csv.reader (handles quotes and embedded commas)
    reader = csv.reader(lines, delimiter=delimiter)
    records = []
    for row in reader:
        if len(row) == len(header):
            records.append(dict(zip(header, row)))
        else:
            if len(row) < len(header):
                row.extend([""] * (len(header) - len(row)))
            records.append(dict(zip(header, row[:len(header)])))
    
    # 4) Create DataFrame
    df = pd.DataFrame.from_records(records, columns=header)
    
    # 5) Type coercion for common column patterns
    numeric_patterns = ["exposure_", "limit_", "mtm", "pnl", "notional", "delta", "gamma", "vega", "_pct", "_var", "_stress"]
    numeric_cols = [c for c in df.columns if any(pat in c for pat in numeric_patterns)]
    for c in numeric_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    
    date_cols = [c for c in df.columns if c.endswith("_date") or c.endswith("_asof") or "as_of" in c]
    for c in date_cols:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    
    bool_cols = [c for c in df.columns if c.endswith("_flag") or c == "collateralized"]
    for c in bool_cols:
        if c in df.columns:
            df[c] = df[c].astype(str).str.lower().map({"true": True, "false": False, "1": True, "0": False})
    
    return df

def load_table_from_api(source: Dict[str, Any]) -> pd.DataFrame:
    """Load table from API based on format specification."""
    fmt = source.get("format", "array_of_objects")
    url = source["url"]
    headers = source.get("headers")
    
    if fmt == "array_of_objects":
        payload = fetch_json(url, headers)
        data = payload if isinstance(payload, list) else payload.get("data", [])
        return pd.json_normalize(data)
    
    elif fmt == "csv_rows_in_json":
        payload = fetch_json(url, headers)
        return df_from_csv_rows_in_json(
            payload,
            columns_key=source.get("columns_key", "columns"),
            row_key=source.get("row_key", "rows"),
            field_key=source.get("field_key"),
            delimiter=source.get("delimiter", ","),
        )
    
    elif fmt == "csv_url":
        return pd.read_csv(url)
    
    else:
        raise ValueError(f"Unsupported API format: {fmt}")

def align_columns(df: pd.DataFrame, allowed_cols: List[str]) -> pd.DataFrame:
    """Align DataFrame to schema by adding missing columns and reordering."""
    for c in allowed_cols:
        if c not in df.columns:
            df[c] = None
    return df[allowed_cols]

def load_tables(form: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
    """Load all tables based on form configuration."""
    mode = form["mode"]
    tables_cfg = form["tables"]
    dfs = {}
    
    for table_name, table_cfg in tables_cfg.items():
        cols = table_cfg["columns"]
        source = table_cfg["source"]
        
        if mode == "file":
            # Load from local JSON file
            file_path = Path(source["file_path"])
            with open(file_path, "r") as f:
                data = json.load(f)
            df = pd.json_normalize(data)
        
        elif mode == "api":
            # Load from API
            df = load_table_from_api(source)
        
        else:
            raise ValueError(f"Invalid mode: {mode}. Must be 'file' or 'api'.")
        
        dfs[table_name] = align_columns(df, cols)
    
    return dfs

# =========================================
# Schema and vocabulary builders
# =========================================

def build_schema_text(form: Dict[str, Any]) -> str:
    """Build schema description for LLM prompt."""
    lines = []
    for table_name, table_cfg in form["tables"].items():
        cols = ", ".join(table_cfg["columns"])
        lines.append(f"{table_name}({cols})")
    return "\n".join(lines)

def build_vocabulary_text(form: Dict[str, Any]) -> str:
    """Build vocabulary hints for LLM prompt."""
    vocab = form.get("vocabulary", {})
    # Filter out comment keys
    vocab = {k: v for k, v in vocab.items() if not k.startswith("_")}
    lines = [f"- {k} -> {v}" for k, v in vocab.items()]
    return "\n".join(lines) if lines else "(none)"

# =========================================
# LLM integration (optional)
# =========================================

def have_openai() -> bool:
    try:
        import openai  # noqa: F401
        return True
    except Exception:
        return False

class OpenAIAdapter:
    def __init__(self, model: str = "gpt-4o-mini", temperature: float = 0.0):
        from openai import OpenAI
        self.client = OpenAI()
        self.model = model
        self.temperature = temperature

    def generate_sql(self, system_prompt: str, user_prompt: str) -> str:
        rsp = self.client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return rsp.choices[0].message.content.strip()

# =========================================
# SQL guardrails
# =========================================

SELECT_ONLY_RE = re.compile(r"^\s*(with\b|select\b)", re.IGNORECASE | re.DOTALL)
MULTI_STMT_RE = re.compile(r";\s*[^;\s]")

def sanitize_sql(sql: str, allow_non_select: bool, default_limit: int, hard_max_rows: int) -> Tuple[str, List[str]]:
    """Apply guardrails to SQL."""
    warnings: List[str] = []
    sql = sql.strip().strip("`")
    if sql.lower().startswith("sql"):
        sql = sql[3:].lstrip(":").strip()

    if MULTI_STMT_RE.search(sql):
        raise ValueError("Multiple statements detected; a single SELECT/CTE statement is required.")

    if not allow_non_select and not SELECT_ONLY_RE.match(sql):
        raise ValueError("Only SELECT/CTE queries are allowed.")

    lowered = re.sub(r"\s+", " ", sql.lower())
    has_limit = " limit " in lowered and not lowered.rstrip().endswith(")")

    if not has_limit:
        sql = f"{sql.rstrip().rstrip(';')} LIMIT {default_limit}"
        warnings.append(f"LIMIT {default_limit} added.")

    m = re.search(r"\blimit\s+(\d+)\b", sql, re.IGNORECASE)
    if m and int(m.group(1)) > hard_max_rows:
        sql = re.sub(r"\blimit\s+\d+\b", f"LIMIT {hard_max_rows}", sql, flags=re.IGNORECASE)
        warnings.append(f"LIMIT clamped to {hard_max_rows}.")
    
    return sql, warnings

# =========================================
# SQL generation
# =========================================

def build_prompts(form: Dict[str, Any], user_request: str) -> Tuple[str, str]:
    """Build LLM prompts from form."""
    prompts = form["prompts"]
    dialect = prompts["dialect_hint"]
    default_limit = form["limits"]["default_limit"]
    
    system_prompt = prompts["system"].format(dialect_hint=dialect)
    
    user_prompt = prompts["user_template"].format(
        schema_text=build_schema_text(form),
        vocabulary=build_vocabulary_text(form),
        dialect_hint=dialect,
        user_request=user_request.strip(),
        default_limit=default_limit,
    )
    
    return system_prompt, user_prompt

def generate_sql(form: Dict[str, Any], user_request: str, use_llm: bool) -> str:
    """Generate SQL from natural language request."""
    if use_llm:
        if not have_openai():
            raise RuntimeError("OpenAI package not installed. Run `pip install openai` or disable --use-llm.")
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY not set. Export it or disable --use-llm.")
        
        model_cfg = form["model"]
        llm = OpenAIAdapter(
            model=os.getenv("OPENAI_MODEL", model_cfg["name"]),
            temperature=model_cfg["temperature"]
        )
        sys_p, usr_p = build_prompts(form, user_request)
        return llm.generate_sql(sys_p, usr_p)
    
    # Fallback: rule-based queries
    key = user_request.strip().lower()
    rule_queries = form.get("rule_based_queries", {})
    # Filter out comment keys
    rule_queries = {k: v for k, v in rule_queries.items() if not k.startswith("_")}
    
    if key in rule_queries:
        return rule_queries[key]
    
    raise ValueError(
        f"No rule-based SQL for query: '{user_request}'. "
        f"Try one of: {list(rule_queries.keys())} or use --use-llm."
    )

# =========================================
# Query runner
# =========================================

def run_query(form: Dict[str, Any], user_request: str, use_llm: bool = False) -> Dict[str, Any]:
    """Execute natural language query and return results."""
    t0 = time.time()
    
    limits = form["limits"]
    
    # 1) Generate SQL
    sql_raw = generate_sql(form, user_request, use_llm=use_llm)
    
    # 2) Apply guardrails
    sql_final, warnings = sanitize_sql(
        sql_raw,
        allow_non_select=limits["allow_non_select"],
        default_limit=limits["default_limit"],
        hard_max_rows=limits["hard_max_rows"],
    )
    
    # 3) Load data and execute
    dfs = load_tables(form)
    con = duckdb.connect(database=":memory:")
    try:
        for tname, df in dfs.items():
            con.register(tname, df)
        
        exec_t0 = time.time()
        res_df: pd.DataFrame = con.execute(sql_final).fetch_df()
        exec_ms = int((time.time() - exec_t0) * 1000)
    finally:
        con.close()
    
    return {
        "sql_generated": sql_raw.strip(),
        "sql_executed": sql_final.strip(),
        "columns": list(res_df.columns),
        "rows": res_df.head(limits["hard_max_rows"]).values.tolist(),
        "row_count": len(res_df),
        "timings_ms": {
            "total": int((time.time() - t0) * 1000),
            "execution": exec_ms
        },
        "warnings": warnings,
        "dialect": form["prompts"]["dialect_hint"],
        "mode": form["mode"],
    }

# =========================================
# CLI
# =========================================

def main():
    ap = argparse.ArgumentParser(
        description="Stateless JSON-to-SQL copilot - single form configuration"
    )
    ap.add_argument("--q", required=True, help="Natural language request")
    ap.add_argument("--use-llm", action="store_true", help="Use OpenAI to generate SQL (requires OPENAI_API_KEY)")
    ap.add_argument("--print-sql", action="store_true", help="Print the generated & executed SQL")
    ap.add_argument("--form", default="input/form.json", help="Path to form.json (default: input/form.json)")
    args = ap.parse_args()
    
    # Load form
    print(f"📋 Loading configuration from: {args.form}")
    form = load_form(args.form)
    
    # Run query
    out = run_query(form, args.q, use_llm=args.use_llm)
    
    if args.print_sql:
        print("\n--- SQL (generated) ---\n", out["sql_generated"])
        print("\n--- SQL (executed) ---\n", out["sql_executed"])
    
    # Pretty print result
    print("\n--- RESULT ---")
    print(json.dumps({
        "mode": out["mode"],
        "columns": out["columns"],
        "row_count": out["row_count"],
        "rows": out["rows"],
        "warnings": out["warnings"],
        "timings_ms": out["timings_ms"],
    }, indent=2, default=str))

if __name__ == "__main__":
    main()
