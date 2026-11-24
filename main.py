import sys
from PyQt5.QtWidgets import QApplication
from api_client import ApiClient
from config import load_settings
from local_db import LocalDB
from ui.login_dialog import LoginDialog
from ui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    settings = load_settings()
    local_db = LocalDB()
    api = ApiClient(settings.get("server_url", "http://192.168.0.15"), local_db)

    while True:
        login_dlg = LoginDialog(api)
        if login_dlg.exec_() != LoginDialog.Accepted:
            sys.exit(0)

        window = MainWindow(api)
        window.show()
        code = app.exec_()
        if code != 1000:
            sys.exit(code)


if __name__ == "__main__":
    main()