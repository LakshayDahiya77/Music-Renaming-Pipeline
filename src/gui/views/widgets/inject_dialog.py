"""Dialog for injecting metadata (actor, sitename, director, tag, special phrase) into a folder."""

from typing import Optional
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from gui.common.builder import UI
from gui.common.icons import Actions
from gui.common.theme import DARK_THEME
from gui.common.widgets import make_description_label, simple_line
from gui.models.plan_model import PlanItem
from injector import inject_metadata_into_filename

ALL_FOLDERS_LABEL = "[All Directories / Entire Plan]"

class InjectDialog(QDialog):
    """Dialog allowing users to inject actor, site, director, tags, and phrases into all files in a folder."""

    def __init__(self, plan_items: list[PlanItem], initial_folder: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Inject Metadata & Tags into Directory")
        self.resize(650, 520)
        self.plan_items = plan_items

        self._setup_ui(initial_folder)
        self._update_preview()

    def _setup_ui(self, initial_folder: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header description
        desc = make_description_label(
            "Inject metadata into all files within a specified directory. "
            "Actors are placed first and de-duplicated. Sitenames, directors, and tags are added into [Tags]. "
            "Special phrases are added into {Phrases}."
        )
        layout.addWidget(desc)
        layout.addWidget(simple_line())

        # Form Frame
        form_frame = QFrame()
        form_frame.setProperty("panelFrame", True)
        form_layout = QVBoxLayout(form_frame)
        form_layout.setSpacing(10)

        # 1. Target Folder Dropdown
        row_dir = QHBoxLayout()
        lbl_dir = QLabel("Target Directory:")
        lbl_dir.setFixedWidth(130)
        lbl_dir.setStyleSheet("font-weight: bold;")
        row_dir.addWidget(lbl_dir)

        self.combo_folder = (
            UI.combobox()
            .on_text_change(lambda _: self._update_preview())
            .build(self)
        )
        # Extract unique folders from plan items
        unique_folders = sorted(list({item.folder for item in self.plan_items if item.folder}))
        folder_options = [ALL_FOLDERS_LABEL] + unique_folders
        self.combo_folder.addItems(folder_options)

        if initial_folder and initial_folder in folder_options:
            self.combo_folder.setCurrentText(initial_folder)
        row_dir.addWidget(self.combo_folder)
        form_layout.addLayout(row_dir)

        # 2. Actor Name
        row_actor = QHBoxLayout()
        lbl_actor = QLabel("Actor Name:")
        lbl_actor.setFixedWidth(130)
        row_actor.addWidget(lbl_actor)
        self.edit_actor = (
            UI.line_edit()
            .placeholder("e.g., Jane Doe (Placed first, de-duplicated)")
            .on_change(lambda _: self._update_preview())
            .build(self)
        )
        row_actor.addWidget(self.edit_actor)
        form_layout.addLayout(row_actor)

        # 3. Sitename / Studio
        row_site = QHBoxLayout()
        lbl_site = QLabel("Sitename / Studio:")
        lbl_site.setFixedWidth(130)
        row_site.addWidget(lbl_site)
        self.edit_site = (
            UI.line_edit()
            .placeholder("e.g., EvilAngel.com (Added inside [Tags], de-duplicated)")
            .on_change(lambda _: self._update_preview())
            .build(self)
        )
        row_site.addWidget(self.edit_site)
        form_layout.addLayout(row_site)

        # 4. Director
        row_dir_name = QHBoxLayout()
        lbl_dir_name = QLabel("Director:")
        lbl_dir_name.setFixedWidth(130)
        row_dir_name.addWidget(lbl_dir_name)
        self.edit_director = (
            UI.line_edit()
            .placeholder("e.g., Mike Adriano (Added inside [Tags], de-duplicated)")
            .on_change(lambda _: self._update_preview())
            .build(self)
        )
        row_dir_name.addWidget(self.edit_director)
        form_layout.addLayout(row_dir_name)

        # 5. Tag(s)
        row_tag = QHBoxLayout()
        lbl_tag = QLabel("Tag(s):")
        lbl_tag.setFixedWidth(130)
        row_tag.addWidget(lbl_tag)
        self.edit_tag = (
            UI.line_edit()
            .placeholder("e.g., Anal, DP (Added inside [Tags], comma-separated)")
            .on_change(lambda _: self._update_preview())
            .build(self)
        )
        row_tag.addWidget(self.edit_tag)
        form_layout.addLayout(row_tag)

        # 6. Special Phrase
        row_phrase = QHBoxLayout()
        lbl_phrase = QLabel("Special Phrase:")
        lbl_phrase.setFixedWidth(130)
        row_phrase.addWidget(lbl_phrase)
        self.edit_phrase = (
            UI.line_edit()
            .placeholder("e.g., Her Only Scene (Added inside {Phrase})")
            .on_change(lambda _: self._update_preview())
            .build(self)
        )
        row_phrase.addWidget(self.edit_phrase)
        form_layout.addLayout(row_phrase)

        layout.addWidget(form_frame)

        # Live Preview Group
        preview_group = QGroupBox("Live Preview (First matching file)")
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.setSpacing(6)

        self.lbl_match_count = QLabel("Matching Files: 0")
        self.lbl_match_count.setStyleSheet("font-weight: bold; color: #62a0ea;")
        preview_layout.addWidget(self.lbl_match_count)

        self.lbl_orig_title = QLabel("Original: None")
        self.lbl_orig_title.setWordWrap(True)
        self.lbl_orig_title.setStyleSheet("color: #a0a0a0; font-family: monospace; font-size: 12.5px;")
        preview_layout.addWidget(self.lbl_orig_title)

        self.lbl_new_title = QLabel("Proposed: None")
        self.lbl_new_title.setWordWrap(True)
        self.lbl_new_title.setStyleSheet("color: #4caf50; font-family: monospace; font-size: 12.5px; font-weight: bold;")
        preview_layout.addWidget(self.lbl_new_title)

        layout.addWidget(preview_group)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_cancel = (
            UI.button("Cancel")
            .on_click(self.reject)
            .build(self)
        )
        btn_layout.addWidget(self.btn_cancel)

        self.btn_apply = (
            UI.button("Apply Injection")
            .icon(Actions.CHECK)
            .role("primary")
            .on_click(self.accept)
            .build(self)
        )
        btn_layout.addWidget(self.btn_apply)

        layout.addLayout(btn_layout)

    def _get_matching_items(self) -> list[PlanItem]:
        selected_folder = self.combo_folder.currentText()
        if selected_folder == ALL_FOLDERS_LABEL:
            return self.plan_items
        return [
            item for item in self.plan_items
            if item.folder == selected_folder or item.old_path.startswith(selected_folder)
        ]

    def _update_preview(self):
        if not hasattr(self, "lbl_match_count") or not hasattr(self, "combo_folder"):
            return
        matching = self._get_matching_items()
        self.lbl_match_count.setText(f"Matching Files in Scope: {len(matching)} file(s)")

        if not matching:
            self.lbl_orig_title.setText("Original: None")
            self.lbl_new_title.setText("Proposed: None")
            return

        sample = matching[0]
        actor = self.edit_actor.text().strip()
        site = self.edit_site.text().strip()
        director = self.edit_director.text().strip()
        tag = self.edit_tag.text().strip()
        phrase = self.edit_phrase.text().strip()

        preview_new = inject_metadata_into_filename(
            sample.proposed_name,
            actor=actor,
            sitename=site,
            director=director,
            tag=tag,
            special_phrase=phrase,
        )

        self.lbl_orig_title.setText(f"Before: {sample.proposed_name}")
        self.lbl_new_title.setText(f"After:  {preview_new}")

    def get_data(self) -> dict[str, str]:
        selected_folder = self.combo_folder.currentText()
        target_folder = "" if selected_folder == ALL_FOLDERS_LABEL else selected_folder
        return {
            "target_folder": target_folder,
            "actor": self.edit_actor.text().strip(),
            "sitename": self.edit_site.text().strip(),
            "director": self.edit_director.text().strip(),
            "tag": self.edit_tag.text().strip(),
            "special_phrase": self.edit_phrase.text().strip(),
        }
