import sqlite3
# Verify: do snippet()/bm25() work when no MATCH clause is present?
c = sqlite3.connect(':memory:')
c.execute("CREATE VIRTUAL TABLE f USING fts5(session_id UNINDEXED, text)")
c.execute("INSERT INTO f VALUES ('s', 'some derivative text')")
try:
    rows = c.execute("SELECT snippet(f, 1, '[', ']', '...', 24), bm25(f) FROM f").fetchall()
    print('no-match snippet/bm25 OK:', rows)
except Exception as exc:
    print('no-match snippet/bm25 FAILED:', type(exc).__name__, exc)
