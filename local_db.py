from __future__ import annotations
import json
import sqlite3
from datetime import datetime
from config import DB_FILE


class LocalDB:
    def __init__(self, db_path=DB_FILE):
        self.db_path = str(db_path)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS requests_cache (
                                                              request_id INTEGER PRIMARY KEY,
                                                              start_date TEXT,
                                                              tech_type TEXT,
                                                              tech_model TEXT,
                                                              problem TEXT,
                                                              status TEXT,
                                                              completion_date TEXT,
                                                              repair_parts TEXT,
                                                              client_id INTEGER,
                                                              master_id INTEGER,
                                                              client_fio TEXT,
                                                              client_phone TEXT,
                                                              master_fio TEXT,
                                                              raw_json TEXT
                );

                CREATE TABLE IF NOT EXISTS users_cache (
                                                           user_id INTEGER PRIMARY KEY,
                                                           fio TEXT,
                                                           phone TEXT,
                                                           role TEXT
                );

                CREATE TABLE IF NOT EXISTS sync_queue (
                                                          id INTEGER PRIMARY KEY AUTOINCREMENT,
                                                          method TEXT NOT NULL,
                                                          endpoint TEXT NOT NULL,
                                                          payload_json TEXT,
                                                          created_at TEXT NOT NULL
                );
                """
            )

    def save_requests(self, items: list[dict]) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM requests_cache")
            for r in items:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO requests_cache (
                        request_id, start_date, tech_type, tech_model, problem, status,
                        completion_date, repair_parts, client_id, master_id,
                        client_fio, client_phone, master_fio, raw_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        r.get("request_id"),
                        r.get("start_date"),
                        r.get("tech_type"),
                        r.get("tech_model"),
                        r.get("problem"),
                        r.get("status"),
                        r.get("completion_date"),
                        r.get("repair_parts"),
                        r.get("client_id"),
                        r.get("master_id"),
                        r.get("client_fio"),
                        r.get("client_phone"),
                        r.get("master_fio"),
                        json.dumps(r, ensure_ascii=False),
                    ),
                )

    def get_requests(self, q: str = "", status: str = "") -> list[dict]:
        sql = "SELECT raw_json FROM requests_cache WHERE 1=1"
        params = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if q:
            like = f"%{q}%"
            sql += (
                " AND (CAST(request_id AS TEXT) LIKE ? OR tech_type LIKE ? OR tech_model LIKE ? "
                "OR problem LIKE ? OR client_fio LIKE ? OR master_fio LIKE ?)"
            )
            params.extend([like] * 6)
        sql += " ORDER BY request_id DESC"

        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [json.loads(row["raw_json"]) for row in rows]

    def get_request_by_id(self, request_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT raw_json FROM requests_cache WHERE request_id = ?", (request_id,)
            ).fetchone()
        return json.loads(row["raw_json"]) if row else None

    def upsert_local_request(self, item: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO requests_cache (
                    request_id, start_date, tech_type, tech_model, problem, status,
                    completion_date, repair_parts, client_id, master_id,
                    client_fio, client_phone, master_fio, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.get("request_id"),
                    item.get("start_date"),
                    item.get("tech_type"),
                    item.get("tech_model"),
                    item.get("problem"),
                    item.get("status"),
                    item.get("completion_date"),
                    item.get("repair_parts"),
                    item.get("client_id"),
                    item.get("master_id"),
                    item.get("client_fio"),
                    item.get("client_phone"),
                    item.get("master_fio"),
                    json.dumps(item, ensure_ascii=False),
                ),
            )

    def save_users(self, users: list[dict]) -> None:
        with self._conn() as conn:
            for u in users:
                conn.execute(
                    "INSERT OR REPLACE INTO users_cache (user_id, fio, phone, role) VALUES (?, ?, ?, ?)",
                    (u.get("user_id"), u.get("fio"), u.get("phone"), u.get("role")),
                )

    def get_users_by_role(self, role: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT user_id, fio, phone, role FROM users_cache WHERE role = ? ORDER BY fio",
                (role,),
            ).fetchall()
        return [dict(r) for r in rows]

    def enqueue(self, method: str, endpoint: str, payload: dict | None = None) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO sync_queue (method, endpoint, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (
                    method.upper(),
                    endpoint,
                    json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )

    def get_queue(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM sync_queue ORDER BY id ASC").fetchall()
        result = []
        for r in rows:
            item = dict(r)
            item["payload"] = json.loads(r["payload_json"]) if r["payload_json"] else None
            result.append(item)
        return result

    def remove_queue_item(self, item_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM sync_queue WHERE id = ?", (item_id,))

    def queue_count(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM sync_queue").fetchone()
        return int(row["c"]) if row else 0