from __future__ import annotations
import json
import sys
from pathlib import Path

APP_NAME = "RepairDesktop"
APP_DIR = Path.home() / ".repair_desktop"
APP_DIR.mkdir(parents=True, exist_ok=True)

SETTINGS_FILE = APP_DIR / "settings.json"
DB_FILE = APP_DIR / "cache.db"

DEFAULT_SETTINGS = {
    "server_url": "http://192.168.0.15",
    "sync_interval_sec": 3,
    "autostart": False,
}

STATUS_LABELS = {
    "new": "Новая",
    "in_progress": "В работе",
    "waiting_parts": "Ожидание запчастей",
    "ready": "Готова к выдаче",
}

ROLE_LABELS = {
    "manager": "Менеджер",
    "operator": "Оператор",
    "technician": "Техник",
    "customer": "Заказчик",
}

TECH_TYPES = [
    "Компьютер",
    "Ноутбук",
    "Клавиатура",
    "Мышь",
    "Монитор",
    "Принтер",
    "Другое",
]


def load_settings() -> dict:
    data = dict(DEFAULT_SETTINGS)
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    data.update(saved)
        except Exception:
            pass
    return data


def save_settings(data: dict) -> None:
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def set_autostart(enabled: bool) -> tuple[bool, str]:
    main_script = Path(__file__).resolve().parent / "main.py"
    python_exe = sys.executable

    if sys.platform.startswith("linux"):
        autostart_dir = Path.home() / ".config" / "autostart"
        autostart_dir.mkdir(parents=True, exist_ok=True)
        desktop_file = autostart_dir / "repair-desktop.desktop"
        try:
            if enabled:
                content = (
                    "[Desktop Entry]\n"
                    "Type=Application\n"
                    "Name=Учёт заявок на ремонт\n"
                    f"Exec={python_exe} {main_script}\n"
                    "Terminal=false\n"
                    "X-GNOME-Autostart-enabled=true\n"
                )
                desktop_file.write_text(content, encoding="utf-8")
            elif desktop_file.exists():
                desktop_file.unlink()
            return True, "Автозапуск обновлён (Linux)"
        except Exception as e:
            return False, f"Ошибка автозапуска: {e}"

    if sys.platform == "win32":
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                if enabled:
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{python_exe}" "{main_script}"')
                else:
                    try:
                        winreg.DeleteValue(key, APP_NAME)
                    except FileNotFoundError:
                        pass
            return True, "Автозапуск обновлён (Windows)"
        except Exception as e:
            return False, f"Ошибка автозапуска: {e}"

    return False, "ОС не поддерживается для автозапуска"