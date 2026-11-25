"""Transcription settings shown at the top of the main window.

Importing a file used to open a settings window every time. With this panel,
the settings stay visible above the task list and imported files are queued
right away with whatever the panel currently shows.
"""

import copy
from typing import Optional, List, Tuple

from PyQt6.QtCore import pyqtSignal, Qt, QThreadPool
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QToolButton,
    QLabel,
    QGroupBox,
    QMessageBox,
    QSizePolicy,
)

from buzz.dialogs import show_model_download_error_dialog
from buzz.locale import _
from buzz.model_loader import ModelDownloader, WhisperModelSize, ModelType
from buzz.settings.settings import Settings
from buzz.store.keyring_store import get_password, Key
from buzz.transcriber.transcriber import (
    FileTranscriptionOptions,
    TranscriptionOptions,
)
from buzz.widgets.model_download_progress_dialog import ModelDownloadProgressDialog
from buzz.widgets.preferences_dialog.models.file_transcription_preferences import (
    FileTranscriptionPreferences,
)
from buzz.widgets.transcriber.file_transcription_form_widget import (
    FileTranscriptionFormWidget,
)
from buzz.widgets.transcriber.speaker_identification_options_widget import (
    SpeakerIdentificationOptions,
    SpeakerIdentificationOptionsWidget,
    is_speaker_identification_available,
)


def can_run_with_options(transcription_options: TranscriptionOptions) -> bool:
    """False when the chosen model still needs a Hugging Face model ID."""
    model = transcription_options.model
    if (
        model.model_type == ModelType.FASTER_WHISPER
        and model.whisper_model_size == WhisperModelSize.CUSTOM
        and model.hugging_face_model_id == ""
    ):
        return False
    if model.model_type == ModelType.HUGGING_FACE and model.hugging_face_model_id == "":
        return False
    return True


class TranscriptionSettingsPanel(QWidget):
    """Always-visible file transcription settings.

    Emits ``triggered`` with the same tuple as ``FileTranscriberWidget``:
    (TranscriptionOptions, FileTranscriptionOptions, model path,
    SpeakerIdentificationOptions).
    """

    triggered = pyqtSignal(tuple)
    openai_access_token_changed = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("TranscriptionSettingsPanel")

        self.settings = Settings()
        self.model_loader: Optional[ModelDownloader] = None
        self.model_download_progress_dialog: Optional[ModelDownloadProgressDialog] = None
        # Imports that wait for a model download, each with its own options
        self.pending_requests: List[
            Tuple[TranscriptionOptions, FileTranscriptionOptions, SpeakerIdentificationOptions]
        ] = []

        preferences = self.load_preferences()
        (
            self.transcription_options,
            self.file_transcription_options,
        ) = preferences.to_transcription_options(
            openai_access_token=get_password(Key.OPENAI_API_KEY),
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 0)
        layout.setSpacing(2)

        # Header: collapse arrow, title and a hint on how to start
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)

        self.toggle_button = QToolButton(self)
        self.toggle_button.setObjectName("TranscriptionSettingsToggleButton")
        self.toggle_button.setText(_("Transcription settings"))
        self.toggle_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.toggle_button.setCheckable(True)
        self.toggle_button.setAutoRaise(True)
        self.toggle_button.toggled.connect(self.set_expanded)

        hint_label = QLabel(
            _("Drop files here or use Import to start transcribing with these settings"),
            self,
        )
        hint_label.setEnabled(False)  # dimmed, it is only a hint
        # Let the hint get cut off rather than widen the window
        hint_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )

        header_layout.addWidget(self.toggle_button)
        header_layout.addStretch()
        header_layout.addWidget(hint_label)
        layout.addLayout(header_layout)

        # Body: the same form the settings window uses, plus speaker options
        self.body = QWidget(self)
        body_layout = QHBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)

        self.form_widget = FileTranscriptionFormWidget(
            transcription_options=self.transcription_options,
            file_transcription_options=self.file_transcription_options,
            parent=self.body,
        )
        self.form_widget.openai_access_token_changed.connect(
            self.openai_access_token_changed
        )
        self.form_widget.transcription_options_changed.connect(
            self.on_transcription_options_changed
        )
        body_layout.addWidget(self.form_widget, 1)

        self.speaker_identification_options = self.load_speaker_identification_options()
        self.speaker_identification_options_widget: Optional[
            SpeakerIdentificationOptionsWidget
        ] = None
        if is_speaker_identification_available():
            group_box = QGroupBox(_("Speaker identification"), self.body)
            group_box.setObjectName("SpeakerIdentificationGroupBox")
            self.speaker_identification_options_widget = SpeakerIdentificationOptionsWidget(
                self.speaker_identification_options, parent=group_box
            )
            self.speaker_identification_options_widget.options_changed.connect(
                self.on_speaker_identification_options_changed
            )
            group_layout = QVBoxLayout(group_box)
            group_layout.addWidget(self.speaker_identification_options_widget)
            body_layout.addWidget(group_box, 0, Qt.AlignmentFlag.AlignTop)
        else:
            self.speaker_identification_options.identify_speakers = False

        layout.addWidget(self.body)

        collapsed = self.settings.value(
            Settings.Key.FILE_TRANSCRIBER_PANEL_COLLAPSED, False
        )
        self.toggle_button.setChecked(not collapsed)
        self.set_expanded(not collapsed)

    # Preferences

    def load_preferences(self) -> FileTranscriptionPreferences:
        # Same group as the settings window, so both show the same choices
        self.settings.settings.beginGroup("file_transcriber")
        preferences = FileTranscriptionPreferences.load(settings=self.settings.settings)
        self.settings.settings.endGroup()
        return preferences

    def save_preferences(self) -> None:
        self.settings.settings.beginGroup("file_transcriber")
        preferences = FileTranscriptionPreferences.from_transcription_options(
            self.transcription_options, self.file_transcription_options
        )
        preferences.save(settings=self.settings.settings)
        if self.speaker_identification_options_widget is not None:
            self.speaker_identification_options.save(self.settings.settings)
        self.settings.settings.endGroup()
        self.settings.settings.sync()

    def load_speaker_identification_options(self) -> SpeakerIdentificationOptions:
        self.settings.settings.beginGroup("file_transcriber")
        options = SpeakerIdentificationOptions.load(self.settings.settings)
        self.settings.settings.endGroup()
        return options

    def reload_preferences(self) -> None:
        """Pick up choices saved elsewhere, e.g. in the settings window."""
        preferences = self.load_preferences()
        (
            self.transcription_options,
            self.file_transcription_options,
        ) = preferences.to_transcription_options(
            openai_access_token=get_password(Key.OPENAI_API_KEY),
        )
        self.speaker_identification_options = self.load_speaker_identification_options()
        if self.speaker_identification_options_widget is None:
            self.speaker_identification_options.identify_speakers = False

        body_layout = self.body.layout()
        old_form = self.form_widget
        self.form_widget = FileTranscriptionFormWidget(
            transcription_options=self.transcription_options,
            file_transcription_options=self.file_transcription_options,
            parent=self.body,
        )
        self.form_widget.openai_access_token_changed.connect(
            self.openai_access_token_changed
        )
        self.form_widget.transcription_options_changed.connect(
            self.on_transcription_options_changed
        )
        body_layout.replaceWidget(old_form, self.form_widget)
        old_form.deleteLater()

    def on_transcription_options_changed(
        self, options: Tuple[TranscriptionOptions, FileTranscriptionOptions]
    ) -> None:
        self.transcription_options, self.file_transcription_options = options
        self.save_preferences()

    def on_speaker_identification_options_changed(
        self, options: SpeakerIdentificationOptions
    ) -> None:
        self.speaker_identification_options = options
        self.save_preferences()

    # Collapsing

    def set_expanded(self, expanded: bool) -> None:
        self.body.setVisible(expanded)
        self.toggle_button.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.settings.set_value(Settings.Key.FILE_TRANSCRIBER_PANEL_COLLAPSED, not expanded)

    # Starting transcriptions

    def start(
        self, file_paths: Optional[List[str]] = None, url: Optional[str] = None
    ) -> bool:
        """Queue files or a URL with the current settings.

        Returns False if the settings are incomplete and nothing was queued.
        """
        if not can_run_with_options(self.transcription_options):
            self.toggle_button.setChecked(True)
            QMessageBox.warning(
                self,
                _("Transcription settings"),
                _("Choose a Hugging Face model in the transcription settings first."),
            )
            return False

        # Snapshot the settings, so changing the panel later doesn't change
        # files that are already queued
        transcription_options = copy.deepcopy(self.transcription_options)
        file_transcription_options = FileTranscriptionOptions(
            file_paths=list(file_paths) if file_paths is not None else None,
            url=url,
            output_formats=set(self.file_transcription_options.output_formats),
        )
        speaker_options = copy.deepcopy(self.speaker_identification_options)
        self.pending_requests.append(
            (transcription_options, file_transcription_options, speaker_options)
        )

        if self.model_loader is not None:
            # A download is already running; these files start when it ends
            return True

        model_path = transcription_options.model.get_local_model_path()
        if model_path is not None:
            self.on_model_loaded(model_path)
            return True

        self.form_widget.setEnabled(False)
        self.model_loader = ModelDownloader(model=transcription_options.model)
        self.model_loader.signals.progress.connect(self.on_download_model_progress)
        self.model_loader.signals.error.connect(self.on_download_model_error)
        self.model_loader.signals.finished.connect(self.on_model_loaded)
        QThreadPool().globalInstance().start(self.model_loader)
        return True

    def on_model_loaded(self, model_path: str) -> None:
        self.model_loader = None
        self.reset_model_download()
        self.form_widget.setEnabled(True)

        requests, self.pending_requests = self.pending_requests, []

        for transcription_options, file_transcription_options, speaker_options in requests:
            if (
                model_path == ""
                and transcription_options.model.model_type != ModelType.OPEN_AI_WHISPER_API
            ):
                show_model_download_error_dialog(
                    self,
                    _("Model path is empty. Check BUZZ_MODEL_ROOT and ensure the model is available offline"),
                )
                return

            self.triggered.emit(
                (
                    transcription_options,
                    file_transcription_options,
                    model_path,
                    speaker_options,
                )
            )

    def on_download_model_progress(self, progress: Tuple[float, float]) -> None:
        (current_size, total_size) = progress

        if self.model_download_progress_dialog is None:
            self.model_download_progress_dialog = ModelDownloadProgressDialog(
                model_type=self.transcription_options.model.model_type, parent=self
            )
            self.model_download_progress_dialog.canceled.connect(
                self.on_cancel_model_progress_dialog
            )

        if total_size > 0:
            self.model_download_progress_dialog.set_value(
                fraction_completed=current_size / total_size
            )

    def on_download_model_error(self, error: str) -> None:
        self.model_loader = None
        self.pending_requests = []
        self.reset_model_download()
        self.form_widget.setEnabled(True)
        show_model_download_error_dialog(self, error)

    def on_cancel_model_progress_dialog(self) -> None:
        if self.model_loader is not None:
            self.model_loader.cancel()
        self.model_loader = None
        self.pending_requests = []
        self.reset_model_download()
        self.form_widget.setEnabled(True)

    def reset_model_download(self) -> None:
        if self.model_download_progress_dialog is not None:
            self.model_download_progress_dialog.close()
            self.model_download_progress_dialog = None

    def cancel(self) -> None:
        """Stop a model download, e.g. when the main window closes."""
        if self.model_loader is not None:
            self.model_loader.cancel()
            self.model_loader = None
        self.pending_requests = []
