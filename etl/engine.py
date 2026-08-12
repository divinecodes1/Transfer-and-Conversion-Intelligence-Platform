"""
Transfer & Conversion Intelligence Platform :: a minimal two-engine adapter.

Just enough to let one ingestion pipeline run on both DuckDB (fast local tests)
and PostgreSQL (deployment), without either a heavyweight ORM or two copies of
the pipeline that drift apart.

The surface is deliberately tiny -- execute, executemany, load_csv, script --
because every method here is a place the two engines could diverge silently. The
SQL itself stays portable; this only smooths over the three things that genuinely
cannot be: parameter placeholders, bulk CSV loading, and multi-statement scripts.
"""
import os

DUCKDB, POSTGRES = "duckdb", "postgres"


class Rows(list):
    """List of tuples that also answers the DB-API calls, so callers can write
    either `con.execute(q)` or `con.execute(q).fetchall()`."""

    def fetchall(self):
        return list(self)

    def fetchone(self):
        return self[0] if self else None


class Engine:
    def __init__(self, kind, con):
        self.kind = kind
        self.con = con

    # ---- construction ----------------------------------------------------
    @classmethod
    def duckdb(cls, path):
        import duckdb
        if path and os.path.exists(path):
            os.remove(path)
        return cls(DUCKDB, duckdb.connect(path or ":memory:"))

    @classmethod
    def postgres(cls, dsn):
        import psycopg2
        con = psycopg2.connect(dsn)
        con.autocommit = True
        # The loader is entitled to the whole portfolio; RLS is fail-closed, so
        # this has to be explicit rather than assumed.
        con.cursor().execute("SELECT set_config('transferops.portfolios', '*', false)")
        return cls(POSTGRES, con)

    # ---- statements ------------------------------------------------------
    def execute(self, sql, params=None):
        if self.kind == DUCKDB:
            cur = self.con.execute(sql, params or [])
            return Rows(cur.fetchall() if cur.description else [])
        cur = self.con.cursor()
        cur.execute(sql.replace("?", "%s"), params or [])
        rows = Rows(cur.fetchall() if cur.description else [])
        cur.close()
        return rows

    def executemany(self, sql, seq):
        if not seq:
            return
        if self.kind == DUCKDB:
            self.con.executemany(sql, seq)
            return
        from psycopg2.extras import execute_batch
        cur = self.con.cursor()
        execute_batch(cur, sql.replace("?", "%s"), seq, page_size=500)
        cur.close()

    def script(self, sql):
        """
        Run a multi-statement file.

        PostgreSQL takes the whole text in one go, which matters because the
        safe-cast helpers contain dollar-quoted plpgsql bodies with semicolons
        inside them -- naive splitting would cut those in half. DuckDB has no
        multi-statement execute, so it gets the split, and its function file uses
        macros precisely so there are no embedded semicolons to trip over.
        """
        if self.kind == POSTGRES:
            self.con.cursor().execute(sql)
            return
        lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
        for stmt in "\n".join(lines).split(";"):
            if stmt.strip():
                self.con.execute(stmt)

    def load_csv(self, table, path):
        if self.kind == DUCKDB:
            self.con.execute(f"COPY {table} FROM '{path}' (HEADER, NULLSTR '')")
            return
        with open(path, encoding="utf-8") as f:
            self.con.cursor().copy_expert(
                f"COPY {table} FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')", f)

    def close(self):
        self.con.close()
