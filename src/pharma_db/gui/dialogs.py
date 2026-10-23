"""Modal dialogs used to create / edit rows and to confirm destructive acts."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..auth import User, hash_password
from ..models import Composition, Manufacturer, Medicine, ValidationError


def _configure_completion(combo: QComboBox) -> None:
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    # Long item lists must not inflate the dialog's minimum width.
    combo.setSizeAdjustPolicy(
        QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
    )
    combo.setMinimumContentsLength(12)
    completer = combo.completer()
    completer.setCompletionMode(combo.completer().CompletionMode.PopupCompletion)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)


class TextPickerDialog(QDialog):
    """Filterable list used to pick a manufacturer / composition string."""

    def __init__(
        self,
        title: str,
        items: list[str],
        parent: QWidget | None = None,
        current: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(520, 480)
        self._items = items
        self._all_items = list(items)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Type to filter...")
        self.search.setClearButtonEnabled(True)
        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True)

        self.count_label = QLabel(f"{len(items):,} item(s)")
        self.count_label.setObjectName("muted")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(8)
        layout.addWidget(self.search)
        layout.addWidget(self.list_widget, 1)
        bottom = QHBoxLayout()
        bottom.addWidget(self.count_label)
        bottom.addStretch(1)
        bottom.addWidget(buttons)
        layout.addLayout(bottom)

        self.search.textChanged.connect(self._apply_filter)
        self.list_widget.itemDoubleClicked.connect(lambda _: self.accept())
        self._apply_filter("")

        if current:
            matches = [i for i, value in enumerate(items) if value == current]
            if matches:
                self.list_widget.setCurrentRow(matches[0])

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        self.list_widget.clear()
        shown = 0
        for value in self._items:
            if needle and needle not in value.lower():
                continue
            item = QListWidgetItem(value)
            self.list_widget.addItem(item)
            shown += 1
            if shown >= 5000:
                break
        self.count_label.setText(f"{shown:,} shown / {len(self._items):,} total")

    def selected(self) -> str | None:
        item = self.list_widget.currentItem()
        return item.text() if item else None


class BaseEditDialog(QDialog):
    """Form dialog with an inline error line and Save / Cancel buttons."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.error_label = QLabel("")
        self.error_label.setObjectName("error")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)

        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primary")
        self.buttons.accepted.connect(self._try_accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(10)
        layout.addLayout(self.form)
        layout.addWidget(self.error_label)
        layout.addWidget(self.buttons, 0, Qt.AlignmentFlag.AlignRight)

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(bool(message))

    def build(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def payload(self) -> object:  # pragma: no cover - overridden
        raise NotImplementedError

    def _try_accept(self) -> None:
        try:
            self.payload()
        except ValidationError as exc:
            self._show_error(str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self._show_error(f"{type(exc).__name__}: {exc}")
            return
        self._show_error("")
        self.accept()


class MedicineDialog(BaseEditDialog):
    def __init__(
        self,
        medicine: Medicine,
        manufacturers: list[str],
        compositions: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Edit medicine" if medicine.id else "Add medicine", parent)
        self.medicine = medicine
        self._manufacturers = manufacturers
        self._compositions = compositions

        self.id_edit = QLineEdit(str(medicine.id) if medicine.id else "auto")
        self.id_edit.setReadOnly(True)
        self.name_edit = QLineEdit(medicine.name)
        self.name_edit.setPlaceholderText("e.g. Azithral 500 Tablet")

        self.price_spin = QDoubleSpinBox()
        self.price_spin.setRange(0.0, 1_000_000_000.0)
        self.price_spin.setDecimals(2)
        self.price_spin.setPrefix("\u20b9 ")
        self.price_spin.setValue(float(medicine.price_rs or 0.0))

        self.manufacturer_combo = QComboBox()
        self.manufacturer_combo.addItems(manufacturers)
        _configure_completion(self.manufacturer_combo)
        self.manufacturer_combo.setCurrentText(medicine.manufacturer_name)
        self.manufacturer_button = QPushButton("...")
        self.manufacturer_button.setFixedWidth(34)
        self.manufacturer_button.clicked.connect(self._pick_manufacturer)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["allopathy", "ayurveda", "homeopathy", "unani", "siddha"])
        _configure_completion(self.type_combo)
        self.type_combo.setCurrentText(medicine.type)

        self.pack_edit = QLineEdit(medicine.pack_size_label or "")
        self.pack_edit.setPlaceholderText("e.g. strip of 10 tablets")

        self.comp1_combo = QComboBox()
        self.comp1_combo.addItems(compositions)
        _configure_completion(self.comp1_combo)
        self.comp1_combo.setCurrentText(medicine.composition1)
        self.comp1_button = QPushButton("...")
        self.comp1_button.setFixedWidth(34)
        self.comp1_button.clicked.connect(self._pick_comp1)

        self.comp2_combo = QComboBox()
        self.comp2_combo.addItems(compositions)
        _configure_completion(self.comp2_combo)
        self.comp2_combo.setCurrentText(medicine.composition2 or "")
        comp2_row = QHBoxLayout()
        comp2_row.setContentsMargins(0, 0, 0, 0)
        comp2_row.setSpacing(6)
        comp2_row.addWidget(self.comp2_combo, 1)
        comp2_button = QPushButton("...")
        comp2_button.setFixedWidth(34)
        comp2_button.clicked.connect(self._pick_comp2)
        comp2_row.addWidget(comp2_button)
        clear_comp2 = QPushButton("Clear")
        clear_comp2.setFlat(True)
        clear_comp2.clicked.connect(lambda: self.comp2_combo.setCurrentText(""))
        comp2_row.addWidget(clear_comp2)
        comp2_wrap = QWidget()
        comp2_wrap.setLayout(comp2_row)

        self.form.addRow("ID", self.id_edit)
        self.form.addRow("Name", self.name_edit)
        self.form.addRow("Price", self.price_spin)
        self.form.addRow("Type", self.type_combo)
        mfr_row = QHBoxLayout()
        mfr_row.setContentsMargins(0, 0, 0, 0)
        mfr_row.setSpacing(6)
        mfr_row.addWidget(self.manufacturer_combo, 1)
        mfr_row.addWidget(self.manufacturer_button)
        mfr_wrap = QWidget()
        mfr_wrap.setLayout(mfr_row)
        self.form.addRow("Manufacturer", mfr_wrap)
        self.form.addRow("Pack size", self.pack_edit)

        comp1_row = QHBoxLayout()
        comp1_row.setContentsMargins(0, 0, 0, 0)
        comp1_row.setSpacing(6)
        comp1_row.addWidget(self.comp1_combo, 1)
        comp1_row.addWidget(self.comp1_button)
        comp1_wrap = QWidget()
        comp1_wrap.setLayout(comp1_row)
        self.form.addRow("Composition 1", comp1_wrap)
        self.form.addRow("Composition 2", comp2_wrap)

        self.name_edit.selectAll()

    def _pick(self, title: str, items: list[str], combo: QComboBox) -> None:
        dialog = TextPickerDialog(title, items, self, combo.currentText())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            chosen = dialog.selected()
            if chosen:
                combo.setCurrentText(chosen)

    def _pick_manufacturer(self) -> None:
        self._pick("Select manufacturer", self._manufacturers, self.manufacturer_combo)

    def _pick_comp1(self) -> None:
        self._pick("Select composition", self._compositions, self.comp1_combo)

    def _pick_comp2(self) -> None:
        self._pick("Select composition", self._compositions, self.comp2_combo)

    def payload(self) -> Medicine:
        return Medicine(
            id=self.medicine.id,
            name=self.name_edit.text(),
            price_rs=self.price_spin.value(),
            manufacturer_name=self.manufacturer_combo.currentText(),
            type=self.type_combo.currentText(),
            pack_size_label=self.pack_edit.text(),
            composition1=self.comp1_combo.currentText(),
            composition2=self.comp2_combo.currentText(),
        ).validate()


class ManufacturerDialog(BaseEditDialog):
    def __init__(self, manufacturer: Manufacturer, parent: QWidget | None = None) -> None:
        super().__init__(
            "Edit manufacturer" if manufacturer.id else "Add manufacturer", parent
        )
        self.manufacturer = manufacturer
        self.id_edit = QLineEdit(str(manufacturer.id) if manufacturer.id else "auto")
        self.id_edit.setReadOnly(True)
        self.name_edit = QLineEdit(manufacturer.name)
        self.name_edit.setPlaceholderText("e.g. Sun Pharmaceutical Industries Ltd")
        self.form.addRow("ID", self.id_edit)
        self.form.addRow("Name", self.name_edit)
        self.name_edit.selectAll()

    def payload(self) -> Manufacturer:
        return Manufacturer(id=self.manufacturer.id, name=self.name_edit.text()).validate()


class CompositionDialog(BaseEditDialog):
    def __init__(self, composition: Composition, parent: QWidget | None = None) -> None:
        super().__init__(
            "Edit composition" if composition.id else "Add composition", parent
        )
        self.composition = composition
        self.id_edit = QLineEdit(str(composition.id) if composition.id else "auto")
        self.id_edit.setReadOnly(True)
        self.text_edit = QLineEdit(composition.text)
        self.text_edit.setPlaceholderText("e.g. Paracetamol (325mg)")
        self.form.addRow("ID", self.id_edit)
        self.form.addRow("Text", self.text_edit)
        self.text_edit.selectAll()

    def payload(self) -> Composition:
        return Composition(id=self.composition.id, text=self.text_edit.text()).validate()


def confirm(parent: QWidget | None, title: str, text: str) -> bool:
    answer = QMessageBox.question(
        parent,
        title,
        text,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return answer == QMessageBox.StandardButton.Yes


class LoginDialog(QDialog):
    """Username / password prompt; also hosts first-run admin creation."""

    def __init__(
        self,
        needs_bootstrap: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sign in" if not needs_bootstrap else "Create admin account")
        self.setModal(True)
        self.setMinimumWidth(340)
        self.user: User | None = None
        self._needs_bootstrap = needs_bootstrap

        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("Username")
        self.password_edit = QLineEdit()
        self.password_edit.setPlaceholderText("Password")
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_edit = QLineEdit()
        self.confirm_edit.setPlaceholderText("Confirm password")
        self.confirm_edit.setEchoMode(QLineEdit.EchoMode.Password)

        self.error_label = QLabel("")
        self.error_label.setObjectName("error")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        self.buttons.accepted.connect(self._try_accept)
        self.buttons.rejected.connect(self.reject)

        form = QFormLayout()
        form.addRow("Username", self.username_edit)
        form.addRow("Password", self.password_edit)
        if needs_bootstrap:
            form.addRow("Confirm", self.confirm_edit)
            note = QLabel(
                "No users exist yet. The first account is created as an admin."
            )
            note.setObjectName("muted")
            note.setWordWrap(True)
        else:
            note = QLabel("")
            note.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(10)
        layout.addWidget(note)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addWidget(self.buttons, 0, Qt.AlignmentFlag.AlignRight)
        self.username_edit.setFocus()

    def _try_accept(self) -> None:
        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        if not username or not password:
            self._show_error("Username and password are required.")
            return
        if self._needs_bootstrap:
            if password != self.confirm_edit.text():
                self._show_error("Passwords do not match.")
                return
            # The caller creates the user; we only validate the shape here.
            try:
                hash_password(password)
            except ValidationError as exc:
                self._show_error(str(exc))
                return
            self._pending = (username, password)
            self._show_error("")
            self.accept()
            return
        self._pending = (username, password)
        self._show_error("")
        self.accept()

    def credentials(self) -> tuple[str, str]:
        return getattr(self, "_pending", ("", ""))

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(bool(message))


def ask_login(
    parent: QWidget | None, needs_bootstrap: bool
) -> tuple[str, str] | None:
    """Return ``(username, password)`` or None when the user cancels."""
    dialog = LoginDialog(needs_bootstrap, parent)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.credentials()
    return None


def info(parent: QWidget | None, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)


def warn(parent: QWidget | None, title: str, text: str) -> None:
    QMessageBox.warning(parent, title, text)


def ask_text(
    parent: QWidget | None, title: str, label: str, default: str = ""
) -> str | None:
    text, accepted = QInputDialog.getText(parent, title, label, text=default)
    return text if accepted else None
