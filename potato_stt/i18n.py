"""Minimal UI localization helpers (English + Russian)."""

from __future__ import annotations

from PySide6.QtCore import QLocale, QSettings

from potato_stt.settings_keys import (
    UI_LANGUAGE,
    UI_LANGUAGE_AUTO,
    UI_LANGUAGE_EN,
    UI_LANGUAGE_RU,
)

_current_language = UI_LANGUAGE_EN


_RU: dict[str, str] = {
    "Potato STT": "Potato STT",
    "Options": "Настройки",
    "Language:": "Язык:",
    "Auto (follow OS)": "Авто (по языку ОС)",
    "English": "English",
    "Russian": "Русский",
    "Launch Potato STT at Windows startup": "Запускать Potato STT при старте Windows",
    "Launch at startup is only available on Windows.": "Автозапуск доступен только в Windows.",
    "Start minimized": "Запускать свернутым",
    "Play start/stop audio cues": "Воспроизводить звуковые сигналы старта/остановки",
    "Show recording and web-search visual cues": "Показывать визуальные индикаторы записи и веб-поиска",
    "Push-to-talk keys (hold any of these):": "Клавиши push-to-talk (удерживайте любую):",
    "Add key…": "Добавить клавишу…",
    "Remove selected": "Удалить выбранное",
    "Enable web search": "Включить веб-поиск",
    "Hold to Ask Web — shortcut keys (hold any of these):": "Hold to Ask Web — горячие клавиши (удерживайте любую):",
    "Multi-tap delay (ms):": "Задержка multi-tap (мс):",
    "Multi-tap gesture:": "Жест multi-tap:",
    "Web search command (leave empty for built-in OpenCode):": "Команда веб-поиска (пусто — встроенный OpenCode):",
    "Remove filler words and phrases from transcripts": "Удалять слова-паразиты и фразы из транскриптов",
    "Words/phrases to strip (one per line or comma-separated):": "Слова/фразы для удаления (по одной в строке или через запятую):",
    "Translate push-to-talk transcripts to English (Russian → English, local model)": "Переводить push-to-talk в английский (русский → английский, локальная модель)",
    "Potato STT — Push-to-talk": "Potato STT — Push-to-talk",
    "Initializing...": "Инициализация...",
    "Hold to Ask Web": "Удерживайте для веб-запроса",
    "Web history": "История веб-поиска",
    "&File": "&Файл",
    "Transcribe media file…": "Транскрибировать медиафайл…",
    "&Quit": "&Выход",
    "&Settings": "&Настройки",
    "&Options…": "&Параметры…",
    "Web search &history…": "&История веб-поиска…",
    "&Help": "&Справка",
    "Using Potato STT…": "Как использовать Potato STT…",
    "Clear local data (uninstall caches)…": "Очистить локальные данные (удалить кэши)…",
    "Show": "Показать",
    "Clear local data…": "Очистить локальные данные…",
    "Quit": "Выход",
    "Ready. Hold {ptt} to talk.": "Готово. Удерживайте {ptt}, чтобы говорить.",
    "{ptt} — recording...": "{ptt} — идет запись...",
    "Speech engine is still initializing.": "Речевой движок еще инициализируется.",
    "Recording web query... release key to search.": "Запись веб-запроса... отпустите клавишу для поиска.",
    "Web search is disabled in Options.": "Веб-поиск отключен в настройках.",
    "Busy transcribing; try again in a moment.": "Идет распознавание; попробуйте через секунду.",
    "Recording web query... release button to search.": "Запись веб-запроса... отпустите кнопку для поиска.",
    "Open past web searches.": "Открыть прошлые веб-поиски.",
    "Open past web searches. ({unread} unread.)": "Открыть прошлые веб-поиски. ({unread} непрочит.).",
    "Web search": "Веб-поиск",
    "Another instance of Potato STT is already running.": "Другой экземпляр Potato STT уже запущен.",
    "Language preference saved. Restart Potato STT to apply all labels.": "Настройка языка сохранена. Перезапустите Potato STT, чтобы применить все подписи.",
    "Using Potato STT": "Как использовать Potato STT",
    "Hold {ptt_phrase} to record. Release when you are done; the text is transcribed and pasted into the application that had keyboard focus when you pressed the key (and also appears in this window).": "Удерживайте {ptt_phrase}, чтобы записывать речь. Отпустите, когда закончите; текст будет распознан и вставлен в приложение, которое было в фокусе при нажатии клавиши (а также появится в этом окне).",
    "Use the Hold to Ask Web button (or optional shortcuts in Options) to record a web query; a small on-screen cue shows while recording and while OpenCode searches.": "Используйте кнопку «Удерживайте для веб-запроса» (или дополнительные горячие клавиши в настройках), чтобы записать веб-запрос; небольшой индикатор на экране показывается во время записи и пока OpenCode ищет в сети.",
    "Use File → Transcribe media file… to transcribe an existing audio or video file.": "Используйте Файл → Транскрибировать медиафайл…, чтобы распознать существующий аудио- или видеофайл.",
    "Use Settings → Options… (Ctrl+,) to change push-to-talk keys, startup behavior, filters, audio/visual cues, web search, and optional translation.": "Используйте Настройки → Параметры… (Ctrl+,), чтобы изменить клавиши push-to-talk, поведение запуска, фильтры, звуковые/визуальные индикаторы, веб-поиск и опциональный перевод.",
    "When a system tray icon is available:": "Когда доступен значок в системном трее:",
    "• The window close button (X) hides this window to the tray without quitting; minimize uses the taskbar as usual.": "• Кнопка закрытия окна (X) прячет окно в трей без выхода из приложения; сворачивание работает как обычно в панели задач.",
    "• Double-click the tray icon to show the window again.": "• Дважды щелкните значок в трее, чтобы снова показать окно.",
    "• Use File → Quit (Ctrl+Q) or the tray menu Quit to exit completely.": "• Используйте Файл → Выход (Ctrl+Q) или пункт Выход в меню трея для полного завершения.",
    "No system tray icon is available on this session; use File → Quit (Ctrl+Q) to exit.": "В этой сессии значок системного трея недоступен; используйте Файл → Выход (Ctrl+Q), чтобы завершить работу.",
    "Clear local data": "Очистить локальные данные",
    "Cleanup script not found:\n{script}\n\nFrom source, run scripts\\Clear-PotatoSTTData.ps1 from the repository root.": "Скрипт очистки не найден:\n{script}\n\nПри запуске из исходников выполните scripts\\Clear-PotatoSTTData.ps1 из корня репозитория.",
    "This removes the Parakeet install folder, Hugging Face ONNX model downloads, saved options (push-to-talk keys, etc.), and Windows startup Run entries for Potato STT / Pipit Clone.\n\nQuit Potato STT first; the script will try to stop PotatoSTT.exe if it is still running.": "Это удалит папку установки Parakeet, загрузки ONNX-моделей Hugging Face, сохраненные настройки (клавиши push-to-talk и т.д.) и записи автозапуска Windows для Potato STT / Pipit Clone.\n\nСначала закройте Potato STT; скрипт попытается остановить PotatoSTT.exe, если процесс все еще запущен.",
    "Open folder": "Открыть папку",
    "Run in PowerShell": "Запустить в PowerShell",
    "Script path:\n{script}": "Путь к скрипту:\n{script}",
    "Could not start PowerShell:\n{e}": "Не удалось запустить PowerShell:\n{e}",
    "FFmpeg required": "Требуется FFmpeg",
    "FFmpeg is not installed or not on PATH. It is needed for most audio and video file formats.": "FFmpeg не установлен или не найден в PATH. Он нужен для большинства аудио- и видеоформатов.",
    "Command (select and copy):": "Команда (выделите и скопируйте):",
    "Install FFmpeg with winget…": "Установить FFmpeg через winget…",
    "Open FFmpeg download page...": "Открыть страницу загрузки FFmpeg...",
    "FFmpeg install": "Установка FFmpeg",
    "A command window should open to install FFmpeg via winget.\n\nWhen it finishes successfully, restart Potato STT (or sign out of Windows) so ffmpeg and ffprobe are picked up from PATH.": "Должно открыться окно командной строки для установки FFmpeg через winget.\n\nПосле успешного завершения перезапустите Potato STT (или выйдите из Windows и войдите снова), чтобы ffmpeg и ffprobe подхватились из PATH.",
    "Could not start winget. Install FFmpeg manually from the download page, or run in a terminal:\n\n{cmd}": "Не удалось запустить winget. Установите FFmpeg вручную со страницы загрузки или выполните в терминале:\n\n{cmd}",
    "Local translation — notice": "Локальный перевод — уведомление",
    "Local Russian → English translation will:\n• Paste English into the app that had focus; this window lists the recognized text and the English wording (when it differs).\n• After you choose **Agree**, the Marian model (~300 MB from the internet) downloads in the background if it is not already on this PC (saved in your Hugging Face cache). Watch the main window status line for progress.\n• Run on your PC using PyTorch on the CPU.\n\nChoose **Agree** to enable translation and start the download when needed, or **Refuse** to cancel.": "Локальный перевод с русского на английский будет:\n• Вставлять английский текст в приложение, которое было в фокусе; в этом окне отображается распознанный текст и английская формулировка (когда она отличается).\n• После выбора **Согласен** модель Marian (~300 МБ из интернета) загрузится в фоне, если ее еще нет на этом ПК (сохраняется в кэше Hugging Face). Прогресс смотрите в строке статуса главного окна.\n• Работать на вашем ПК через PyTorch на CPU.\n\nВыберите **Согласен**, чтобы включить перевод и запустить загрузку при необходимости, или **Отказаться**, чтобы отменить.",
    "Refuse": "Отказаться",
    "Agree": "Согласен",
    "Add push-to-talk key": "Добавить клавишу push-to-talk",
    "Press a keyboard key, click a mouse button, or hold modifiers then press a key.\nFor modifier-only chords, hold both modifiers (for example Ctrl+Shift) and release one.\nEscape cancels.": "Нажмите клавишу на клавиатуре, кнопку мыши или удерживайте модификаторы и нажмите клавишу.\nДля сочетаний только из модификаторов удерживайте оба модификатора (например Ctrl+Shift) и отпустите один.\nEscape отменяет.",
    "Web search summary": "Сводка веб-поиска",
    "Web search history": "История веб-поиска",
    "Unread — open to mark as read.": "Непрочитано — откройте, чтобы пометить как прочитанное.",
    "Opened before (read).": "Открывалось ранее (прочитано).",
    "When a system tray icon is available, the main window stays hidden until you open it from the tray. Otherwise the window opens minimized to the taskbar.": "Если доступен значок системного трея, главное окно остается скрытым, пока вы не откроете его из трея. Иначе окно открывается свернутым в панели задач.",
    "Play a short sound when microphone recording starts and stops.": "Воспроизводить короткий звук при начале и окончании записи микрофона.",
    "Show the small on-screen overlays while recording or searching.": "Показывать небольшие экранные индикаторы во время записи или поиска.",
    "Recording continues while at least one bound key or button is held. If you remove every key, Right Ctrl is used again.": "Запись продолжается, пока удерживается хотя бы одна назначенная клавиша или кнопка. Если удалить все клавиши, снова будет использоваться Right Ctrl.",
    "Controls Hold to Ask Web, web-search hotkeys, and double-tap web search.": "Управляет Hold to Ask Web, горячими клавишами веб-поиска и веб-поиском по двойному нажатию.",
    "Hold a bound key or mouse button to record a web query (same as the main-window button). Release to transcribe and run your configured web-search command (built-in OpenCode when empty). If the list is empty, only the button works. If a key is also a push-to-talk key, push-to-talk takes priority.": "Удерживайте назначенную клавишу или кнопку мыши, чтобы записать веб-запрос (как кнопка в главном окне). Отпустите, чтобы распознать и выполнить настроенную команду веб-поиска (встроенный OpenCode, если поле пустое). Если список пуст, работает только кнопка. Если клавиша также назначена для push-to-talk, приоритет у push-to-talk.",
    "Multi-tap push-to-talk keys for web search (same physical key as dictation)": "Использовать multi-tap на клавишах push-to-talk для веб-поиска (та же физическая клавиша, что и для диктовки)",
    "When enabled, a push-to-talk key can also start a web query using the gesture you select below. The delay applies between taps/clicks and before dictation starts on a plain hold.": "Если включено, клавиша push-to-talk может также запускать веб-запрос жестом, выбранным ниже. Задержка применяется между нажатиями/кликами и перед началом диктовки при обычном удержании.",
    " ms": " мс",
    "Maximum time between tap release and the next press (multi-tap), and how long to wait before treating a single hold as normal dictation.": "Максимальное время между отпусканием и следующим нажатием (multi-tap), а также сколько ждать перед тем, как считать одиночное удержание обычной диктовкой.",
    "Once, release, then press-and-hold — web search (hold alone — dictation)": "Один раз, отпустить, затем нажать и удерживать — веб-поиск (простое удержание — диктовка)",
    "Double-tap-then-hold — dictation; third tap — start web search": "Двойное нажатие и удержание — диктовка; третье нажатие — запуск веб-поиска",
    "Example: opencode run --format default \"{prompt}\"   — placeholders: {query}, {prompt}, {query_json}": "Пример: opencode run --format default \"{prompt}\"   — плейсхолдеры: {query}, {prompt}, {query_json}",
    "Run command through the system shell (cmd.exe) — less safe; enables pipes/redirection": "Выполнять команду через системную оболочку (cmd.exe) — менее безопасно; включает пайпы/перенаправление",
    "Case-insensitive whole-word or whole-phrase removal after normalization. Affects push-to-talk, file transcription, and subtitle export.": "Удаление целых слов или фраз без учета регистра после нормализации. Влияет на push-to-talk, транскрибацию файлов и экспорт субтитров.",
    "um\nyou know": "ээ\nну знаешь",
    "Lines starting with # are ignored. Longer phrases are removed before shorter ones.": "Строки, начинающиеся с #, игнорируются. Более длинные фразы удаляются раньше коротких.",
    "After each utterance, paste English into the target app. This window shows the recognition and an English line when the translation differs. After you agree in the notice dialog, the Marian model (~300 MB) downloads from Hugging Face in the background if it is not already on this PC. Uses PyTorch on the CPU.": "После каждого высказывания в целевое приложение вставляется английский текст. В этом окне показывается распознавание и английская строка, если перевод отличается. После согласия в диалоге уведомления модель Marian (~300 МБ) загружается из Hugging Face в фоне, если ее еще нет на этом ПК. Используется PyTorch на CPU.",
    "Add hold-to-ask-web key": "Добавить клавишу для hold-to-ask-web",
    "That key is already in the list.": "Эта клавиша уже есть в списке.",
    "Push-to-talk": "Push-to-talk",
    "Startup setting": "Параметр автозапуска",
    "Could not update the Windows startup entry:\n{e}": "Не удалось обновить запись автозапуска Windows:\n{e}",
    "Press and hold to record a web search query. Release to transcribe and ask OpenCode for a web summary.": "Нажмите и удерживайте, чтобы записать веб-запрос. Отпустите, чтобы распознать и отправить запрос в OpenCode для сводки.",
    "Open past web searches. Highlights when there are unread results.": "Открыть прошлые веб-поиски. Подсвечивается, когда есть непрочитанные результаты.",
    "Starting...": "Запуск...",
    "Transcribe file": "Транскрибировать файл",
    "The speech engine is still getting ready. Wait until startup finishes, then try again.": "Речевой движок еще подготавливается. Дождитесь завершения запуска и попробуйте снова.",
    "A file transcription is already in progress.": "Транскрибация файла уже выполняется.",
    "Open audio or video": "Открыть аудио или видео",
    "Media (*.wav *.mp3 *.m4a *.aac *.flac *.ogg *.opus *.wma *.mp4 *.mkv *.webm *.mov *.avi);;All files (*.*)": "Медиа (*.wav *.mp3 *.m4a *.aac *.flac *.ogg *.opus *.wma *.mp4 *.mkv *.webm *.mov *.avi);;Все файлы (*.*)",
    "Save subtitles": "Сохранить субтитры",
    "SubRip (*.srt);;WebVTT (*.vtt)": "SubRip (*.srt);;WebVTT (*.vtt)",
    "Failed": "Ошибка",
    "Preparing ONNX ASR engine (first model load may take time)...": "Подготовка ONNX ASR движка (первая загрузка модели может занять время)...",
    "Preparing Parakeet HTTP STT engine (download/first model load may take time)...": "Подготовка Parakeet HTTP STT движка (загрузка/первая загрузка модели может занять время)...",
}


def _normalized_pref(value: str | None) -> str:
    v = (value or "").strip().lower()
    if v in (UI_LANGUAGE_AUTO, UI_LANGUAGE_EN, UI_LANGUAGE_RU):
        return v
    return UI_LANGUAGE_AUTO


def resolved_language(preference: str | None) -> str:
    pref = _normalized_pref(preference)
    if pref == UI_LANGUAGE_EN:
        return UI_LANGUAGE_EN
    if pref == UI_LANGUAGE_RU:
        return UI_LANGUAGE_RU
    for lang in QLocale.system().uiLanguages():
        if lang.lower().startswith("ru"):
            return UI_LANGUAGE_RU
    return UI_LANGUAGE_EN


def init_localization(settings: QSettings) -> str:
    global _current_language
    pref = settings.value(UI_LANGUAGE, UI_LANGUAGE_AUTO, type=str)
    _current_language = resolved_language(pref)
    return _current_language


def tr(text: str) -> str:
    if _current_language == UI_LANGUAGE_RU:
        return _RU.get(text, text)
    return text

