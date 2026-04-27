"""Cross-thread Qt signals used by controllers and the main window."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class AppSignals(QObject):
    statusChanged = Signal(str)
    transcriptAppend = Signal(str)
    transcriptReady = Signal(str)
    errorOccurred = Signal(str)
    ffmpegMissing = Signal(str)
    recordingActive = Signal(bool)
    fileTranscribeDone = Signal(str, str, str, str)
    translationModelPreloadFinished = Signal(bool, str)
    webSearchReady = Signal(str, str)
    webSearchOverlaySyncRequest = Signal()
    micSttBusy = Signal(bool)
    webSearchPipelineJobStarted = Signal()
    webSearchPipelineJobFinished = Signal()
    webSearchJobsChanged = Signal(int)
