"""Model Context Protocol (MCP) server for searching and querying ChatGPT archives."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

from mcp.server.mcpserver import MCPServer
from src.indexer import DEFAULT_DB_PATH, get_db_connection, init_db

server = MCPServer("search-gpt")


def sanitize_fts5_query(query: str) -> str:
    """Sanitize user search query for SQLite FTS5 syntax while preserving quotes and valid prefixes."""
    query = query.strip()
    if not query:
        return ""

    # If user provided unclosed quotes, clean them
    if '"' in query and query.count('"') % 2 != 0:
        query = query.replace('"', ' ')

    quoted_phrases = re.findall(r'"([^"]*)"', query)
    remainder = re.sub(r'"[^"]*"', ' ', query)

    cleaned_remainder = re.sub(r"[^\w\s\-\*]", " ", remainder)
    tokens = cleaned_remainder.split()

    processed = []
    for phrase in quoted_phrases:
        clean_p = re.sub(r"[^\w\s\-]", " ", phrase).strip()
        if clean_p:
            processed.append(f'"{clean_p}"')

    for token in tokens:
        upper = token.upper()
        if upper in ("AND", "OR", "NOT"):
            processed.append(upper)
        elif token.endswith("*") and any(c.isalnum() for c in token[:-1]):
            processed.append(token)
        else:
            clean_t = token.replace("*", "").strip()
            if clean_t:
                processed.append(f'"{clean_t}"')

    return " ".join(processed)


def format_timestamp(epoch: Optional[float]) -> str:
    """Convert epoch timestamp to human readable date string."""
    if epoch:
        try:
            dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M UTC")
        except (ValueError, OSError):
            pass
    return "Unknown date"


@server.tool()
def search_conversations(
    query: str,
    role_filter: str = "all",
    limit: int = 10,
    sort_by_date: bool = False,
    dedup_conversations: bool = True,
) -> str:
    """Search historical ChatGPT conversations using full-text BM25 search.
    
    Args:
        query: Search keywords, exact phrases (e.g. '"habit loops"'), or terms to search for.
        role_filter: Filter by message sender: 'all' (default), 'user' (your prompts/thoughts), or 'assistant' (model answers).
        limit: Number of matching snippets to return (default: 10, max: 30).
        sort_by_date: If True, orders matches by date (newest first); if False, orders by BM25 relevance score.
        dedup_conversations: If True (default), returns the highest-scoring turn from distinct conversations.
    
    Returns:
        Ranked list of conversation matches with snippets, timestamps, and conversation IDs.
    """
    if not DEFAULT_DB_PATH.exists():
        return f"Error: Index database not found at {DEFAULT_DB_PATH}. Please run 'python -m src.indexer' first."

    limit = max(1, min(limit, 30))
    fts_query = sanitize_fts5_query(query)
    if not fts_query:
        return "Please provide a valid search query with letters or numbers."

    conn = get_db_connection()
    try:
        where_clauses = ["messages_fts MATCH ?"]
        params: List[Any] = [fts_query]

        if role_filter.lower() in ("user", "assistant"):
            where_clauses.append("m.role = ?")
            params.append(role_filter.lower())

        order_by = "c.create_time DESC" if sort_by_date else "rank ASC"

        # Fetch extra candidate rows if deduplicating conversations
        fetch_limit = limit * 4 if dedup_conversations else limit

        sql = f"""
            SELECT 
                m.id AS message_id,
                m.conversation_id,
                m.turn_index,
                m.role,
                m.create_time AS message_time,
                c.title,
                c.create_time AS conv_time,
                c.model,
                snippet(messages_fts, -1, '**[', ']**', '...', 20) AS snippet,
                bm25(messages_fts) AS rank
            FROM messages_fts f
            JOIN messages m ON f.message_id = m.id
            JOIN conversations c ON m.conversation_id = c.id
            WHERE {" AND ".join(where_clauses)}
            ORDER BY {order_by}
            LIMIT ?
        """
        params.append(fetch_limit)

        cursor = conn.execute(sql, params)
        raw_rows = cursor.fetchall()

        if not raw_rows:
            return f"No matches found for query: '{query}' (role filter: {role_filter}). Try broader terms or synonyms."

        rows = []
        seen_convs = set()
        for r in raw_rows:
            if dedup_conversations:
                if r["conversation_id"] in seen_convs:
                    continue
                seen_convs.add(r["conversation_id"])
            rows.append(r)
            if len(rows) >= limit:
                break

        output = [f"### Search Results for: `{query}` ({len(rows)} matches)\n"]
        for idx, r in enumerate(rows, start=1):
            date_str = format_timestamp(r["conv_time"] or r["message_time"])
            role_label = "🧑 User" if r["role"] == "user" else "🤖 Assistant"
            output.append(
                f"**{idx}. {r['title']}**\n"
                f"- **Conversation ID:** `{r['conversation_id']}`\n"
                f"- **Date:** {date_str} | **Turn:** {r['turn_index']} ({role_label})\n"
                f"- **Match Snippet:**\n"
                f"> {r['snippet']}\n"
                f"*To read this conversation, call `get_conversation(conversation_id=\"{r['conversation_id']}\")`*\n"
            )

        return "\n".join(output)
    except sqlite3.OperationalError as e:
        return f"Search error (FTS5): {e}. Try searching without special characters."
    finally:
        conn.close()


@server.tool()
def get_conversation(
    conversation_id: str,
    start_turn: int = 0,
    max_messages: int = 40,
) -> str:
    """Retrieve the formatted dialogue transcript of a specific conversation.
    
    Args:
        conversation_id: The UUID or ID of the conversation to inspect.
        start_turn: 0-indexed turn number to start retrieving from (default: 0).
        max_messages: Maximum turns to return in this view to conserve tokens (default: 40).
    
    Returns:
        Full transcript with turn numbers, speaker roles, timestamps, and message text.
    """
    if not DEFAULT_DB_PATH.exists():
        return f"Error: Database not found at {DEFAULT_DB_PATH}."

    conn = get_db_connection()
    try:
        conv = conn.execute(
            "SELECT id, title, create_time, model, message_count, source_file FROM conversations WHERE id = ?",
            (conversation_id.strip(),)
        ).fetchone()

        if not conv:
            return f"Conversation not found with ID: '{conversation_id}'"

        total_messages = conv["message_count"]
        messages = conn.execute(
            """
            SELECT id, turn_index, role, content, create_time
            FROM messages
            WHERE conversation_id = ? AND turn_index >= ?
            ORDER BY turn_index ASC
            LIMIT ?
            """,
            (conversation_id.strip(), max(0, start_turn), max(1, min(max_messages, 100)))
        ).fetchall()

        date_str = format_timestamp(conv["create_time"])
        header = [
            f"# {conv['title']}",
            f"- **Conversation ID:** `{conv['id']}`",
            f"- **Date:** {date_str}",
            f"- **Model:** {conv['model'] or 'Standard'}",
            f"- **Total Turns:** {total_messages} (Showing turns {start_turn} to {start_turn + len(messages) - 1})",
            f"- **Source File:** `{conv['source_file']}`\n",
            "---\n"
        ]

        turns = []
        for m in messages:
            role_header = "🧑 **User**" if m["role"] == "user" else "🤖 **Assistant**" if m["role"] == "assistant" else f"⚙️ **{m['role'].title()}**"
            turn_time = format_timestamp(m["create_time"])
            turns.append(
                f"### Turn {m['turn_index']} — {role_header} *({turn_time})*\n\n"
                f"{m['content']}\n\n"
                f"---\n"
            )

        if start_turn + len(messages) < total_messages:
            remaining = total_messages - (start_turn + len(messages))
            turns.append(
                f"\n*... {remaining} more messages remaining. Call `get_conversation(conversation_id=\"{conv['id']}\", start_turn={start_turn + len(messages)})` to read further.*"
            )

        return "\n".join(header + turns)
    finally:
        conn.close()


@server.tool()
def list_conversations(
    limit: int = 20,
    offset: int = 0,
    query: str = "",
    sort_order: str = "desc",
) -> str:
    """Browse conversation titles chronologically or filter titles by keyword.
    
    Args:
        limit: Number of conversation summaries to return (default: 20, max: 50).
        offset: Pagination offset (default: 0).
        query: Optional keyword or phrase to filter conversation titles.
        sort_order: 'desc' for newest first (default), or 'asc' for oldest first.
    
    Returns:
        List of conversations with ID, title, date, and message count.
    """
    if not DEFAULT_DB_PATH.exists():
        return f"Error: Database not found at {DEFAULT_DB_PATH}."

    limit = max(1, min(limit, 50))
    offset = max(0, offset)
    direction = "ASC" if sort_order.lower() == "asc" else "DESC"

    conn = get_db_connection()
    try:
        if query.strip():
            cursor = conn.execute(
                f"""
                SELECT id, title, create_time, model, message_count, source_file
                FROM conversations
                WHERE title LIKE ?
                ORDER BY create_time {direction}
                LIMIT ? OFFSET ?
                """,
                (f"%{query.strip()}%", limit, offset)
            )
        else:
            cursor = conn.execute(
                f"""
                SELECT id, title, create_time, model, message_count, source_file
                FROM conversations
                ORDER BY create_time {direction}
                LIMIT ? OFFSET ?
                """,
                (limit, offset)
            )

        rows = cursor.fetchall()
        if not rows:
            return "No conversations found matching criteria."

        output = [f"### Conversation Archive (Showing {len(rows)} items, offset {offset}):\n"]
        for idx, r in enumerate(rows, start=offset + 1):
            date_str = format_timestamp(r["create_time"])
            output.append(
                f"{idx}. **{r['title']}**\n"
                f"   - ID: `{r['id']}` | Date: {date_str} | Turns: {r['message_count']}\n"
            )

        output.append(f"\n*Use `get_conversation(conversation_id=\"<id>\")` to read any transcript.*")
        return "\n".join(output)
    finally:
        conn.close()


@server.tool()
def extract_nuggets(
    query: str,
    limit: int = 5,
) -> str:
    """Extract writing nuggets for essay research: finds matching turns and pairs the User Prompt with the Assistant's Core Insight.
    
    Args:
        query: Conceptual topic, question, or theme (e.g. 'writing routine', 'feeling vs explanation', 'state machine').
        limit: Number of paired nuggets to retrieve (default: 5, max: 10).
    
    Returns:
        Formatted prompt-response nugget pairs ideal for quotation, essay synthesis, and drafting.
    """
    if not DEFAULT_DB_PATH.exists():
        return f"Error: Database not found at {DEFAULT_DB_PATH}."

    limit = max(1, min(limit, 10))
    fts_query = sanitize_fts5_query(query)
    if not fts_query:
        return "Please provide a valid query."

    conn = get_db_connection()
    try:
        # Find top assistant matches or user matches with their paired counterpart
        sql = """
            SELECT 
                m.id AS message_id,
                m.conversation_id,
                m.turn_index,
                m.role,
                c.title,
                c.create_time AS conv_time,
                bm25(messages_fts) AS rank
            FROM messages_fts f
            JOIN messages m ON f.message_id = m.id
            JOIN conversations c ON m.conversation_id = c.id
            WHERE messages_fts MATCH ? AND m.role IN ('user', 'assistant')
            ORDER BY rank ASC
            LIMIT ?
        """
        matches = conn.execute(sql, (fts_query, limit * 2)).fetchall()

        if not matches:
            return f"No conceptual nuggets found for '{query}'."

        seen_conversations = set()
        nuggets = []

        for match in matches:
            conv_id = match["conversation_id"]
            if conv_id in seen_conversations:
                continue
            seen_conversations.add(conv_id)

            # Get user prompt turn and assistant response turn
            turn_idx = match["turn_index"]
            is_assistant = (match["role"] == "assistant")
            target_user_turn = turn_idx - 1 if is_assistant else turn_idx
            target_asst_turn = turn_idx if is_assistant else turn_idx + 1

            rows = conn.execute(
                """
                SELECT turn_index, role, content, create_time
                FROM messages
                WHERE conversation_id = ? AND turn_index IN (?, ?)
                ORDER BY turn_index ASC
                """,
                (conv_id, target_user_turn, target_asst_turn)
            ).fetchall()

            user_text = ""
            asst_text = ""
            turn_date = format_timestamp(match["conv_time"])

            for r in rows:
                if r["role"] == "user":
                    user_text = r["content"].strip()
                elif r["role"] == "assistant":
                    asst_text = r["content"].strip()

            if user_text or asst_text:
                # Truncate overly long text for nugget summaries
                user_preview = (user_text[:350] + "...") if len(user_text) > 350 else user_text
                asst_preview = (asst_text[:600] + "...") if len(asst_text) > 600 else asst_text

                nuggets.append(
                    f"### 💡 Nugget: {match['title']} ({turn_date})\n"
                    f"- **Conversation ID:** `{conv_id}`\n\n"
                    f"**Prompt / Context:**\n"
                    f"> {user_preview or '[Initial context outside preview]'}\n\n"
                    f"**Core Insight / Response:**\n"
                    f"> {asst_preview or '[Response preview unavailable]'}\n\n"
                    f"*To inspect full exchange: `get_conversation(conversation_id=\"{conv_id}\", start_turn={max(0, target_user_turn)})`*\n"
                    f"---\n"
                )

            if len(nuggets) >= limit:
                break

        return "\n".join(nuggets) if nuggets else f"No paired nuggets found for '{query}'."
    finally:
        conn.close()


@server.tool()
def get_archive_stats() -> str:
    """Get high-level overview metrics of the indexed ChatGPT conversation archive."""
    if not DEFAULT_DB_PATH.exists():
        return f"Database not found at {DEFAULT_DB_PATH}."

    conn = get_db_connection()
    try:
        conv_stats = conn.execute(
            "SELECT COUNT(*) AS total_convs, MIN(create_time) AS earliest, MAX(create_time) AS latest FROM conversations"
        ).fetchone()

        msg_count = conn.execute("SELECT COUNT(*) AS total_messages FROM messages").fetchone()["total_messages"]
        user_count = conn.execute("SELECT COUNT(*) AS user_messages FROM messages WHERE role = 'user'").fetchone()["user_messages"]
        asst_count = conn.execute("SELECT COUNT(*) AS asst_messages FROM messages WHERE role = 'assistant'").fetchone()["asst_messages"]

        db_size_mb = DEFAULT_DB_PATH.stat().st_size / (1024 * 1024)

        return (
            f"### 📊 ChatGPT Archive Statistics\n\n"
            f"- **Total Conversations:** {conv_stats['total_convs']:,}\n"
            f"- **Total Messages:** {msg_count:,}\n"
            f"  - **User Messages (Prompts):** {user_count:,}\n"
            f"  - **Assistant Responses:** {asst_count:,}\n"
            f"- **Date Range:** {format_timestamp(conv_stats['earliest'])} → {format_timestamp(conv_stats['latest'])}\n"
            f"- **Database Size:** {db_size_mb:.1f} MB (SQLite + FTS5 BM25 index)\n"
            f"- **Index Status:** Fully synchronized and ready for queries.\n"
        )
    finally:
        conn.close()


def main() -> None:
    """Run the MCP server over stdio transport."""
    # Ensure index exists before starting
    if not DEFAULT_DB_PATH.exists():
        print(f"Index database not found at {DEFAULT_DB_PATH}. Building index now...")
        from src.indexer import index_conversations
        index_conversations()

    server.run(transport="stdio")


if __name__ == "__main__":
    main()
