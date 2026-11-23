from __future__ import annotations
import requests
from local_db import LocalDB


class ApiError(Exception):
    pass


class ApiClient:
    def __init__(self, server_url: str, local_db: LocalDB):
        self.server_url = server_url.rstrip("/")
        self.db = local_db
        self.token: str | None = None
        self.user: dict | None = None
        self.is_online: bool = True
        self.timeout = 5

    def set_server_url(self, url: str) -> None:
        self.server_url = url.rstrip("/")

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request(self, method: str, endpoint: str, payload: dict | None = None, params: dict | None = None):
        url = f"{self.server_url}/api{endpoint}"
        resp = requests.request(
            method=method.upper(),
            url=url,
            json=payload,
            params=params,
            headers=self._headers(),
            timeout=self.timeout,
        )
        self.is_online = True
        try:
            body = resp.json()
        except ValueError:
            raise ApiError(f"Сервер вернул некорректный ответ (HTTP {resp.status_code})")

        if not resp.ok or not body.get("ok"):
            raise ApiError(body.get("error") or f"Ошибка HTTP {resp.status_code}")
        return body.get("data")

    # --- Авторизация ---
    def login(self, login: str, password: str) -> dict:
        data = self._request("POST", "/auth/login", {"login": login, "password": password})
        self.token = data["token"]
        self.user = data["user"]
        return self.user

    def logout(self) -> None:
        self.token = None
        self.user = None

    # --- Заявки ---
    def get_requests(self, q: str = "", status: str = "") -> tuple[list[dict], bool]:
        """Возвращает (список_заявок, из_кэша)."""
        params = {}
        if q:
            params["q"] = q
        if status:
            params["status"] = status
        try:
            items = self._request("GET", "/requests", params=params)
            if not q and not status:
                self.db.save_requests(items)
            return items, False
        except requests.RequestException:
            self.is_online = False
            return self.db.get_requests(q=q, status=status), True

    def get_request(self, request_id: int) -> tuple[dict | None, bool]:
        try:
            item = self._request("GET", f"/requests/{request_id}")
            self.db.upsert_local_request(item)
            return item, False
        except requests.RequestException:
            self.is_online = False
            return self.db.get_request_by_id(request_id), True

    def create_request(self, data: dict) -> tuple[dict | None, bool]:
        """Возвращает (созданная_заявка_или_None, сохранено_в_офлайн_очередь)."""
        try:
            created = self._request("POST", "/requests", data)
            self.db.upsert_local_request(created)
            return created, False
        except requests.RequestException:
            self.is_online = False
            self.db.enqueue("POST", "/requests", data)
            return None, True

    def update_request(self, request_id: int, data: dict) -> tuple[dict | None, bool]:
        try:
            updated = self._request("PUT", f"/requests/{request_id}", data)
            self.db.upsert_local_request(updated)
            return updated, False
        except requests.RequestException:
            self.is_online = False
            self.db.enqueue("PUT", f"/requests/{request_id}", data)
            return None, True

    def delete_request(self, request_id: int) -> bool:
        """Возвращает True, если ушло в офлайн-очередь."""
        try:
            self._request("DELETE", f"/requests/{request_id}")
            return False
        except requests.RequestException:
            self.is_online = False
            self.db.enqueue("DELETE", f"/requests/{request_id}")
            return True

    def update_status(self, request_id: int, status: str, repair_parts: str) -> tuple[dict | None, bool]:
        payload = {"status": status, "repair_parts": repair_parts}
        try:
            updated = self._request("PATCH", f"/requests/{request_id}/status", payload)
            self.db.upsert_local_request(updated)
            return updated, False
        except requests.RequestException:
            self.is_online = False
            self.db.enqueue("PATCH", f"/requests/{request_id}/status", payload)
            return None, True

    def assign_master(self, request_id: int, master_id: int | None) -> tuple[dict | None, bool]:
        payload = {"master_id": master_id or 0}
        try:
            updated = self._request("PATCH", f"/requests/{request_id}/master", payload)
            self.db.upsert_local_request(updated)
            return updated, False
        except requests.RequestException:
            self.is_online = False
            self.db.enqueue("PATCH", f"/requests/{request_id}/master", payload)
            return None, True

    def add_comment(self, request_id: int, message: str) -> bool:
        payload = {"message": message}
        try:
            self._request("POST", f"/requests/{request_id}/comments", payload)
            return False
        except requests.RequestException:
            self.is_online = False
            self.db.enqueue("POST", f"/requests/{request_id}/comments", payload)
            return True

    # --- Пользователи, статистика, уведомления ---
    def get_users(self, role: str = "") -> list[dict]:
        params = {"role": role} if role else None
        try:
            users = self._request("GET", "/users", params=params)
            self.db.save_users(users)
            return users
        except requests.RequestException:
            self.is_online = False
            return self.db.get_users_by_role(role) if role else []

    def get_stats(self, date_from: str = "", date_to: str = "") -> dict | None:
        params = {}
        if date_from:
            params["from"] = date_from
        if date_to:
            params["to"] = date_to
        try:
            return self._request("GET", "/stats", params=params)
        except requests.RequestException:
            self.is_online = False
            return None

    def get_notifications(self) -> dict | None:
        try:
            return self._request("GET", "/notifications")
        except requests.RequestException:
            self.is_online = False
            return None

    def read_notifications(self) -> None:
        try:
            self._request("POST", "/notifications/read")
        except requests.RequestException:
            self.is_online = False

    # --- Фоновая синхронизация офлайн-очереди ---
    def sync_offline_queue(self) -> tuple[int, int]:
        """Отправляет накопленные офлайн-операции. Возвращает (успешно, осталось)."""
        queue = self.db.get_queue()
        if not queue:
            return 0, 0

        synced = 0
        for item in queue:
            try:
                self._request(item["method"], item["endpoint"], item["payload"])
                self.db.remove_queue_item(item["id"])
                synced += 1
            except requests.RequestException:
                self.is_online = False
                break
            except ApiError:
                # Если сервер отклонил запрос (например, запись уже удалена) — убираем из очереди
                self.db.remove_queue_item(item["id"])
        return synced, self.db.queue_count()