# BA Input Form

**Single source of truth** for configuring the CCR SQL Copilot.

---

## 🎯 Quick Start

### 1. Copy the Template
```bash
cp form.template.json form.json
```

### 2. Edit `form.json`

**For File Mode** (local data files):
```json
{
  "mode": "file",
  "tables": {
    "ccr_limits": {
      "columns": [...],
      "source": {
        "file_path": "input/data/ccr_limits.json"
      }
    }
  }
}
```

**For API Mode** (10k+ rows):
```json
{
  "mode": "api",
  "tables": {
    "ccr_limits": {
      "columns": [...],
      "source": {
        "url": "https://api.example.com/limits",
        "format": "csv_rows_in_json",
        "headers": {"Authorization": "Bearer ${TOKEN}"}
      }
    }
  }
}
```

### 3. Run Queries
```bash
cd ..
python json_sql_copilot.py --form input/form.json --q "top breaches headroom"
```

---

## 📝 What's in form.json

### Required Sections

**`mode`** - Data source mode
- `"file"` - Load from local JSON files
- `"api"` - Fetch from REST APIs

**`tables`** - Table definitions
- Column lists (what fields exist)
- Data sources (where to get data)

**`vocabulary`** - Natural language mappings
- Maps business terms to database columns
- Example: `"utilization": "limit_utilization_pct"`

**`limits`** - SQL execution guardrails
- `default_limit`: Default rows returned
- `hard_max_rows`: Maximum rows allowed
- `allow_non_select`: false (SELECT only)

**`prompts`** - LLM instructions
- `system`: Instructions for AI
- `user_template`: Query template

**`model`** - LLM configuration
- `provider`: "openai"
- `name`: "gpt-4o-mini"

### Optional Sections

**`rule_based_queries`** - Pre-built SQL
- Named queries that work without LLM
- Example: `"top breaches headroom": "SELECT..."`

---

## 📊 Two Modes

### Mode 1: File (Local Data)

**Use for:** Testing, development, small datasets

```json
{
  "mode": "file",
  "tables": {
    "ccr_limits": {
      "source": {
        "file_path": "input/data/ccr_limits.json"
      }
    }
  }
}
```

Place your data files in `input/data/`:
- `ccr_limits.json` - JSON array of objects
- `trades.json` - JSON array of objects

### Mode 2: API (Production Data)

**Use for:** Production, real-time data, 10k+ rows

```json
{
  "mode": "api",
  "tables": {
    "ccr_limits": {
      "source": {
        "url": "https://api.example.com/limits",
        "format": "csv_rows_in_json",
        "columns_key": "columns",
        "row_key": "rows",
        "field_key": null,
        "delimiter": ",",
        "headers": {
          "Authorization": "Bearer ${CCR_API_TOKEN}"
        }
      }
    }
  }
}
```

**Supported formats:**
- `array_of_objects` - Standard JSON
- `csv_rows_in_json` - CSV strings (recommended for 10k+)
- `csv_url` - Direct CSV file URL

---

## 🔧 Complete Example

See `form.json` for a working example with:
- ✅ File mode configuration
- ✅ 20 columns per table
- ✅ Vocabulary mappings
- ✅ 3 pre-built queries
- ✅ LLM prompts

See `form.template.json` for:
- ✅ Detailed comments
- ✅ API mode examples
- ✅ All available options

---

## ⚙️ Configuration Tips

### Adding a New Table

```json
"tables": {
  "my_new_table": {
    "description": "My custom data",
    "columns": ["col1", "col2", "col3"],
    "source": {
      "file_path": "input/data/my_data.json"
    }
  }
}
```

### Adding Vocabulary

```json
"vocabulary": {
  "my term": "my_column",
  "breach": "limit_utilization_pct > 100"
}
```

### Adding Custom Queries

```json
"rule_based_queries": {
  "my report": "SELECT * FROM ccr_limits WHERE ..."
}
```

---

## 🚀 Usage Examples

```bash
# File mode with local data
python json_sql_copilot.py --form input/form.json --q "top breaches headroom"

# With LLM (natural language)
python json_sql_copilot.py --form input/form.json --use-llm --q "Show me FX trades over 10M"

# Print generated SQL
python json_sql_copilot.py --form input/form.json --q "portfolio utilization summary" --print-sql
```

---

## 📚 Files

- `form.json` - Active configuration (edit this)
- `form.template.json` - Template with all options
- `data/` - Your data files (file mode only)
  - `ccr_limits.json` - Sample CCR limits
  - `trades.json` - Sample trades

---

**Need help?** See `form.template.json` for detailed examples and comments.
