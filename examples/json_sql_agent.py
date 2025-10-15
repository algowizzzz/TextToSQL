#!/usr/bin/env python3
"""
LangGraph Agent for JSON-to-SQL with Self-Correction

Multi-turn agent that:
1. Generates SQL from natural language
2. Executes SQL and returns results
3. Reviews results and decides to refine or exit
4. Loops back for refinement up to max_turns

Usage:
    python json_sql_agent.py --form input/form.json --q "your question"
"""

from __future__ import annotations
import os
import sys
import json
import argparse
import time
from typing import TypedDict, Annotated, Optional, Any, Dict, List
from operator import add

import duckdb
import pandas as pd
from dotenv import load_dotenv

# LangGraph imports
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

# Import helpers from stateless version
sys.path.insert(0, os.path.dirname(__file__))
from json_sql_copilot import (
    load_form,
    register_tables,
    sanitize_sql,
    build_schema_text,
    build_vocabulary_text,
)

load_dotenv()


# ========================================
# Agent State
# ========================================

class AgentState(TypedDict):
    """State maintained across agent turns"""
    # Input
    user_request: str
    form: Dict[str, Any]
    
    # Execution state
    turn: int
    max_turns: int
    sql: Optional[str]
    sql_final: Optional[str]
    previous_sql: Optional[str]
    
    # Results
    results_df: Optional[pd.DataFrame]
    row_count: int
    columns: List[str]
    error: Optional[str]
    
    # Decision
    decision: str  # "REFINE" or "EXIT"
    feedback: Optional[str]
    
    # History (for logging)
    history: Annotated[List[Dict], add]


# ========================================
# Node 1: SQL Generation
# ========================================

def generate_sql_node(state: AgentState) -> Dict:
    """Generate SQL from user query (or refine based on feedback)"""
    print(f"\n{'='*70}")
    print(f"🔧 TURN {state['turn'] + 1}: SQL Generation")
    print(f"{'='*70}")
    
    form = state["form"]
    user_request = state["user_request"]
    turn = state["turn"]
    
    # Build schema context
    schema_text = build_schema_text(form)
    vocab_text = build_vocabulary_text(form)
    
    # Get LLM
    model_cfg = form.get("model", {})
    llm = ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", model_cfg.get("name", "gpt-4o-mini")),
        temperature=model_cfg.get("temperature", 0.0)
    )
    
    # Build prompt based on turn
    if turn == 0:
        # First attempt: use system prompt from config
        system_prompt = form["prompts"]["system"]
        user_prompt = form["prompts"]["user_template"].format(
            schema_text=schema_text,
            vocabulary=vocab_text,
            user_request=user_request,
            dialect_hint=form["prompts"]["dialect_hint"],
            default_limit=form["limits"]["default_limit"]
        )
    else:
        # Refinement attempt
        agent_config = form["agent"]
        system_prompt = agent_config["system_prompt"]
        user_prompt = agent_config["refinement_template"].format(
            previous_sql=state["previous_sql"],
            row_count=state["row_count"],
            feedback=state["feedback"],
            schema_hint=f"{schema_text[:500]}..."  # Abbreviated
        )
    
    print(f"📝 Generating SQL (attempt {turn + 1})...")
    
    # Call LLM
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt)
    ]
    
    response = llm.invoke(messages)
    sql_raw = response.content.strip()
    
    # Clean SQL (remove markdown, explanatory text, etc.)
    # Extract SQL from markdown code blocks
    if "```sql" in sql_raw.lower():
        # Extract SQL from code block
        import re
        match = re.search(r'```sql\s*(.*?)\s*```', sql_raw, re.DOTALL | re.IGNORECASE)
        if match:
            sql_raw = match.group(1).strip()
    elif "```" in sql_raw:
        # Generic code block
        import re
        match = re.search(r'```\s*(.*?)\s*```', sql_raw, re.DOTALL)
        if match:
            sql_raw = match.group(1).strip()
    
    # Remove any leading SQL: or sql: labels
    if sql_raw.lower().startswith("sql:"):
        sql_raw = sql_raw[4:].strip()
    elif sql_raw.lower().startswith("sql"):
        sql_raw = sql_raw[3:].strip()
    
    # Remove any trailing explanatory text (after the query ends with semicolon)
    if ";" in sql_raw:
        # Take everything up to and including the last semicolon
        sql_raw = sql_raw[:sql_raw.rindex(";") + 1].strip()
    
    print(f"✅ SQL Generated:\n{sql_raw[:200]}...")
    
    return {
        "sql": sql_raw,
        "previous_sql": state.get("sql"),  # Save for next iteration
        "turn": turn + 1,
        "history": [{
            "turn": turn + 1,
            "stage": "generate",
            "sql": sql_raw
        }]
    }


# ========================================
# Node 2: SQL Execution
# ========================================

def execute_sql_node(state: AgentState) -> Dict:
    """Execute SQL and return results"""
    print(f"\n🔍 Executing SQL...")
    
    form = state["form"]
    sql_raw = state["sql"]
    limits = form["limits"]
    
    # Apply SQL guardrails
    try:
        sql_final, warnings = sanitize_sql(
            sql_raw,
            allow_non_select=limits["allow_non_select"],
            default_limit=limits["default_limit"],
            hard_max_rows=limits["hard_max_rows"]
        )
    except Exception as e:
        print(f"❌ SQL Sanitization Error: {e}")
        return {
            "sql_final": sql_raw,
            "results_df": None,
            "row_count": 0,
            "columns": [],
            "error": f"SQL sanitization failed: {str(e)}",
            "history": [{
                "turn": state["turn"],
                "stage": "execute",
                "error": str(e)
            }]
        }
    
    # Execute SQL
    con = duckdb.connect(database=":memory:")
    try:
        register_tables(con, form)
        
        exec_start = time.time()
        results_df = con.execute(sql_final).fetch_df()
        exec_time = time.time() - exec_start
        
        row_count = len(results_df)
        columns = list(results_df.columns)
        
        print(f"✅ Execution successful: {row_count} rows in {exec_time:.2f}s")
        
        return {
            "sql_final": sql_final,
            "results_df": results_df,
            "row_count": row_count,
            "columns": columns,
            "error": None,
            "history": [{
                "turn": state["turn"],
                "stage": "execute",
                "row_count": row_count,
                "exec_time_ms": int(exec_time * 1000)
            }]
        }
        
    except Exception as e:
        print(f"❌ Execution Error: {e}")
        return {
            "sql_final": sql_final,
            "results_df": None,
            "row_count": 0,
            "columns": [],
            "error": str(e),
            "history": [{
                "turn": state["turn"],
                "stage": "execute",
                "error": str(e)
            }]
        }
    finally:
        con.close()


# ========================================
# Node 3: Review & Decision (Exit Node)
# ========================================

def review_node(state: AgentState) -> Dict:
    """Review results and decide: REFINE or EXIT"""
    print(f"\n🔎 Reviewing Results...")
    
    form = state["form"]
    agent_config = form["agent"]
    max_turns = agent_config["max_turns"]
    turn = state["turn"]
    
    # Check max turns
    if turn >= max_turns:
        print(f"⚠️  Max turns ({max_turns}) reached. Exiting.")
        return {
            "decision": "EXIT",
            "feedback": agent_config["fallback_message"].format(max_turns=max_turns),
            "history": [{
                "turn": turn,
                "stage": "review",
                "decision": "EXIT",
                "reason": "max_turns_reached"
            }]
        }
    
    # Check execution errors
    if state["error"]:
        print(f"❌ SQL Error detected: {state['error']}")
        feedback = f"REFINE: SQL execution failed with error: {state['error']}"
        return {
            "decision": "REFINE",
            "feedback": feedback,
            "history": [{
                "turn": turn,
                "stage": "review",
                "decision": "REFINE",
                "reason": "sql_error"
            }]
        }
    
    # Evaluate result quality with LLM
    exit_config = agent_config["exit_node"]
    
    # Prepare data preview
    df = state["results_df"]
    data_preview = "EMPTY" if df is None or len(df) == 0 else df.head(5).to_string()
    
    user_prompt = exit_config["user_template"].format(
        user_request=state["user_request"],
        sql=state["sql_final"],
        row_count=state["row_count"],
        data_preview=data_preview
    )
    
    # Call LLM for evaluation
    model_cfg = form.get("model", {})
    llm = ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", model_cfg.get("name", "gpt-4o-mini")),
        temperature=0.3  # Slightly higher for evaluation
    )
    
    messages = [
        SystemMessage(content=exit_config["system_prompt"]),
        HumanMessage(content=user_prompt)
    ]
    
    response = llm.invoke(messages)
    evaluation = response.content.strip()
    
    print(f"📊 Evaluation: {evaluation[:100]}...")
    
    # Parse decision
    if evaluation.upper().startswith("GOOD"):
        print(f"✅ Results approved. Exiting.")
        return {
            "decision": "EXIT",
            "feedback": None,
            "history": [{
                "turn": turn,
                "stage": "review",
                "decision": "EXIT",
                "evaluation": evaluation
            }]
        }
    else:
        print(f"🔄 Refinement needed: {evaluation[:100]}...")
        return {
            "decision": "REFINE",
            "feedback": evaluation,
            "history": [{
                "turn": turn,
                "stage": "review",
                "decision": "REFINE",
                "evaluation": evaluation
            }]
        }


# ========================================
# Build LangGraph
# ========================================

def build_agent_graph() -> StateGraph:
    """Build the LangGraph agent with 3 nodes"""
    
    graph = StateGraph(AgentState)
    
    # Add nodes
    graph.add_node("generate", generate_sql_node)
    graph.add_node("execute", execute_sql_node)
    graph.add_node("review", review_node)
    
    # Define edges
    graph.set_entry_point("generate")
    graph.add_edge("generate", "execute")
    graph.add_edge("execute", "review")
    
    # Conditional edge from review
    graph.add_conditional_edges(
        "review",
        lambda state: state["decision"],
        {
            "EXIT": END,
            "REFINE": "generate"
        }
    )
    
    return graph.compile()


# ========================================
# Main Runner
# ========================================

def run_agent(form: Dict[str, Any], user_request: str) -> Dict[str, Any]:
    """Run the LangGraph agent"""
    
    agent_config = form.get("agent", {})
    if not agent_config.get("enabled", False):
        agent_config["enabled"] = True  # Enable if using agent script
    
    # Initialize state
    initial_state = {
        "user_request": user_request,
        "form": form,
        "turn": 0,
        "max_turns": agent_config.get("max_turns", 3),
        "sql": None,
        "sql_final": None,
        "previous_sql": None,
        "results_df": None,
        "row_count": 0,
        "columns": [],
        "error": None,
        "decision": "",
        "feedback": None,
        "history": []
    }
    
    # Build and run graph
    print(f"\n{'='*70}")
    print(f"🤖 Starting LangGraph Agent")
    print(f"{'='*70}")
    print(f"Query: {user_request}")
    print(f"Max turns: {initial_state['max_turns']}")
    
    agent = build_agent_graph()
    
    start_time = time.time()
    final_state = agent.invoke(initial_state)
    total_time = time.time() - start_time
    
    # Format result
    result = {
        "user_request": user_request,
        "sql_generated": final_state.get("sql"),
        "sql_executed": final_state.get("sql_final"),
        "columns": final_state.get("columns", []),
        "row_count": final_state.get("row_count", 0),
        "rows": final_state["results_df"].head(form["limits"]["hard_max_rows"]).values.tolist() 
                if final_state.get("results_df") is not None else [],
        "turns_taken": final_state.get("turn", 0),
        "error": final_state.get("error"),
        "feedback": final_state.get("feedback"),
        "timings_ms": {
            "total": int(total_time * 1000)
        },
        "history": final_state.get("history", [])
    }
    
    return result


# ========================================
# CLI
# ========================================

def main():
    parser = argparse.ArgumentParser(
        description="LangGraph Agent for JSON-to-SQL with self-correction"
    )
    parser.add_argument(
        "--form",
        default="input/form.json",
        help="Path to configuration JSON (default: input/form.json)"
    )
    parser.add_argument(
        "--q",
        required=True,
        help="Natural language query"
    )
    parser.add_argument(
        "--print-sql",
        action="store_true",
        help="Print generated SQL"
    )
    
    args = parser.parse_args()
    
    # Check for OpenAI API key
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ Error: OPENAI_API_KEY not set. LangGraph agent requires LLM.")
        print("   Export it: export OPENAI_API_KEY=sk-...")
        sys.exit(1)
    
    # Load configuration
    print(f"📋 Loading configuration from: {args.form}")
    form = load_form(args.form)
    
    # Run agent
    try:
        result = run_agent(form, args.q)
        
        # Print SQL if requested
        if args.print_sql:
            print(f"\n{'='*70}")
            print(f"--- SQL (final) ---")
            print(result["sql_executed"])
            print(f"{'='*70}")
        
        # Print result
        print(f"\n{'='*70}")
        print(f"📊 RESULT")
        print(f"{'='*70}")
        print(json.dumps({
            "columns": result["columns"],
            "row_count": result["row_count"],
            "rows": result["rows"],
            "turns_taken": result["turns_taken"],
            "timings_ms": result["timings_ms"]
        }, indent=2, default=str))
        
        if result.get("error"):
            print(f"\n⚠️  Final error: {result['error']}")
        
        if result.get("feedback"):
            print(f"\n💬 Feedback: {result['feedback']}")
        
        print(f"\n🔍 Agent took {result['turns_taken']} turn(s)")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

