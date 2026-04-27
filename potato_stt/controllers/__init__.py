"""Controller classes that own focused slices of `MainWindow` behavior.

Each controller takes the collaborators it needs (QSettings, AppSignals, helper callables)
and exposes a small public API. Controllers do not import or depend on `MainWindow`.
"""
