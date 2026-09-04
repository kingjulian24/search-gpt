# AGENTS.md — Agent Guidelines & Architecture for search-gpt

## 1. Project Purpose & Scope

`search-gpt` is a **Model Context Protocol (MCP)** server providing intelligent query and retrieval access over a large archive of LLM conversation logs (~40MB, ~4,888 conversations) stored in `data/conversations-*.md`.

The goal is to allow any MCP-compatible AI agent or client (e.g., Claude Desktop, Cursor, Zed, Antigravity) to search, retrieve, summarize, and inspect historical conversations through structured MCP tool calls rather than stuffing massive dumps into the context window.

---

## 2. Dataset Characteristics

The data directory (`data/`) contains 6 JSON export files (`conversations-000.json` to `conversations-005.json`):
- **Total Size:** ~63.5 MB
- **Total Conversations:** 584 conversations
- **Total Messages:** 28,285 messages
- **Format Structure:**
  - Standard ChatGPT export JSON format.
  - Each conversation contains `id`, `title`, `create_time`, `update_time`, `default_model_slug`, `current_node`, and `mapping`.
  - Linear message sequence is retrieved by traversing `current_node` back through `parent` links to root.
  - Each message node contains `author.role` (`user`, `assistant`, `system`), `content.parts` (text strings), and `create_time`.

---

## 3. Recommended Technical Architecture

### 3.1 Server Stack
- **Language / Runtime:** Python 3.12+ using `FastMCP` (`mcp[cli]`).
- **Transport:** Standard I/O (`stdio`) for local MCP integration with Google Antigravity, Claude Desktop, Cursor, etc.

### 3.2 Indexing & Storage Layer
1. **Parser & Ingest Pipeline (`src/parser.py`, `src/indexer.py`):**
   - Stream/load each `conversations-*.json` file.
   - Trace linear turn sequences via `current_node` -> `parent`.
   - Store metadata: `id`, `title`, `create_time` (epoch float and ISO date), `update_time`, `model`, and message count.
2. **Primary Storage (SQLite + FTS5):**
   - Table `conversations`: `id`, `title`, `create_time`, `update_time`, `model`, `message_count`, `source_file`.
   - Table `messages`: `id`, `conversation_id`, `turn_index`, `role`, `content`, `create_time`.
   - Virtual table `messages_fts` (FTS5): full-text search over `content` and `title` using BM25 scoring with porter stemming.
3. **Writing & Essay Tools:**
   - Tools tailored to find conceptual nuggets, extract prompt-response pairs, browse chronologically, and pull conversation context for essays.

---

## 4. MCP Tools Specification

The server must expose the following core tools to agents:

### 1. `search_conversations`
- **Parameters:**
  - `query` (string, required): Search query keywords, operators, or phrase.
  - `limit` (integer, default: 10): Max number of matching conversation snippets to return.
  - `role_filter` (string, optional: `"user"` | `"assistant"` | `"all"`): Filter matches by message sender.
- **Returns:**
  - Ranked list of search matches with `conversation_id`, `title`, snippet/highlighted matches, and relevance score.

### 2. `get_conversation`
- **Parameters:**
  - `conversation_id` (string/int, required): The ID of the conversation to inspect.
  - `max_messages` (integer, optional): Maximum messages to retrieve (defaults to entire conversation if within sensible token limits).
- **Returns:**
  - Full transcript formatted with roles and messages, plus metadata (title, source file, line number).

### 3. `list_recent_conversations`
- **Parameters:**
  - `limit` (integer, default: 20): Number of recent conversation titles.
  - `offset` (integer, default: 0): Pagination offset.
- **Returns:**
  - List of conversation summaries (`id`, `title`, `message_count`, `source_file`).

### 4. `get_archive_stats`
- **Parameters:** None.
- **Returns:**
  - Total conversations, total turns, source file breakdown, index status.

---

## 5. Agent Conventions & Rules

When modifying or contributing to `search-gpt`, agents must adhere to the following:

1. **Do Not Mutate Raw Data:** Never edit, reformat, or delete the export files in `data/`. They are treated as read-only source files.
2. **Reproducible Indexing:** Any database or index must be regenerable via a single idempotent script (e.g. `python -m src.indexer` or `npm run index`).
3. **Graceful Degradation:** The MCP server should start and function with basic lexical search (SQLite FTS5) even if external embedding dependencies or API keys are missing.
4. **Token Consciousness:** Search tool responses should return concise snippets and summaries by default. Never dump 50 full conversations into an MCP tool response unless explicitly paginated or requested.
5. **Type Safety & Testing:** Write typed code (mypy/pydantic for Python; TypeScript for TS). Include unit tests for the JSON parser to verify multi-turn conversation extraction and edge-case handling.
6. **Error Handling:** MCP tool handlers must return clean error strings or structured JSON errors rather than throwing unhandled exceptions across the stdio transport.
