from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)
from api_client import ApiClient, ApiError
from config import load_settings, save_settings


class LoginDialog(QDialog):
    def __init__(self, api: ApiClient, parent=None):
        super().__init__(parent)
        self.api = api
        self.settings = load_settings()
        self.setWindowTitle("Вход — Учёт заявок на ремонт")
        self.setFixedWidth(380)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel("Авторизация в системе")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        form = QFormLayout()
        self.server_edit = QLineEdit(self.settings.get("server_url", "http://192.168.0.15"))
        self.server_edit.setPlaceholderText("http://192.168.0.15")

        self.login_edit = QLineEdit()
        self.login_edit.setPlaceholderText("login1")

        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        self.pass_edit.setPlaceholderText("Пароль")
        self.pass_edit.returnPressed.connect(self._do_login)

        form.addRow("Сервер:", self.server_edit)
        form.addRow("Логин:", self.login_edit)
        form.addRow("Пароль:", self.pass_edit)
        layout.addLayout(form)

        hint = QLabel("Тестовые: login1 / pass1 (менеджер), login2 / pass2 (техник)")
        hint.setStyleSheet("color: #666; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        btns = QHBoxLayout()
        self.login_btn = QPushButton("Войти")
        self.login_btn.setDefault(True)
        self.login_btn.clicked.connect(self._do_login)

        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)

        btns.addStretch()
        btns.addWidget(cancel_btn)
        btns.addWidget(self.login_btn)
        layout.addLayout(btns)

    def _do_login(self) -> None:
        server = self.server_edit.text().strip().rstrip("/")
        login = self.login_edit.text().strip()
        password = self.pass_edit.text()

        if not server or not login or not password:
            QMessageBox.warning(self, "Внимание", "Заполните адрес сервера, логин и пароль.")
            return

        if not server.startswith(("http://", "https://")):
            server = "http://" + server

        self.api.set_server_url(server)
        self.settings["server_url"] = server
        save_settings(self.settings)

        self.login_btn.setEnabled(False)
        try:
            self.api.login(login, password)
            self.accept()
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка входа", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Нет связи с сервером", f"Не удалось подключиться к {server}:\n{e}")
        finally:
            self.login_btn.setEnabled(True)