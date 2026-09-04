# search-gpt

**search-gpt** is a Model Context Protocol (MCP) server that enables AI assistants (Google Antigravity, Claude Desktop, Cursor, Zed, etc.) to query, retrieve, and explore historical LLM conversations from local export archives (such as ChatGPT `conversations.json` dumps).

---

## 🚀 Overview

The `data/` directory contains an archive of historical conversation transcripts (~63.5 MB, 584 conversations, and 28,285 messages across `conversations-000.json` to `conversations-005.json`).

Rather than stuffing megabytes of text into an LLM context window—which is costly, slow, and exceeds context budgets—`search-gpt` provides an MCP tool interface that lets any LLM (including Google Antigravity):
1. **Search across thousands of messages** instantly using fast keyword matching (SQLite FTS5 / BM25).
2. **Sort and filter chronologically** using exact timestamps (`create_time` & `update_time`).
3. **Extract writing nuggets and insights** for essays, articles, and research.
4. **Retrieve targeted conversations or turn ranges** on demand with token-efficient snippets.

---

## 🏗 Architecture

```
                               ┌─────────────────────────────┐
                               │  LLM Clients                │
                               │  (Google Antigravity,       │
                               │   Claude Desktop, Cursor)   │
                               └──────────────┬──────────────┘
                                              │ stdio (JSON-RPC)
                                              ▼
                               ┌─────────────────────────────┐
                               │     search-gpt MCP Server   │
                               │                             │
                               │  - search_conversations     │
                               │  - get_conversation         │
                               │  - list_conversations       │
                               │  - extract_nuggets          │
                               │  - get_archive_stats        │
                               └──────────────┬──────────────┘
                                              │
                                              ▼
                               ┌─────────────────────────────┐
                               │  SQLite Database + FTS5     │
                               │  (BM25 ranking, instant,    │
                               │   exact keyword & code)     │
                               └──────────────┬──────────────┘
                                              │ Ingest / Parse
                                              ▼
                               ┌─────────────────────────────┐
                               │   data/conversations-*.json │
                               │   (584 chats, 28k messages) │
                               └─────────────────────────────┘
```

### Why MCP + Indexed Search?
| Approach | Token Cost | Latency | Exact Code / Error Search | Conceptual / Topic Search |
|---|---|---|---|---|
| **Raw Context Stuffing** (~63.5MB) | Extreme (~15M+ tokens) | Unusable / Exceeds limits | Poor (Lost in middle) | Unusable |
| **Grep / Ripgrep directly** | Low | Fast | High (exact regex/string) | None |
| **MCP + SQLite FTS5 (BM25)** | Low (snippets returned) | Milliseconds | High (BM25 ranking + porter stemming) | Moderate |
| **MCP + Hybrid (FTS5 + Vector)** | Low (top-k relevant) | Sub-second | High | High (captures semantic intent) |

---

## 🛠 Features & MCP Tools

| Tool Name | Arguments | Description |
|---|---|---|
| `search_conversations` | `query` (str), `role_filter` (str: all/user/assistant), `limit` (int, default: 10), `sort_by_date` (bool) | Full-text BM25 search over conversation turns; returns ranked snippets with match highlights and metadata. |
| `extract_nuggets` | `query` (str), `limit` (int, default: 5) | **Writing tool**: Pairs your original prompt/context with the assistant's core insight/response for essay synthesis. |
| `get_conversation` | `conversation_id` (str), `start_turn` (int, default: 0), `max_messages` (int, default: 40) | Fetches clean chronological dialogue transcript with speaker labels and turn pagination. |
| `list_conversations` | `limit` (int, default: 20), `offset` (int, default: 0), `query` (str), `sort_order` (desc/asc) | Browse conversation titles chronologically or filter titles by keyword. |
| `get_archive_stats` | *(none)* | Returns overview metrics: total conversations, user vs assistant turns, date range, and index size. |

---

## 📦 Setup & Installation

### Prerequisites
- **Python 3.12+**
- Virtual environment (`.venv`)

### 1. Installation
```bash
# Clone the repository
git clone https://github.com/your-username/search-gpt.git
cd search-gpt

# Create virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Add Your Conversation Data
Export your data from ChatGPT (**Settings → Data Controls → Export Data**). Download the zip and place your `conversations.json` (or split `conversations-*.json` files) into the `data/` folder:
```bash
mkdir -p data
# Place conversations.json or conversations-*.json inside data/
```

### 3. Index the Data
Run the indexer to parse the JSON files into a local SQLite FTS5 database:
```bash
python -m src.indexer
```
*Creates `conversations.db` with full-text BM25 indexes in seconds.*

### 4. Run the MCP Server
```bash
python -m src.server
```

### 5. Run Tests
```bash
python -m unittest discover tests
```

---

## 🔌 Client Configuration

Replace `/path/to/search-gpt` below with the absolute path to your cloned repository (run `pwd` inside the project folder).

### Google Antigravity
Add the server definition to `~/.gemini/config/mcp_config.json`:
```json
{
  "mcpServers": {
    "search-gpt": {
      "command": "/path/to/search-gpt/.venv/bin/python",
      "args": ["-m", "src.server"],
      "cwd": "/path/to/search-gpt"
    }
  }
}
```

### Claude Desktop
Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "search-gpt": {
      "command": "/path/to/search-gpt/.venv/bin/python",
      "args": ["-m", "src.server"],
      "cwd": "/path/to/search-gpt"
    }
  }
}
```

### Cursor / Zed
- **Command:** `/path/to/search-gpt/.venv/bin/python`
- **Args:** `["-m", "src.server"]`
- **Cwd:** `/path/to/search-gpt`

---

## 📂 Project Structure

```
search-gpt/
├── data/                       # Raw conversation JSON dumps (read-only)
│   ├── conversations-000.json
│   ├── conversations-001.json
│   └── ...
├── src/
│   ├── __init__.py
│   ├── parser.py               # Tree-walking parser for multi-turn chats
│   ├── indexer.py              # SQLite + FTS5 indexing pipeline
│   └── server.py               # MCP server & writing tools
├── tests/
│   └── test_server.py          # Unit & integration test suite
├── agents.md                   # Agent system guidelines and architecture specs
├── README.md                   # Project documentation
├── requirements.txt            # Python dependencies
└── conversations.db            # SQLite FTS5 database (auto-generated)
```

---

## 📄 License
MIT
