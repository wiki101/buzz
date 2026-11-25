from unittest.mock import Mock, patch

from pytestqt.qtbot import QtBot

from buzz.model_loader import ModelType, TranscriptionModel, WhisperModelSize
from buzz.settings.settings import Settings
from buzz.transcriber.transcriber import OutputFormat, TranscriptionOptions
from buzz.widgets.transcriber.transcription_settings_panel import (
    TranscriptionSettingsPanel,
    can_run_with_options,
)
from tests.audio import test_audio_path


def _model_path_patch():
    return patch.object(
        TranscriptionModel, "get_local_model_path", return_value="/models/tiny"
    )


class TestTranscriptionSettingsPanel:
    def test_start_emits_triggered_without_a_dialog(self, qtbot: QtBot):
        panel = TranscriptionSettingsPanel()
        qtbot.add_widget(panel)

        mock_triggered = Mock()
        panel.triggered.connect(mock_triggered)

        with _model_path_patch():
            assert panel.start(file_paths=[test_audio_path]) is True

        (
            transcription_options,
            file_transcription_options,
            model_path,
            _speaker_options,
        ) = mock_triggered.call_args[0][0]
        assert file_transcription_options.file_paths == [test_audio_path]
        assert model_path == "/models/tiny"
        assert isinstance(transcription_options, TranscriptionOptions)

    def test_queued_files_keep_settings_from_when_they_were_added(self, qtbot: QtBot):
        panel = TranscriptionSettingsPanel()
        qtbot.add_widget(panel)
        panel.file_transcription_options.output_formats = {OutputFormat.TXT}

        mock_triggered = Mock()
        panel.triggered.connect(mock_triggered)

        with _model_path_patch():
            panel.start(file_paths=[test_audio_path])

        # Changing the panel afterwards must not change the queued task
        panel.transcription_options.language = "fr"
        panel.file_transcription_options.output_formats.add(OutputFormat.SRT)

        transcription_options, file_transcription_options, _, _ = (
            mock_triggered.call_args[0][0]
        )
        assert transcription_options.language != "fr"
        assert file_transcription_options.output_formats == {OutputFormat.TXT}

    def test_collapse_state_is_remembered(self, qtbot: QtBot):
        panel = TranscriptionSettingsPanel()
        qtbot.add_widget(panel)

        panel.toggle_button.setChecked(False)
        assert panel.body.isHidden()
        assert Settings().value(Settings.Key.FILE_TRANSCRIBER_PANEL_COLLAPSED, False)

        panel.toggle_button.setChecked(True)
        assert not panel.body.isHidden()
        assert not Settings().value(
            Settings.Key.FILE_TRANSCRIBER_PANEL_COLLAPSED, False
        )


def test_can_run_requires_hugging_face_model_id():
    options = TranscriptionOptions(
        model=TranscriptionModel(
            model_type=ModelType.HUGGING_FACE, hugging_face_model_id=""
        )
    )
    assert can_run_with_options(options) is False

    options.model.hugging_face_model_id = "openai/whisper-tiny"
    assert can_run_with_options(options) is True

    options = TranscriptionOptions(
        model=TranscriptionModel(
            model_type=ModelType.WHISPER_CPP,
            whisper_model_size=WhisperModelSize.TINY,
        )
    )
    assert can_run_with_options(options) is True
