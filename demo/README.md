# Demo Databases

QueryBridge ships with sample databases so you can try it immediately.

## Chinook Database (Music Store)

The [Chinook database](https://github.com/lerocha/chinook-database) is a sample database representing a digital media store.

**Tables:**
- `artist` — Music artists (275 rows)
- `album` — Albums linked to artists (347 rows)  
- `track` — Individual tracks with genre, media type, price (3,503 rows)
- `genre` — Music genres (25 rows)
- `media_type` — File formats (5 rows)
- `playlist` / `playlist_track` — Curated playlists
- `customer` — Store customers across countries (59 rows)
- `employee` — Store employees with reporting hierarchy (8 rows)
- `invoice` / `invoice_line` — Purchase history (412 invoices, 2,240 line items)

**Great for testing questions like:**
- "What are the top 10 best-selling artists?"
- "Which country generates the most revenue?"
- "Show me the monthly sales trend for 2013"
- "How many tracks does each genre have?"
- "Which employee has the most customers?"

## Files

| File | Format | Use |
|------|--------|-----|
| `chinook.sql` | SQLite SQL | `sqlite3 chinook.db < chinook.sql` |
| `chinook_postgres.sql` | PostgreSQL SQL | Used by `docker compose up` |

## Using the Demo

### With Docker (recommended)
```bash
docker compose up
# Open http://localhost:3000
```

### With SQLite (no Docker needed)
```bash
pip install querybridge[sqlite]
querybridge --dsn "sqlite:///demo/chinook.db" interactive
```
