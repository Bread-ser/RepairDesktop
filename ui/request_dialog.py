from __future__ import annotations
from datetime import date
from PyQt5.QtCore import QDate
from PyQt5.QtGui import QTextDocument
from PyQt5.QtPrintSupport import QPrintDialog, QPrinter
from PyQt5.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)
from api_client import ApiClient, ApiError
from config import STATUS_LABELS, TECH_TYPES
from file_io import build_request_print_html


class RequestDialog(QDialog):
    def __init__(self, api: ApiClient, request_id: int | None = None, parent=None):
        super().__init__(parent)
        self.api = api
        self.user = api.user
        self.role = self.user["role"]
        self.request_id = request_id
        self.req: dict | None = None
        self.customers = self.api.get_users("customer") if self.role in ("manager", "operator") else []
        self.technicians = self.api.get_users("technician") if self.role in ("manager", "operator") else []

        if self.request_id is not None:
            self.req, from_cache = self.api.get_request(self.request_id)
            if not self.req:
                QMessageBox.warning(self, "Ошибка", "Заявка не найдена.")
                self.reject()
                return
            self.setWindowTitle(f"Заявка №{self.request_id}" + (" (из кэша)" if from_cache else ""))
        else:
            self.setWindowTitle("Новая заявка")

        self.setMinimumWidth(560)
        self._build_ui()
        self._populate()

    def _can_edit_fields(self) -> bool:
        if self.request_id is None:
            return self.role in ("manager", "operator", "customer")
        if self.role in ("manager", "operator"):
            return True
        return (
                self.role == "customer"
                and int(self.req.get("client_id", 0)) == int(self.user["user_id"])
                and self.req.get("status") == "new"
        )

    def _can_change_status(self) -> bool:
        if self.request_id is None:
            return False
        if self.role in ("manager", "operator"):
            return True
        return self.role == "technician" and int(self.req.get("master_id") or 0) == int(self.user["user_id"])

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setCalendarPopup(True)

        self.type_combo = QComboBox()
        self.type_combo.setEditable(True)
        self.type_combo.addItems(TECH_TYPES)

        self.model_edit = QLineEdit()
        self.problem_edit = QTextEdit()
        self.problem_edit.setFixedHeight(70)

        self.parts_edit = QLineEdit()
        self.parts_edit.setPlaceholderText("Использованные / заказанные запчасти")

        form.addRow("Дата создания:", self.date_edit)
        form.addRow("Тип техники:", self.type_combo)
        form.addRow("Модель:", self.model_edit)
        form.addRow("Проблема:", self.problem_edit)

        if self.request_id is None and self.role in ("manager", "operator"):
            self.client_combo = QComboBox()
            for c in self.customers:
                self.client_combo.addItem(f"{c['fio']} ({c.get('phone', '')})", c["user_id"])
            form.addRow("Заказчик:", self.client_combo)
        else:
            self.client_combo = None
            if self.req:
                client_lbl = QLabel(f"{self.req.get('client_fio', '')} ({self.req.get('client_phone', '')})")
                form.addRow("Заказчик:", client_lbl)

        if self.request_id is not None:
            self.status_combo = QComboBox()
            for code, label in STATUS_LABELS.items():
                self.status_combo.addItem(label, code)
            form.addRow("Статус:", self.status_combo)
            form.addRow("Запчасти:", self.parts_edit)

            if self.role in ("manager", "operator"):
                self.master_combo = QComboBox()
                self.master_combo.addItem("— Не назначен —", 0)
                for t in self.technicians:
                    self.master_combo.addItem(t["fio"], t["user_id"])
                form.addRow("Мастер:", self.master_combo)
            else:
                self.master_combo = None
                form.addRow("Мастер:", QLabel(self.req.get("master_fio") or "Не назначен"))
        else:
            self.status_combo = None
            self.master_combo = None

        layout.addLayout(form)

        # Комментарии (только для существующей заявки)
        if self.request_id is not None:
            layout.addWidget(QLabel("Комментарии:"))
            self.comments_list = QListWidget()
            self.comments_list.setFixedHeight(110)
            layout.addWidget(self.comments_list)

            c_row = QHBoxLayout()
            self.comment_input = QLineEdit()
            self.comment_input.setPlaceholderText("Добавить комментарий...")
            self.comment_input.returnPressed.connect(self._add_comment)
            c_btn = QPushButton("Отправить")
            c_btn.clicked.connect(self._add_comment)
            c_row.addWidget(self.comment_input)
            c_row.addWidget(c_btn)
            layout.addLayout(c_row)
        else:
            self.comments_list = None

        # Кнопки
        btns = QHBoxLayout()
        if self.request_id is not None:
            print_btn = QPushButton("Печать квитанции")
            print_btn.clicked.connect(self._print_receipt)
            btns.addWidget(print_btn)

            if self.role == "manager":
                del_btn = QPushButton("Удалить")
                del_btn.setStyleSheet("color: #b00020;")
                del_btn.clicked.connect(self._delete_request)
                btns.addWidget(del_btn)

        btns.addStretch()
        cancel_btn = QPushButton("Закрыть")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(cancel_btn)

        if self._can_edit_fields() or self._can_change_status():
            save_btn = QPushButton("Сохранить")
            save_btn.setDefault(True)
            save_btn.clicked.connect(self._save)
            btns.addWidget(save_btn)

        layout.addLayout(btns)

    def _populate(self) -> None:
        can_edit = self._can_edit_fields()
        self.date_edit.setEnabled(can_edit)
        self.type_combo.setEnabled(can_edit)
        self.model_edit.setReadOnly(not can_edit)
        self.problem_edit.setReadOnly(not can_edit)

        if not self.req:
            return

        d = QDate.fromString(str(self.req.get("start_date", "")), "yyyy-MM-dd")
        if d.isValid():
            self.date_edit.setDate(d)
        self.type_combo.setCurrentText(str(self.req.get("tech_type", "")))
        self.model_edit.setText(str(self.req.get("tech_model", "")))
        self.problem_edit.setPlainText(str(self.req.get("problem", "")))
        self.parts_edit.setText(str(self.req.get("repair_parts") or ""))
        self.parts_edit.setReadOnly(not (can_edit or self._can_change_status()))

        if self.status_combo:
            idx = self.status_combo.findData(self.req.get("status"))
            if idx >= 0:
                self.status_combo.setCurrentIndex(idx)
            self.status_combo.setEnabled(self._can_change_status())

        if self.master_combo:
            mid = int(self.req.get("master_id") or 0)
            idx = self.master_combo.findData(mid)
            if idx >= 0:
                self.master_combo.setCurrentIndex(idx)

        if self.comments_list is not None:
            self.comments_list.clear()
            for c in self.req.get("comments", []):
                self.comments_list.addItem(f"{c.get('fio', '')}: {c.get('message', '')}")

    def _save(self) -> None:
        tech_type = self.type_combo.currentText().strip()
        tech_model = self.model_edit.text().strip()
        problem = self.problem_edit.toPlainText().strip()
        start_date = self.date_edit.date().toString("yyyy-MM-dd")

        if not tech_type or not tech_model or not problem:
            QMessageBox.warning(self, "Внимание", "Заполните тип техники, модель и описание проблемы.")
            return

        queued_any = False
        try:
            if self.request_id is None:
                payload = {
                    "start_date": start_date,
                    "tech_type": tech_type,
                    "tech_model": tech_model,
                    "problem": problem,
                }
                if self.client_combo is not None:
                    payload["client_id"] = self.client_combo.currentData()
                _, queued = self.api.create_request(payload)
                queued_any = queued_any or queued
            else:
                if self._can_edit_fields():
                    payload = {
                        "start_date": start_date,
                        "tech_type": tech_type,
                        "tech_model": tech_model,
                        "problem": problem,
                        "repair_parts": self.parts_edit.text().strip(),
                    }
                    _, queued = self.api.update_request(self.request_id, payload)
                    queued_any = queued_any or queued

                if self._can_change_status() and self.status_combo:
                    new_status = self.status_combo.currentData()
                    new_parts = self.parts_edit.text().strip()
                    if new_status != self.req.get("status") or new_parts != (self.req.get("repair_parts") or ""):
                        _, queued = self.api.update_status(self.request_id, new_status, new_parts)
                        queued_any = queued_any or queued

                if self.master_combo is not None:
                    new_master = int(self.master_combo.currentData() or 0)
                    old_master = int(self.req.get("master_id") or 0)
                    if new_master != old_master:
                        _, queued = self.api.assign_master(self.request_id, new_master)
                        queued_any = queued_any or queued

            if queued_any:
                QMessageBox.information(
                    self,
                    "Офлайн-режим",
                    "Нет связи с сервером. Изменения сохранены в очередь и отправятся автоматически при восстановлении сети.",
                )
            self.accept()
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", str(e))

    def _add_comment(self) -> None:
        text = self.comment_input.text().strip()
        if not text:
            return
        try:
            queued = self.api.add_comment(self.request_id, text)
            self.comments_list.addItem(f"{self.user['fio']}: {text}" + (" [в очереди]" if queued else ""))
            self.comment_input.clear()
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", str(e))

    def _delete_request(self) -> None:
        reply = QMessageBox.question(
            self,
            "Подтверждение",
            f"Удалить заявку №{self.request_id}? Номера последующих заявок сдвинутся.",
            QMessageBox.Yes | QMessageBox.No,
            )
        if reply != QMessageBox.Yes:
            return
        try:
            queued = self.api.delete_request(self.request_id)
            if queued:
                QMessageBox.information(self, "Офлайн-режим", "Удаление поставлено в очередь синхронизации.")
            self.accept()
        except ApiError as e:
            QMessageBox.warning(self, "Ошибка", str(e))

    def _print_receipt(self) -> None:
        if not self.req:
            return
        printer = QPrinter(QPrinter.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec_() == QPrintDialog.Accepted:
            doc = QTextDocument()
            doc.setHtml(build_request_print_html(self.req))
            doc.print_(printer)