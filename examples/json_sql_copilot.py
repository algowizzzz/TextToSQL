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

def register_tables(con: duckdb.DuckDBPyConnection, form: Dict[str, Any]) -> None:
    """Register all tables in DuckDB based on form configuration.
    
    For Parquet files: Uses DuckDB native reads (zero-copy, blazing fast)
    Supports glob patterns for partitioned files (e.g., data_*.parquet)
    For API: Loads to pandas DataFrame first, then registers
    """
    mode = form["mode"]
    tables_cfg = form["tables"]
    
    for table_name, table_cfg in tables_cfg.items():
        cols = table_cfg["columns"]
        source = table_cfg["source"]
        
        if mode == "parquet":
            # DuckDB native Parquet read (zero-copy, no pandas needed!)
            file_path = source["file_path"]
            
            # Support glob patterns for partitioned files
            # DuckDB's read_parquet handles globs automatically
            # e.g., 'data_*.parquet' reads all matching files
            col_list = ", ".join(cols)
            con.execute(f"CREATE OR REPLACE VIEW {table_name} AS SELECT {col_list} FROM read_parquet('{file_path}')")
        
        elif mode == "api":
            # Load from API to pandas, then register
            df = load_table_from_api(source)
            df = align_columns(df, cols)
            con.register(table_name, df)
        
        else:
            raise ValueError(f"Invalid mode: {mode}. Must be 'parquet' or 'api'.")

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
    """Adapter for OpenAI API with support for reasoning models (o1/o1-mini)."""
    def __init__(self, model: str = "gpt-4o-mini", temperature: float = 0.0):
        from openai import OpenAI
        self.client = OpenAI()
        self.model = model
        self.temperature = temperature
        # o1 models don't support system prompts or temperature
        self.is_reasoning_model = model.startswith("o1")

    def generate_sql(self, system_prompt: str, user_prompt: str) -> str:
        if self.is_reasoning_model:
            # o1 models: combine system + user into single user message
            combined_prompt = f"{system_prompt}\n\n{user_prompt}"
            rsp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": combined_prompt},
                ],
            )
        else:
            # Standard models: separate system and user messages
            rsp = self.client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        return rsp.choices[0].message.content.strip()
    
    def generate_commentary(self, system_prompt: str, user_prompt: str, temperature: float = 0.3) -> str:
        """Generate natural language commentary about query results."""
        if self.is_reasoning_model:
            # o1 models: combine system + user into single user message
            combined_prompt = f"{system_prompt}\n\n{user_prompt}"
            rsp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": combined_prompt},
                ],
            )
        else:
            # Standard models: separate system and user messages
            rsp = self.client.chat.completions.create(
                model=self.model,
                temperature=temperature,
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

def extract_reference_values(form: Dict[str, Any]) -> Dict[str, Dict[str, List[str]]]:
    """Extract unique values from specified columns for LLM context.
    
    Returns dict like: {"ccr_limits": {"customer_name": ["Aurora Metals", ...], ...}, ...}
    """
    ref_config = form.get("reference_values", {})
    
    if not ref_config.get("enabled", False):
        return {}
    
    # Only works with parquet mode
    if form.get("mode") != "parquet":
        return {}
    
    max_values = ref_config.get("max_values_per_column", 20)
    result = {}
    
    con = duckdb.connect(":memory:")
    
    try:
        for table_name, table_config in ref_config.get("tables", {}).items():
            # Get file path from tables.{table_name}.source.file_path
            tables = form.get("tables", {})
            if table_name not in tables:
                continue
            
            table_def = tables[table_name]
            source = table_def.get("source", {})
            file_path = source.get("file_path")
            
            if not file_path:
                continue
            
            result[table_name] = {}
            
            for column in table_config.get("columns", []):
                try:
                    query = f"""
                        SELECT DISTINCT {column} 
                        FROM read_parquet('{file_path}')
                        WHERE {column} IS NOT NULL
                        ORDER BY {column}
                        LIMIT {max_values}
                    """
                    values = con.execute(query).fetchall()
                    result[table_name][column] = [str(v[0]) for v in values]
                except Exception as e:
                    # Silently skip columns that don't exist or fail
                    result[table_name][column] = []
    finally:
        con.close()
    
    return result

def build_system_prompt_with_references(form: Dict[str, Any], ref_values: Dict[str, Dict[str, List[str]]]) -> str:
    """Build system prompt with reference values injected."""
    prompts = form["prompts"]
    dialect = prompts["dialect_hint"]
    base_prompt = prompts["system"].format(dialect_hint=dialect)
    
    if not ref_values:
        return base_prompt
    
    # Build reference section
    ref_lines = ["\n\nREFERENCE VALUES (actual data in tables):"]
    
    for table_name, columns in ref_values.items():
        if not columns:
            continue
        ref_lines.append(f"\n{table_name}:")
        for column, values in columns.items():
            if not values:
                continue
            # Show first 10, indicate if more
            display_values = values[:10]
            values_str = ", ".join(f'"{v}"' for v in display_values)
            if len(values) > 10:
                values_str += f" ... ({len(values)} total)"
            ref_lines.append(f"  - {column}: {values_str}")
    
    return base_prompt + "".join(ref_lines)

def build_prompts(form: Dict[str, Any], user_request: str, ref_values: Optional[Dict[str, Dict[str, List[str]]]] = None) -> Tuple[str, str]:
    """Build LLM prompts from form."""
    prompts = form["prompts"]
    dialect = prompts["dialect_hint"]
    default_limit = form["limits"]["default_limit"]
    
    # Build system prompt with reference values if provided
    if ref_values:
        system_prompt = build_system_prompt_with_references(form, ref_values)
    else:
        system_prompt = prompts["system"].format(dialect_hint=dialect)
    
    user_prompt = prompts["user_template"].format(
        schema_text=build_schema_text(form),
        vocabulary=build_vocabulary_text(form),
        dialect_hint=dialect,
        user_request=user_request.strip(),
        default_limit=default_limit,
    )
    
    return system_prompt, user_prompt

def extract_filters_from_query(form: Dict[str, Any], user_request: str, llm: 'OpenAIAdapter') -> Optional[str]:
    """Two-stage optimization: Extract WHERE clause filters first (Stage 1).
    
    This reduces LLM costs by 30-50% and improves query performance by pushing
    filters down early to DuckDB's Parquet reader.
    """
    filter_system = """You are a SQL expert. Extract WHERE clause conditions from natural language queries.
Return ONLY the WHERE clause conditions (no SELECT, FROM, etc). If no filters, return 'NONE'."""
    
    # Build context about schema and vocabulary
    schema_text = build_schema_text(form)
    vocab_text = build_vocabulary_text(form)
    
    filter_user = f"""SCHEMA:
{schema_text}

VOCABULARY:
{vocab_text}

USER REQUEST: "{user_request}"

Extract the WHERE clause conditions that would filter the data. 
Return ONLY the conditions (e.g., "as_of_date >= '2025-10-01' AND limit_utilization_pct > 100").
If no specific filters, return "NONE"."""
    
    try:
        filters = llm.generate_sql(filter_system, filter_user)
        if filters.upper().strip() == "NONE" or not filters.strip():
            return None
        return filters.strip()
    except Exception:
        return None

def generate_sql(form: Dict[str, Any], user_request: str, use_llm: bool) -> str:
    """Generate SQL from natural language request.
    
    If two_stage_optimizer is enabled, extracts filters first for better performance.
    """
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
        
        # Extract reference values for LLM context (done once at generation time)
        ref_values = extract_reference_values(form)
        
        # Check if two-stage optimization is enabled
        use_two_stage = form.get("optimization", {}).get("two_stage_optimizer", False)
        
        if use_two_stage:
            # Stage 1: Extract filters (fast, cheap)
            filters = extract_filters_from_query(form, user_request, llm)
            
            # Stage 2: Generate SQL with filter hints
            if filters:
                sys_p, usr_p = build_prompts(form, user_request, ref_values)
                # Enhance prompt with extracted filters
                usr_p += f"\n\nHINT: Apply these filters early: {filters}"
                return llm.generate_sql(sys_p, usr_p)
        
        # Standard single-stage generation
        sys_p, usr_p = build_prompts(form, user_request, ref_values)
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

def generate_commentary(form: Dict[str, Any], user_request: str, result: Dict[str, Any]) -> Optional[str]:
    """Generate natural language commentary about query results using LLM."""
    commentary_cfg = form.get("commentary", {})
    
    if not commentary_cfg.get("enabled", False):
        return None
    
    if not have_openai():
        return None
    
    if not os.getenv("OPENAI_API_KEY"):
        return None
    
    # Prepare data preview
    max_rows = commentary_cfg.get("max_rows_in_prompt", 20)
    sample_rows = result["rows"][:max_rows]
    
    # Format data as readable text
    data_lines = []
    for i, row in enumerate(sample_rows, 1):
        row_dict = dict(zip(result["columns"], row))
        # Format row compactly
        row_str = ", ".join([f"{k}={v}" for k, v in row_dict.items()])
        data_lines.append(f"{i}. {row_str}")
    
    data_preview = "\n".join(data_lines)
    
    # Build prompts
    system_prompt = commentary_cfg.get(
        "system_prompt",
        "You are a data analyst providing concise insights. Be specific and focus on key findings."
    )
    
    user_template = commentary_cfg.get(
        "user_template",
        "USER REQUEST: \"{user_request}\"\n\nRESULTS ({row_count} rows):\n{data_preview}\n\nProvide brief commentary (3-5 sentences)."
    )
    
    user_prompt = user_template.format(
        user_request=user_request,
        row_count=result["row_count"],
        columns=", ".join(result["columns"]),
        sample_size=len(sample_rows),
        data_preview=data_preview
    )
    
    # Generate commentary
    try:
        model_cfg = form["model"]
        llm = OpenAIAdapter(
            model=os.getenv("OPENAI_MODEL", model_cfg["name"]),
            temperature=model_cfg.get("temperature", 0.0)
        )
        commentary_t0 = time.time()
        commentary_text = llm.generate_commentary(system_prompt, user_prompt, temperature=0.3)
        commentary_ms = int((time.time() - commentary_t0) * 1000)
        
        return {
            "text": commentary_text,
            "generation_time_ms": commentary_ms
        }
    except Exception as e:
        # Silently fail - commentary is optional
        return {
            "text": f"[Commentary generation failed: {str(e)}]",
            "generation_time_ms": 0
        }

def run_query(form: Dict[str, Any], user_request: str, use_llm: bool = False, with_commentary: bool = False) -> Dict[str, Any]:
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
    
    # 3) Register tables and execute query
    con = duckdb.connect(database=":memory:")
    try:
        register_tables(con, form)
        
        exec_t0 = time.time()
        try:
            res_df: pd.DataFrame = con.execute(sql_final).fetch_df()
            exec_ms = int((time.time() - exec_t0) * 1000)
        except duckdb.BinderException as e:
            error_msg = str(e)
            
            # Provide user-friendly hints for common errors
            if "as_of_date" in error_msg and ("TIMESTAMP" in error_msg or "DATE" in error_msg):
                raise RuntimeError(
                    f"❌ Date type mismatch error.\n"
                    f"Hint: as_of_date is stored as VARCHAR. Use CAST(as_of_date AS DATE) for comparisons,\n"
                    f"      or use the 'latest' or 'recent' vocabulary mappings.\n\n"
                    f"Original error: {error_msg}"
                ) from e
            
            if "limit_utilization_pct" in error_msg and "trades" in error_msg:
                raise RuntimeError(
                    f"❌ Column ownership error.\n"
                    f"Hint: limit_utilization_pct exists ONLY in ccr_limits, NOT in trades.\n"
                    f"      Filter by ccr_limits.limit_utilization_pct instead.\n\n"
                    f"Original error: {error_msg}"
                ) from e
            
            if "does not have a column" in error_msg or "not found" in error_msg:
                raise RuntimeError(
                    f"❌ Column not found in table.\n"
                    f"Hint: Check column ownership in schema:\n"
                    f"      - limit_utilization_pct, exposure_*, limit_*: ONLY in ccr_limits\n"
                    f"      - mtm, notional, product, failed_trade: ONLY in trades\n"
                    f"      - adaptiv_code, as_of_date, currency: In BOTH tables\n\n"
                    f"Original error: {error_msg}"
                ) from e
            
            # Re-raise with original error if no specific hint
            raise
    finally:
        con.close()
    
    result = {
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
    
    # 4) Optional: Generate commentary
    if with_commentary or (use_llm and form.get("commentary", {}).get("enabled", False)):
        commentary = generate_commentary(form, user_request, result)
        if commentary:
            result["commentary"] = commentary
            result["timings_ms"]["commentary"] = commentary.get("generation_time_ms", 0)
    
    return result

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
    ap.add_argument("--with-commentary", action="store_true", help="Generate LLM commentary about results")
    ap.add_argument("--form", default="input/form.json", help="Path to form.json (default: input/form.json)")
    args = ap.parse_args()
    
    # Load form
    print(f"📋 Loading configuration from: {args.form}")
    form = load_form(args.form)
    
    # Run query
    out = run_query(form, args.q, use_llm=args.use_llm, with_commentary=args.with_commentary)
    
    if args.print_sql:
        print("\n--- SQL (generated) ---\n", out["sql_generated"])
        print("\n--- SQL (executed) ---\n", out["sql_executed"])
    
    # Pretty print result
    print("\n--- RESULT ---")
    result_output = {
        "mode": out["mode"],
        "columns": out["columns"],
        "row_count": out["row_count"],
        "rows": out["rows"],
        "warnings": out["warnings"],
        "timings_ms": out["timings_ms"],
    }
    print(json.dumps(result_output, indent=2, default=str))
    
    # Print commentary if available
    if "commentary" in out:
        print("\n" + "="*70)
        print("💡 COMMENTARY")
        print("="*70)
        print(out["commentary"]["text"])
        print("="*70)

if __name__ == "__main__":
    main()
