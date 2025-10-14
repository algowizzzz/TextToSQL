# JSON SQL Copilot

**Single form configuration** for CCR limits & trades analysis using DuckDB. Everything configured in one JSON file.

## 🚀 Key Features

- **Single source of truth**: `input/form.json` contains everything
- **Two modes**: `file` (local JSON files) or `api` (REST endpoints, 10k+ rows)
- **CSV-in-JSON loader**: Optimized for large datasets (< 40ms parse time)
- **Optional LLM**: OpenAI GPT for natural language queries
- **Auto-commentary**: LLM-generated insights about query results (NEW!)
- **SQL guardrails**: SELECT-only, LIMIT enforcement
- **Fast execution**: DuckDB in-memory processing

---

## 📋 Installation

### 1. Setup Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure (One-time)
```bash
cd input/
cp form.template.json form.json
# Edit form.json with your settings
```

### 3. Run
```bash
cd ..
python json_sql_copilot.py --form input/form.json --q "top breaches headroom"
```

---

## 🎯 Usage

### Pre-built Queries (No LLM Required)
```bash
# Show breaching counterparties
python json_sql_copilot.py --form input/form.json --q "top breaches headroom"

# Show trades for breaches  
python json_sql_copilot.py --form input/form.json --q "top trades by mtm for breaches"

# Portfolio summary
python json_sql_copilot.py --form input/form.json --q "portfolio utilization summary"
```

### Natural Language (With LLM)
```bash
# Add OPENAI_API_KEY to .env
echo "OPENAI_API_KEY=sk-..." > .env

# Use natural language
python json_sql_copilot.py --form input/form.json --use-llm --q "Show FX trades over 10M"

# With auto-commentary (LLM generates insights about the results)
python json_sql_copilot.py --form input/form.json --use-llm --q "summary of Northbridge Capital exposure and trades"
```

---

## ⚙️ Configuration (input/form.json)

### File Mode (Local Data)
```json
{
  "mode": "file",
  "tables": {
    "ccr_limits": {
      "columns": ["adaptiv_code", "customer_name", ...],
      "source": {
        "file_path": "input/data/ccr_limits.json"
      }
    }
  },
  "vocabulary": {...},
  "limits": {...},
  "prompts": {...}
}
```

**Provide:** JSON data files in `input/data/`

### API Mode (Production, 10k+ Rows)
```json
{
  "mode": "api",
  "tables": {
    "ccr_limits": {
      "columns": ["adaptiv_code", ...],
      "source": {
        "url": "https://api.example.com/limits",
        "format": "csv_rows_in_json",
        "headers": {"Authorization": "Bearer ${TOKEN}"}
      }
    }
  }
}
```

**Supported formats:**
- `array_of_objects` - Standard JSON (< 1k rows)
- `csv_rows_in_json` - CSV strings (10k+ rows, **recommended**)
- `csv_url` - Direct CSV file URL

---

## 📊 What's in form.json

### Required

- **`mode`** - Data source (`"file"` or `"api"`)
- **`tables`** - Table definitions with columns and sources
- **`vocabulary`** - Natural language to SQL mappings
- **`limits`** - Execution guardrails
- **`prompts`** - LLM instructions
- **`model`** - LLM configuration

### Optional

- **`rule_based_queries`** - Pre-built SQL queries
- **`commentary`** - Auto-generate insights about results (NEW!)
  - `enabled` - Enable/disable commentary
  - `max_rows_in_prompt` - How many rows to analyze
  - `system_prompt` - Instructions for the analyst persona
  - `user_template` - Template for commentary generation

See `input/form.template.json` for complete example with comments.

---

## 📈 Performance

### Small Dataset (file mode)
- 4 rows × 13 columns
- Query time: ~30ms

### Large Dataset (api mode, csv_rows_in_json)
- 10,000 rows × 20 columns
- Parse: ~20ms
- Query: ~5ms
- Memory: ~1.2 MB per table
- **Total: < 50ms**

**Comfortable range:** 10k-5M rows with filtering

---

## 📁 Project Structure

```
.
├── input/
│   ├── form.json              # Your configuration (edit this)
│   ├── form.template.json     # Template with examples
│   ├── README.md             # Input folder guide
│   └── data/                 # Your data files (file mode)
│       ├── ccr_limits.json
│       └── trades.json
│
├── json_sql_copilot.py       # Main engine (~400 lines)
├── README.md                 # This file
└── requirements.txt         # Dependencies
```

---

## 🛡️ Safety Features

- ✅ **SELECT-only queries** (no writes)
- ✅ **Single statement enforcement**
- ✅ **LIMIT enforcement** (default 200, max 1000)
- ✅ **Column allow-lists** (schema-based)
- ✅ **Timeout protection** (30s default)

---

## 🧪 Testing

### Test with Sample Data
```bash
python json_sql_copilot.py --form input/form.json --q "top breaches headroom"
# Expected: 2 breaching counterparties (AC001, AC003)
```

### View SQL Output
```bash
python json_sql_copilot.py --form input/form.json --q "top breaches headroom" --print-sql
```

---

## 🔌 Extending to Production

### Option 1: Switch to API Mode

1. Edit `input/form.json`:
   ```json
   {
     "mode": "api",
     "tables": {
       "ccr_limits": {
         "source": {
           "url": "https://prod-api.com/limits",
           "format": "csv_rows_in_json"
         }
       }
     }
   }
   ```

2. Add tokens to `.env`:
   ```bash
   CCR_API_TOKEN=your-token
   ```

3. Run as usual

### Option 2: Export Data to Files

1. Export your data to JSON
2. Place in `input/data/`
3. Keep `mode: "file"`

---

## 💡 Tips

### Adding Custom Queries

Edit `input/form.json`:
```json
"rule_based_queries": {
  "my report": "SELECT * FROM ccr_limits WHERE ..."
}
```

### Adding Vocabulary

```json
"vocabulary": {
  "my term": "my_column"
}
```

### Adding a New Table

```json
"tables": {
  "my_table": {
    "columns": ["col1", "col2"],
    "source": {"file_path": "input/data/my_data.json"}
  }
}
```

---

## ❓ FAQ

**Q: Do I need to edit multiple files?**  
A: No! Just `input/form.json` - single source of truth.

**Q: Can I use both file and API mode?**  
A: Not simultaneously, but you can switch by changing `mode`.

**Q: How do I know what columns are available?**  
A: Check the `columns` array in your `input/form.json`.

**Q: What if my API uses a different format?**  
A: Set `format` to `array_of_objects`, `csv_rows_in_json`, or `csv_url`.

**Q: How do I add authentication?**  
A: Add tokens to `.env` and reference with `${TOKEN}` in headers.

---

## 🎛️ Command Line Flags

```bash
python json_sql_copilot.py [OPTIONS]

Required:
  --q "QUERY"          Your query (natural language or pre-built query name)

Optional:
  --form PATH          Path to form.json (default: input/form.json)
  --use-llm            Use OpenAI for natural language (requires OPENAI_API_KEY in .env)
  --print-sql          Show generated and executed SQL
  --with-commentary    Generate LLM commentary about results (auto-enabled with --use-llm)
```

### Examples
```bash
# Basic query
python json_sql_copilot.py --form input/form.json --q "top breaches headroom"

# With SQL output
python json_sql_copilot.py --form input/form.json --q "portfolio utilization summary" --print-sql

# Natural language with LLM (auto-generates commentary)
python json_sql_copilot.py --form input/form.json --use-llm --q "summary of Northbridge Capital exposure"

# Force commentary on pre-built query
python json_sql_copilot.py --form input/form.json --with-commentary --q "top breaches headroom"
```

---

## 📚 Documentation

- **`input/README.md`** - Form configuration guide
- **`input/form.template.json`** - Complete example with comments

---

## 🎓 Example Workflow

```bash
# 1. Setup (one time)
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cd input/
cp form.template.json form.json
nano form.json  # Edit as needed

# 3. Test
cd ..
python json_sql_copilot.py --form input/form.json --q "top breaches headroom"

# 4. Add your data (file mode)
cp my_data.json input/data/ccr_limits.json

# 5. Run your queries
python json_sql_copilot.py --form input/form.json --q "your query"
```

---

**Version**: v3.0.0 (Single Form Architecture)  
**Status**: ✅ Production Ready  
**Performance**: ⚡ Optimized for 10k+ rows  
**Configuration**: 📄 Single JSON file

Built with: Python 3.13+, DuckDB, pandas, OpenAI API
