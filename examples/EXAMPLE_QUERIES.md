# Example Query Sessions
**Real-world test queries demonstrating agent behavior, self-correction, and edge cases**

---

## Table of Contents
1. [Simple Queries (1-2 Turns)](#simple-queries)
2. [Ambiguous Queries (Entity Disambiguation)](#ambiguous-queries)
3. [Complex Multi-Turn Corrections](#complex-multi-turn-corrections)
4. [Granularity Mismatch Issues](#granularity-mismatch-issues)
5. [Key Learnings](#key-learnings)

---

## Simple Queries

### Query 1: Customer Breach Identification

**User Query:** `"show me all customers with ccr pfe exposure above limit"`

**Agent Performance:**
- **Turns:** 3
- **Outcome:** ✅ Success

**Turn-by-Turn:**

| Turn | SQL | Result | Review Decision |
|------|-----|--------|-----------------|
| 1 | `SELECT customer_name FROM ccr_limits WHERE exposure_pfe > limit_ccr` | 2 rows | ❌ REFINE: Missing `exposure_pfe` and `limit_ccr` in SELECT for verification |
| 2 | `SELECT adaptiv_code, customer_name, exposure_pfe, limit_ccr FROM ccr_limits` | 30 rows | ❌ REFINE: Missing WHERE clause to filter for exposure_pfe > limit_ccr |
| 3 | `SELECT customer_name, exposure_pfe, limit_ccr, as_of_date FROM ccr_limits WHERE exposure_pfe > limit_ccr AND CAST(as_of_date AS DATE) = (SELECT MAX(...))` | 2 rows ✅ | ✅ GOOD |

**Final Result:**
```json
{
  "columns": ["customer_name", "exposure_pfe", "limit_ccr", "as_of_date"],
  "row_count": 2,
  "rows": [
    ["Northbridge Capital", 19347458.455355268, 17000000, "2025-10-14"],
    ["Aurora Metals", 11913149.768448714, 10000000, "2025-10-14"]
  ]
}
```

**Commentary Generated:**
- **Northbridge Capital** has a CCR PFE exposure of **19,347,458.46**, which is **2,347,458.46** above the CCR limit of **17,000,000** as of **2025-10-14**.
- **Aurora Metals** has a CCR PFE exposure of **11,913,149.77**, exceeding the CCR limit of **10,000,000** by **1,913,149.77** as of **2025-10-14**.

**Key Insight:** Agent caught missing columns in SELECT and missing WHERE clause, demonstrating review node effectiveness.

---

## Ambiguous Queries

### Query 2: Entity Type Disambiguation (Failed Attempt)

**User Query:** `"sum of notional and pfe by failed trade or not for aurora metal"`

**Agent Performance:**
- **Turns:** 5 (max reached)
- **Outcome:** ❌ Failed (0 rows)

**Turn-by-Turn:**

| Turn | SQL | Result | Review Decision |
|------|-----|--------|-----------------|
| 1 | `WHERE trades.product = 'aurora metal'` | 0 rows | ❌ REFINE: Filter uses exact match, may exclude relevant data |
| 2 | `WHERE product LIKE '%aurora metal%'` | 0 rows | ❌ REFINE: Query does not aggregate, missing JOIN |
| 3 | `JOIN ccr_limits ... WHERE product LIKE '%aurora metal%'` | 0 rows | ❌ REFINE: sum_pfe calculation incorrect |
| 4 | `... WHERE product LIKE '%aurora metal%'` | 0 rows | ❌ REFINE: Missing aggregation and GROUP BY |
| 5 | `... WHERE product LIKE '%aurora metal%'` | 0 rows | ⚠️ Max turns reached |

**Final Result:**
```json
{
  "row_count": 0,
  "rows": []
}
```

**Problem:** Agent incorrectly assumed "aurora metal" was a product type, not recognizing it as a customer name variant.

---

### Query 2b: Entity Type Disambiguation (Successful with Hint)

**User Query:** `"sum of notional and pfe by failed trade or not for aurora metal customer"`  
*(Added "customer" keyword as hint)*

**Agent Performance:**
- **Turns:** 3
- **Outcome:** ✅ Success

**Turn-by-Turn:**

| Turn | SQL | Result | Review Decision |
|------|-----|--------|-----------------|
| 1 | `WHERE ccr_limits.customer_name = 'Aurora Metal'` | 0 rows | ❌ REFINE: Consider using LIKE instead of = |
| 2 | `WHERE ccr_limits.customer_name LIKE '%Aurora Metal%'` | 5 rows | ❌ REFINE: Query does not aggregate (sum) |
| 3 | `SELECT failed_trade, customer_name, SUM(trades.notional), SUM(ccr_limits.exposure_pfe) ... GROUP BY failed_trade, customer_name` | 2 rows ✅ | ✅ GOOD |

**Final Result:**
```json
{
  "columns": ["failed_trade", "customer_name", "total_notional", "total_pfe"],
  "row_count": 2,
  "rows": [
    [true, "Aurora Metals", 124413283.8923648, 114139911.47394484],
    [false, "Aurora Metals", 718534152.1656947, 627769513.1066973]
  ]
}
```

**Commentary Generated:**
- **Failed Trades:** Aurora Metals has a total notional of **$124,413,283.89** and a total PFE of **$114,139,911.47** for failed trades.
- **Non-Failed Trades:** For successful trades, Aurora Metals has a total notional of **$718,534,152.17** and a total PFE of **$627,769,513.11**.
- **Combined Notional:** The overall notional exposure sums to **$842,947,436.06**.
- **Combined PFE:** The total Potential Future Exposure is **$741,909,424.58**.

**Key Insight:** Reference values feature (extracting unique customer names) helps agent correctly identify "Aurora Metals" as a customer after adding the keyword hint.

---

### Query 3: Text Matching Pattern Correction

**User Query:** `"show me all failed trades for fwd"`

**Agent Performance:**
- **Turns:** 5
- **Outcome:** ✅ Success (but struggled)

**Turn-by-Turn:**

| Turn | SQL | Result | Review Decision |
|------|-----|--------|-----------------|
| 1 | `WHERE failed_trade = TRUE AND product = 'fwd'` | 0 rows | ❌ REFINE: Use LIKE instead of = |
| 2 | `WHERE product LIKE '%fwd%'` | 0 rows | ❌ REFINE: Missing filter for failed trades |
| 3 | `WHERE failed_trade = TRUE AND product LIKE '%FWD%'` | 1 row | ❌ REFINE: Query includes LIMIT 200, remove it |
| 4 | `WHERE product LIKE '%fwd%'` | 0 rows | ❌ REFINE: Missing filter for failed trades again |
| 5 | `WHERE failed_trade = TRUE AND product LIKE '%FWD%'` | 1 row ✅ | ⚠️ Max turns reached |

**Final Result:**
```json
{
  "columns": ["trade_id", "product", "failed_trade"],
  "row_count": 1,
  "rows": [
    ["T00071", "FX FWD", true]
  ]
}
```

**Commentary Generated:**
- **Trade Count:** There is **1** failed trade for FX Forward (`product=FX FWD`), identified by `trade_id=T00071`.
- **Failed Trade Status:** The trade is marked as `failed_trade=True`, indicating that the exposure calculation did not succeed.
- **Exposure Impact:** Due to the failed status, the exposure for this trade was conservatively set to its notional value, which may result in **overstated** exposure.

**Key Insight:** Agent struggled with maintaining both filters (failed_trade + product pattern) across turns, but eventually converged. Shows need for stronger filter persistence in refinement prompts.

---

## Complex Multi-Turn Corrections

### Query 4: Aggregation with Granularity Issues

**User Query:** `"sum of notional and pfe by failed trade by product"`

**Agent Performance:**
- **Turns:** 4
- **Outcome:** ⚠️ Returns results but semantically questionable (see Granularity Issues section)

**Turn-by-Turn:**

| Turn | SQL | Result | Review Decision |
|------|-----|--------|-----------------|
| 1 | `SUM(trades.notional + CASE WHEN failed_trade THEN notional ELSE pfe END)` | 19 rows | ❌ REFINE: Conditionally sums instead of summing separately |
| 2 | `SUM(trades.notional), SUM(ccr_limits.exposure_pfe) ... JOIN ccr_limits` | 19 rows | ❌ REFINE: Join may cause duplicate rows |
| 3 | Complex subquery with SUM | 19 rows | ❌ REFINE: SUM incorrectly adds notional twice |
| 4 | `SELECT product, failed_trade, SUM(notional), SUM(cl.exposure_pfe) FROM trades JOIN (SELECT adaptiv_code, SUM(exposure_pfe) ...) cl` | 19 rows ✅ | ✅ GOOD |

**Final Result (Sample):**
```json
{
  "columns": ["product", "failed_trade", "total_notional", "total_exposure_pfe"],
  "row_count": 19,
  "rows": [
    ["FX FWD", true, 11635030.730708892, 32155634.06719064],
    ["CLN", true, 15591938.91383587, 25972287.02570981],
    ["FX SWAP", true, 9918345.381686859, 93387821.44784513],
    ["COMD SWAP", true, 24882656.77847296, 114139911.47394487]
  ]
}
```

**Commentary Generated:**
- **FX FWD**: Failed trades have a total notional of **11,635,030.73** and a total exposure PFE of **32,155,634.07**.
- **CLN**: Failed trades have a total notional of **15,591,938.91** and a total exposure PFE of **25,972,287.02**.
- **FX SWAP**: Failed trades have a total notional of **9,918,345.38** and a total exposure PFE of **93,387,821.45**.
- **COMD SWAP**: Failed trades have a total notional of **24,882,656.78** and a total exposure PFE of **114,139,911.47**.

**⚠️ Critical Issue:** PFE values are inflated due to JOIN with trades table (see Granularity Mismatch section below).

---

### Query 5: Trade-Level Aggregation (Correct)

**User Query:** `"sum of notional by failed trade by product"`

**Agent Performance:**
- **Turns:** 1 ✅
- **Outcome:** ✅ Success

**SQL Generated:**
```sql
SELECT
    trades.failed_trade,
    trades.product,
    SUM(trades.notional) AS sum_notional
FROM trades
GROUP BY trades.failed_trade, trades.product
```

**Final Result (Sample):**
```json
{
  "columns": ["failed_trade", "product", "sum_notional"],
  "row_count": 19,
  "rows": [
    [true, "COMD SWAP", 24882656.77847296],
    [true, "CLN", 15591938.91383587],
    [true, "FX FWD", 11635030.730708892],
    [true, "FX SWAP", 9918345.381686859],
    [false, "FX FWD", 163759990.84141585],
    [false, "COMD SWAP", 83730553.43230319]
  ]
}
```

**Commentary Generated:**
- **COMD SWAP**: The sum of notional for failed trades is **24,882,656.78**.
- **CLN**: The sum of notional for failed trades is **15,591,938.91**.
- **FX FWD**: The sum of notional for failed trades is **11,635,030.73**.
- **FX SWAP**: The sum of notional for failed trades is **9,918,345.38**.

**Key Insight:** When only trade-level metrics are requested (no JOIN needed), agent generates perfect SQL on first attempt.

---

## Granularity Mismatch Issues

### Query 6: PFE Aggregation by Product (Problematic)

**User Query:** `"sum of pfe failed trades by product"`

**Agent Performance:**
- **Turns:** 3
- **Outcome:** ⚠️ Returns results but **semantically incorrect**

**Turn-by-Turn:**

| Turn | SQL | Result | Review Decision |
|------|-----|--------|-----------------|
| 1 | `SUM(trades.notional) AS sum_pfe` | 4 rows | ❌ REFINE: Query sums notional instead of pfe |
| 2 | `SUM(trades.pfe) AS sum_pfe` | ❌ SQL Error | Column "pfe" doesn't exist in trades |
| 3 | `SELECT product, failed_trade, SUM(ccr_limits.exposure_pfe) FROM trades JOIN ccr_limits WHERE failed_trade = true GROUP BY product, failed_trade` | 4 rows ✅ | ✅ GOOD (but wrong!) |

**Final Result:**
```json
{
  "columns": ["product", "failed_trade", "sum_pfe"],
  "row_count": 4,
  "rows": [
    ["FX FWD", true, 32155634.06719064],
    ["FX SWAP", true, 93387821.44784513],
    ["CLN", true, 25972287.02570981],
    ["COMD SWAP", true, 114139911.47394486]
  ]
}
```

**Commentary Generated:**
- **COMD SWAP** has the highest sum of PFE for failed trades at **$114,139,911.47**.
- **FX SWAP** accounts for **$93,387,821.45** in PFE from failed trades.
- **FX FWD** records **$32,155,634.07** in PFE for failed trades.
- **CLN** has **$25,972,287.03** in PFE from failed trades.

---

### ⚠️ Why This Result is Incorrect

**The Fundamental Problem:**

1. **PFE is a counterparty-level metric** (one value per customer per date)
2. **Product is a trade-level dimension** (many trades per customer)
3. **Grouping by product and summing PFE over-counts exposure**

**Example of Over-Counting:**
- **Aurora Metals** has PFE = $10M (counterparty-level, calculated once)
- **Aurora Metals** has 10 trades, including 3 FX FWD trades
- **Query logic:** Joins trades with ccr_limits, creating 10 rows (one per trade)
- **Query result:** `SUM(exposure_pfe) WHERE product='FX FWD'` = $10M × 3 = **$30M** ❌
- **Correct PFE for Aurora Metals:** $10M (regardless of product breakdown)

**What the Query Actually Shows:**
- "PFE counted N times, where N = number of failed trades of that product type"
- **NOT:** "Actual PFE exposure attributable to that product"

**Why Agent Approved It:**
- ✅ SQL is syntactically correct
- ✅ Query returns rows (no errors)
- ✅ Columns match user request
- ❌ Agent doesn't understand **granularity mismatch** (trade-level GROUP BY with counterparty-level SUM)

---

### Comparison: Query 4 vs. Query 5

| Aspect | Query 4: "notional and pfe by product" | Query 5: "notional by product" |
|--------|---------------------------------------|-------------------------------|
| **Turns** | 4 (struggled) | 1 (immediate) |
| **JOIN needed?** | Yes (for PFE) | No (notional in trades table) |
| **Result correctness** | ⚠️ Notional ✅, PFE ❌ (inflated) | ✅ Fully correct |
| **Business meaning** | PFE values are meaningless | Clear trade-level aggregation |

**Key Learning:** Mixing trade-level and counterparty-level metrics in one query creates semantic errors that current agent cannot detect.

---

## Key Learnings

### ✅ Agent Strengths

1. **Text Matching Correction**
   - Converts `= 'fwd'` → `LIKE '%FWD%'` when 0 results
   - Handles case sensitivity issues

2. **Filter Persistence**
   - Eventually adds missing `failed_trade = true` filter
   - Includes filter columns in SELECT for verification

3. **JOIN Optimization**
   - Removes unnecessary JOINs when all columns are in one table
   - Example: "show me all failed trades" → no JOIN needed

4. **Error Recovery**
   - Handles DuckDB `BinderException` errors (missing columns)
   - Fixes type mismatches (VARCHAR vs. DATE comparisons)

5. **Reference Value Usage**
   - Uses unique values (customer names, products) to disambiguate
   - Example: "Aurora Metals" correctly identified as customer (with hint)

---

### ❌ Agent Limitations

1. **Granularity Mismatch Detection**
   - **Cannot detect** when counterparty-level metrics (PFE) are summed with trade-level GROUP BY (product)
   - Review node approves semantically invalid queries
   - **Impact:** Results are numerically wrong but syntactically valid

2. **Entity Disambiguation Without Hints**
   - Struggles with ambiguous entity names ("aurora metal" vs. "Aurora Metals")
   - Requires user to add keywords ("customer", "product") for clarity
   - **Mitigation:** Reference values help but not foolproof

3. **Filter Instability Across Turns**
   - Sometimes "forgets" filters added in previous turns
   - Example: Turn 2 adds `failed_trade`, Turn 4 drops it
   - **Mitigation:** Refinement template needs stronger filter preservation

4. **Latency for Complex Queries**
   - 4-5 turn queries take 30-60 seconds
   - **Mitigation:** Use tiered routing (simple → stateless, complex → agent)

5. **Cost Accumulation**
   - Each turn costs ~$0.002-0.004 (o1-mini)
   - 5-turn query = $0.010-0.020
   - **Mitigation:** Set `max_turns = 3` for cost-sensitive deployments

---

### 🎯 Recommended Improvements

#### Priority 1: Granularity Validation
**Add column-level metadata to schema:**
```json
{
  "tables": {
    "ccr_limits": {
      "columns": {
        "exposure_pfe": {"type": "float", "granularity": "counterparty"},
        "customer_name": {"type": "string", "granularity": "counterparty"}
      }
    },
    "trades": {
      "columns": {
        "notional": {"type": "float", "granularity": "trade"},
        "product": {"type": "string", "granularity": "trade"}
      }
    }
  }
}
```

**Review node check:**
```
If GROUP BY uses "trade" granularity columns (product, trade_id)
AND SUM/AVG uses "counterparty" granularity columns (exposure_pfe)
THEN REFINE: "Cannot aggregate counterparty-level metrics by trade-level dimensions"
```

#### Priority 2: Enhanced Reference Values
**Current:** Extract unique values per column  
**Improved:** Add entity type hints
```json
{
  "reference_values": {
    "ccr_limits": {
      "customer_name": {
        "values": ["Aurora Metals", "Northbridge Capital"],
        "entity_type": "customer",
        "aliases": ["aurora metal", "aurora metals corp"]
      }
    }
  }
}
```

#### Priority 3: Filter Stability
**Update refinement prompt to:**
1. List all filters applied in previous SQL
2. Explicitly require: "Preserve ALL existing filters + add missing ones"
3. Show filter checklist in review node feedback

#### Priority 4: Early Exit Optimization
**Add confidence scoring:**
- If Turn 1 returns >10 rows + passes basic checks → exit early
- If Turn 1 returns 0 rows + user query has typos → suggest alternatives
- Reduces average turns from 2.5 → 1.8

---

## Query Patterns Summary

| Query Pattern | Agent Performance | Recommended Path |
|--------------|------------------|------------------|
| **Simple filters** (top N, single table) | ✅ 1-2 turns | Use stateless |
| **Text matching** (LIKE patterns) | ✅ 2-3 turns | Use agent |
| **Entity disambiguation** (with hints) | ✅ 2-3 turns | Use agent |
| **Entity disambiguation** (without hints) | ❌ 5+ turns, fails | Needs improvement |
| **Trade-level aggregations** | ✅ 1 turn | Use stateless |
| **Counterparty-level queries** | ✅ 2-3 turns | Use agent |
| **Mixed granularity** (trade + counterparty) | ❌ Semantically wrong | **BLOCKED** until validation added |

---

## Test Dataset Summary

**Tables:**
- `ccr_limits`: 30 rows (6 customers × 5 dates)
- `trades`: 100 rows (various products, counterparties)

**Date Range:** 2025-10-10 to 2025-10-14 (5 days)

**Key Entities:**
- **Customers:** Aurora Metals, Northbridge Capital, Pacific Energy Partners, Westgate Holdings, Pinnacle Resources, Silverline Trading
- **Products:** FX FWD, FX SWAP, COMD SWAP, CLN, CDS, IRS, Swaption, etc.
- **Failed Trades:** 5 trades with `failed_trade = true`

**Breaches:** 10 records where `exposure_pfe > limit_ccr`

---

**Document Version:** 1.0  
**Last Updated:** October 2025  
**Test Session Date:** October 15, 2025



