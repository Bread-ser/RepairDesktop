from __future__ import annotations
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QTextDocument
from PyQt5.QtPrintSupport import QPrintDialog, QPrinter
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyle,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from api_client import ApiClient, ApiError
from config import ROLE_LABELS, STATUS_LABELS, load_settings, save_settings, set_autostart
from file_io import (
    build_report_print_html,
    export_requests_csv,
    export_requests_xlsx,
    import_requests_file,
)
from ui.request_dialog import RequestDialog


class MainWindow(QMainWindow):
    def __init__(self, api: ApiClient):
        super().__init__()
        self.api = api
        self.user = api.user
        self.role = self.user["role"]
        self.settings = load_settings()
        self.current_requests: list[dict] = []
        self.last_stats: dict | None = None
        self.last_unread_count = 0
        self._force_quit = False

        role_ru = ROLE_LABELS.get(self.role, self.role)
        self.setWindowTitle(f"Учёт заявок на ремонт — {self.user['fio']} ({role_ru})")
        self.resize(1120, 680)

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(300)
        self.search_timer.timeout.connect(self.load_requests)

        self._build_ui()
        self._setup_tray()
        self._setup_sync_timer()
        self.load_requests()
        if self.role == "manager":
            self.load_stats()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        top = QHBoxLayout()
        self.status_badge = QLabel("● Онлайн")
        self.status_badge.setStyleSheet("color: #1b7f37; font-weight: bold;")
        top.addWidget(self.status_badge)

        self.queue_badge = QLabel("")
        self.queue_badge.setStyleSheet("color: #b45309; font-weight: bold;")
        top.addWidget(self.queue_badge)

        top.addStretch()

        self.barcode_edit = QLineEdit()
        self.barcode_edit.setPlaceholderText("Штрих-код / № заявки + Enter")
        self.barcode_edit.setFixedWidth(210)
        self.barcode_edit.returnPressed.connect(self._on_barcode_scanned)
        top.addWidget(self.barcode_edit)

        self.autostart_cb = QCheckBox("Автозапуск")
        self.autostart_cb.setChecked(bool(self.settings.get("autostart", False)))
        self.autostart_cb.toggled.connect(self._toggle_autostart)
        top.addWidget(self.autostart_cb)

        sync_btn = QPushButton("Синхронизация")
        sync_btn.clicked.connect(self._manual_sync)
        top.addWidget(sync_btn)

        logout_btn = QPushButton("Выйти")
        logout_btn.clicked.connect(self._logout)
        top.addWidget(logout_btn)

        root.addLayout(top)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_requests_tab(), "Заявки")
        if self.role == "manager":
            self.tabs.addTab(self._build_reports_tab(), "Отчёты и статистика")
        root.addWidget(self.tabs)

        self.statusBar().showMessage(f"Сервер: {self.api.server_url}")

    def _build_requests_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        bar = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Поиск по №, технике, клиенту, мастеру...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._on_search_changed)
        self.search_edit.returnPressed.connect(self.load_requests)
        bar.addWidget(self.search_edit, 2)

        self.status_filter = QComboBox()
        self.status_filter.addItem("Все статусы", "")
        for code, label in STATUS_LABELS.items():
            self.status_filter.addItem(label, code)
        self.status_filter.currentIndexChanged.connect(self.load_requests)
        bar.addWidget(self.status_filter)

        if self.role in ("manager", "operator", "customer"):
            new_btn = QPushButton("+ Новая заявка")
            new_btn.clicked.connect(self._create_request)
            bar.addWidget(new_btn)

        export_btn = QPushButton("Экспорт CSV/Excel")
        export_btn.clicked.connect(self._export_file)
        bar.addWidget(export_btn)

        if self.role in ("manager", "operator", "customer"):
            import_btn = QPushButton("Импорт CSV/Excel")
            import_btn.clicked.connect(self._import_file)
            bar.addWidget(import_btn)

        layout.addLayout(bar)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["№", "Дата", "Тип техники", "Модель", "Проблема", "Статус", "Заказчик", "Мастер"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.cellDoubleClicked.connect(self._open_selected_request)
        layout.addWidget(self.table)

        hint = QLabel("Двойной клик по строке открывает карточку заявки (редактирование, статус, комментарии, печать).")
        hint.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(hint)
        return tab

    def _build_reports_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        bar = QHBoxLayout()
        self.from_edit = QLineEdit()
        self.from_edit.setPlaceholderText("С даты (YYYY-MM-DD)")
        self.to_edit = QLineEdit()
        self.to_edit.setPlaceholderText("По дату (YYYY-MM-DD)")
        refresh_btn = QPushButton("Сформировать")
        refresh_btn.clicked.connect(self.load_stats)
        print_btn = QPushButton("Печать отчёта")
        print_btn.clicked.connect(self._print_report)

        bar.addWidget(QLabel("Период:"))
        bar.addWidget(self.from_edit)
        bar.addWidget(self.to_edit)
        bar.addWidget(refresh_btn)
        bar.addWidget(print_btn)
        bar.addStretch()
        layout.addLayout(bar)

        self.kpi_label = QLabel("Загрузка статистики...")
        self.kpi_label.setStyleSheet("font-size: 14px; font-weight: bold; padding: 6px 0;")
        layout.addWidget(self.kpi_label)

        layout.addWidget(QLabel("По типам техники:"))
        self.type_table = QTableWidget(0, 4)
        self.type_table.setHorizontalHeaderLabels(["Тип техники", "Всего", "Готово", "Ср. дней"])
        self.type_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.type_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.type_table)

        layout.addWidget(QLabel("По мастерам:"))
        self.master_table = QTableWidget(0, 3)
        self.master_table.setHorizontalHeaderLabels(["Мастер", "Всего заявок", "Выполнено"])
        self.master_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.master_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.master_table)
        return tab

    def _on_search_changed(self) -> None:
        self.search_timer.start()

    def _logout(self) -> None:
        self.sync_timer.stop()
        self.api.logout()
        self._force_quit = True
        self.tray.hide()
        self.close()
        QApplication.exit(1000)

    def _setup_tray(self) -> None:
        self.tray = QSystemTrayIcon(self)
        icon = self.style().standardIcon(QStyle.SP_ComputerIcon)
        self.setWindowIcon(icon)
        self.tray.setIcon(icon)
        self.tray.setToolTip("Учёт заявок на ремонт")

        menu = QMenu()
        show_act = QAction("Открыть окно", self)
        show_act.triggered.connect(self._restore_from_tray)
        logout_act = QAction("Выйти из аккаунта", self)
        logout_act.triggered.connect(self._logout)
        quit_act = QAction("Выход", self)
        quit_act.triggered.connect(self._quit_app)
        menu.addAction(show_act)
        menu.addAction(logout_act)
        menu.addSeparator()
        menu.addAction(quit_act)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.activateWindow()

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self._restore_from_tray()

    def _quit_app(self) -> None:
        self._force_quit = True
        self.tray.hide()
        self.close()
        QApplication.quit()

    def closeEvent(self, event) -> None:
        if not self._force_quit and self.tray.isVisible():
            event.ignore()
            self.hide()
            self.tray.showMessage(
                "Учёт заявок на ремонт",
                "Приложение свёрнуто в трей и продолжает фоновую синхронизацию.",
                QSystemTrayIcon.Information,
                2500,
            )
        else:
            event.accept()

    def _setup_sync_timer(self) -> None:
        interval_ms = int(self.settings.get("sync_interval_sec", 15)) * 1000
        self.sync_timer = QTimer(self)
        self.sync_timer.timeout.connect(self._background_sync)
        self.sync_timer.start(interval_ms)

    def _background_sync(self) -> None:
        synced, remaining = self.api.sync_offline_queue()
        if synced > 0:
            self.tray.showMessage(
                "Синхронизация завершена",
                f"Отправлено отложенных операций: {synced}",
                QSystemTrayIcon.Information,
                3000,
            )

        self.load_requests(silent=True)
        if self.role == "manager" and self.api.is_online:
            self.load_stats()

        notif = self.api.get_notifications()
        if notif is not None:
            unread = int(notif.get("unread", 0))
            if unread > self.last_unread_count and notif.get("items"):
                msg = notif["items"][0].get("message", "Новое уведомление")
                self.tray.showMessage("Новое уведомление", msg, QSystemTrayIcon.Information, 4000)
            self.last_unread_count = unread

        self._update_connection_badges(remaining)

    def _manual_sync(self) -> None:
        synced, remaining = self.api.sync_offline_queue()
        self.load_requests(silent=False)
        if self.role == "manager":
            self.load_stats()
        self._update_connection_badges(remaining)
        self.statusBar().showMessage(f"Синхронизировано операций: {synced}, в очереди: {remaining}", 4000)

    def _update_connection_badges(self, queue_count: int | None = None) -> None:
        if queue_count is None:
            queue_count = self.api.db.queue_count()
        if self.api.is_online:
            self.status_badge.setText("● Онлайн")
            self.status_badge.setStyleSheet("color: #1b7f37; font-weight: bold;")
        else:
            self.status_badge.setText("● Офлайн (локальный кэш)")
            self.status_badge.setStyleSheet("color: #c62828; font-weight: bold;")
        self.queue_badge.setText(f"В очереди: {queue_count}" if queue_count > 0 else "")

    def load_requests(self, silent: bool = False) -> None:
        q = self.search_edit.text().strip()
        status = self.status_filter.currentData() or ""

        scroll_pos = self.table.verticalScrollBar().value()
        selected_id = None
        curr_row = self.table.currentRow()
        if curr_row >= 0:
            curr_item = self.table.item(curr_row, 0)
            if curr_item:
                selected_id = curr_item.data(Qt.UserRole)

        items, from_cache = self.api.get_requests(q=q, status=status)
        self.current_requests = items

        self.table.setRowCount(len(items))
        row_to_select = -1
        for row_idx, r in enumerate(items):
            req_id = int(r["request_id"])
            if req_id == selected_id:
                row_to_select = row_idx
            vals = [
                str(req_id),
                str(r.get("start_date", "")),
                str(r.get("tech_type", "")),
                str(r.get("tech_model", "")),
                str(r.get("problem", "")),
                STATUS_LABELS.get(r.get("status", ""), str(r.get("status", ""))),
                str(r.get("client_fio") or ""),
                str(r.get("master_fio") or "—"),
            ]
            for col_idx, val in enumerate(vals):
                item = QTableWidgetItem(val)
                if col_idx == 0:
                    item.setData(Qt.UserRole, req_id)
                self.table.setItem(row_idx, col_idx, item)

        if row_to_select >= 0:
            self.table.selectRow(row_to_select)
        self.table.verticalScrollBar().setValue(scroll_pos)

        self._update_connection_badges()
        if not silent:
            src = "из локального кэша SQLite" if from_cache else "с сервера"
            self.statusBar().showMessage(f"Загружено заявок: {len(items)} ({src})", 3000)

    def _open_selected_request(self, row: int, _col: int) -> None:
        item = self.table.item(row, 0)
        if not item:
            return
        req_id = item.data(Qt.UserRole)
        dlg = RequestDialog(self.api, request_id=req_id, parent=self)
        if dlg.exec_() == RequestDialog.Accepted:
            self.load_requests()
            if self.role == "manager":
                self.load_stats()

    def _create_request(self) -> None:
        dlg = RequestDialog(self.api, request_id=None, parent=self)
        if dlg.exec_() == RequestDialog.Accepted:
            self.load_requests()
            if self.role == "manager":
                self.load_stats()

    def _on_barcode_scanned(self) -> None:
        raw = self.barcode_edit.text().strip()
        self.barcode_edit.clear()
        digits = "".join(ch for ch in raw if ch.isdigit())
        if not digits:
            QMessageBox.warning(self, "Штрих-код", f"Не удалось распознать номер заявки из «{raw}».")
            return
        dlg = RequestDialog(self.api, request_id=int(digits), parent=self)
        if dlg.exec_() == RequestDialog.Accepted:
            self.load_requests()

    def _export_file(self) -> None:
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Экспорт заявок",
            "requests.xlsx",
            "Excel (*.xlsx);;CSV (*.csv)",
        )
        if not path:
            return
        try:
            if path.lower().endswith(".csv") or "CSV" in selected_filter:
                export_requests_csv(path, self.current_requests)
            else:
                export_requests_xlsx(path, self.current_requests)
            QMessageBox.information(self, "Экспорт", f"Сохранено в {path}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка экспорта", str(e))

    def _import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Импорт заявок",
            "",
            "Таблицы (*.xlsx *.csv);;Все файлы (*)",
        )
        if not path:
            return
        try:
            default_client_id = int(self.user["user_id"])
            if self.role in ("manager", "operator"):
                customers = self.api.get_users("customer")
                if customers:
                    default_client_id = int(customers[0]["user_id"])
            rows = import_requests_file(path, default_client_id)
            if not rows:
                QMessageBox.warning(self, "Импорт", "Не найдено строк для импорта (нужны колонки: Тип, Модель, Проблема).")
                return

            created, queued = 0, 0
            for item in rows:
                _, is_queued = self.api.create_request(item)
                if is_queued:
                    queued += 1
                else:
                    created += 1
            self.load_requests()
            QMessageBox.information(
                self,
                "Импорт завершён",
                f"Создано на сервере: {created}\nПоставлено в офлайн-очередь: {queued}",
            )
        except (ApiError, Exception) as e:
            QMessageBox.critical(self, "Ошибка импорта", str(e))

    def load_stats(self) -> None:
        stats = self.api.get_stats(self.from_edit.text().strip(), self.to_edit.text().strip())
        if not stats:
            self.kpi_label.setText("Статистика недоступна в офлайн-режиме.")
            return
        self.last_stats = stats
        c = stats.get("counts", {})
        avg = stats.get("avg_days")
        self.kpi_label.setText(
            f"Всего: {stats.get('total', 0)} | Новые: {c.get('new', 0)} | В работе: {c.get('in_progress', 0)} "
            f"| Ожидают запчасти: {c.get('waiting_parts', 0)} | Готово: {c.get('ready', 0)} "
            f"| Ср. срок: {avg if avg is not None else '—'} дн."
        )

        by_type = stats.get("by_type", [])
        self.type_table.setRowCount(len(by_type))
        for i, r in enumerate(by_type):
            self.type_table.setItem(i, 0, QTableWidgetItem(str(r.get("tech_type", ""))))
            self.type_table.setItem(i, 1, QTableWidgetItem(str(r.get("total", 0))))
            self.type_table.setItem(i, 2, QTableWidgetItem(str(r.get("done", 0))))
            self.type_table.setItem(i, 3, QTableWidgetItem(str(r.get("avg_days") or "—")))

        by_master = stats.get("by_master", [])
        self.master_table.setRowCount(len(by_master))
        for i, r in enumerate(by_master):
            self.master_table.setItem(i, 0, QTableWidgetItem(str(r.get("master", ""))))
            self.master_table.setItem(i, 1, QTableWidgetItem(str(r.get("total", 0))))
            self.master_table.setItem(i, 2, QTableWidgetItem(str(r.get("done", 0))))

    def _print_report(self) -> None:
        if not self.last_stats:
            QMessageBox.warning(self, "Печать", "Сначала сформируйте отчёт.")
            return
        printer = QPrinter(QPrinter.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec_() == QPrintDialog.Accepted:
            doc = QTextDocument()
            doc.setHtml(build_report_print_html(self.last_stats, self.from_edit.text().strip(), self.to_edit.text().strip()))
            doc.print_(printer)

    def _toggle_autostart(self, checked: bool) -> None:
        ok, msg = set_autostart(checked)
        if ok:
            self.settings["autostart"] = checked
            save_settings(self.settings)
            self.statusBar().showMessage(msg, 3000)
        else:
            QMessageBox.warning(self, "Автозапуск", msg)
            self.autostart_cb.blockSignals(True)
            self.autostart_cb.setChecked(not checked)
            self.autostart_cb.blockSignals(False)