"""Interface language: English source strings with translations looked up at use time.

Strings are translated when widgets are built, so a language change takes effect the
next time the window is created (Lapicero asks for a restart).
"""

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
from PySide6.QtWidgets import QApplication

DEFAULT_LANGUAGE = "en"
# (label shown in its own language, code), in Settings order.
LANGUAGES = (("English", "en"), ("Español", "es"))

SPANISH = {
    # Library window
    "Select a page, or create a subject, section and page with +.":
        "Selecciona una página, o crea una materia, sección y página con +.",
    "New subject": "Nueva materia",
    "New section": "Nueva sección",
    "New subsection": "Nueva subsección",
    "New page": "Nueva página",
    "Rename…": "Cambiar nombre…",
    "Rename subject": "Cambiar nombre de la materia",
    "Rename section": "Cambiar nombre de la sección",
    "Rename page": "Cambiar nombre de la página",
    "Delete section…": "Eliminar sección…",
    "Delete subject…": "Eliminar materia…",
    "Import old note…": "Importar nota antigua…",
    "Import note…": "Importar nota…",
    "Settings": "Configuración",
    "New subject, section or page": "Nueva materia, sección o página",
    "Search pages": "Buscar páginas",
    "SUBJECTS": "MATERIAS",
    "Grid": "Cuadrícula",
    "Plain": "Lisa",
    "Paper of the selected page": "Papel de la página seleccionada",
    "Fullscreen (F11, Esc to leave)": "Pantalla completa (F11, Esc para salir)",
    "Fullscreen": "Pantalla completa",
    "Zoom out": "Alejar",
    "Reset zoom (Ctrl+0)": "Restablecer zoom (Ctrl+0)",
    "Zoom in": "Acercar",
    "Show/hide sidebar": "Mostrar/ocultar barra lateral",
    "Undo (Ctrl+Z)": "Deshacer (Ctrl+Z)",
    "Redo (Ctrl+Y)": "Rehacer (Ctrl+Y)",
    "Lasso select (L): drag to move, Delete to remove":
        "Selección con lazo (L): arrastra para mover, Supr para eliminar",
    "Hand select (H): click an item, or drag a box around several":
        "Selección con mano (H): haz clic en un elemento o arrastra un recuadro sobre varios",
    "Eraser (E)": "Borrador (E)",
    "{name}: click again for color and width": "{name}: haz clic otra vez para color y grosor",
    "Shapes (S): drag to draw": "Formas (S): arrastra para dibujar",
    "Engineering elements: drag to place axes or symbols":
        "Elementos de ingeniería: arrastra para colocar ejes o símbolos",
    "Ask Claude (A): drag a box around something, then type a question":
        "Preguntar a Claude (A): enmarca algo con un recuadro y escribe una pregunta",
    "Ask": "Preguntar",
    "Leave fullscreen (F11 or Esc)": "Salir de pantalla completa (F11 o Esc)",
    "Width (1–{max}):": "Grosor (1–{max}):",
    "P pen · E eraser · L lasso · H hand · S shapes · A ask Claude · Ctrl+C/V copy/paste · Ctrl+↑/↓ width · "
    "wheel scroll · Shift+wheel sideways · Ctrl+wheel zoom · F11 fullscreen":
        "P lápiz · E borrador · L lazo · H mano · S formas · A preguntar a Claude · Ctrl+C/V copiar/pegar · "
        "Ctrl+↑/↓ grosor · rueda desplazar · Mayús+rueda lateral · Ctrl+rueda zoom · F11 pantalla completa",
    # Pens, colors, shapes and diagrams
    "Black pen": "Lápiz negro",
    "Blue pen": "Lápiz azul",
    "Red pen": "Lápiz rojo",
    "Green pen": "Lápiz verde",
    "Yellow highlighter": "Resaltador amarillo",
    "Pink highlighter": "Resaltador rosa",
    "Black": "Negro",
    "Blue": "Azul",
    "Red": "Rojo",
    "Green": "Verde",
    "Purple": "Morado",
    "Orange": "Naranja",
    "Yellow": "Amarillo",
    "Pink": "Rosa",
    "Cyan": "Cian",
    "Gray": "Gris",
    "Line": "Línea",
    "Arrow": "Flecha",
    "Rectangle": "Rectángulo",
    "Ellipse": "Elipse",
    "Triangle": "Triángulo",
    "XY axes": "Ejes XY",
    "XYZ axes (3D)": "Ejes XYZ (3D)",
    "Integral": "Integral",
    # Save status and dialogs
    "Saved": "Guardado",
    "All changes saved to {path}": "Todos los cambios se guardaron en {path}",
    "Saving…": "Guardando…",
    "Changes are saved when you pause writing": "Los cambios se guardan cuando dejas de escribir",
    "Not saved": "Sin guardar",
    "{title}: {error}. Work remains in memory; retry Save (Ctrl+S).":
        "{title}: {error}. El trabajo sigue en memoria; vuelve a guardar (Ctrl+S).",
    "Library open failed": "No se pudo abrir la biblioteca",
    "Library save failed": "No se pudo guardar la biblioteca",
    "Name:": "Nombre:",
    "Delete subject": "Eliminar materia",
    "Delete \"{name}\" with all of its sections and pages? This cannot be undone.":
        "¿Eliminar \"{name}\" con todas sus secciones y páginas? No se puede deshacer.",
    "Delete section": "Eliminar sección",
    "Delete \"{name}\" with all of its pages and subsections? This cannot be undone.":
        "¿Eliminar \"{name}\" con todas sus páginas y subsecciones? No se puede deshacer.",
    "Import standalone note": "Importar nota independiente",
    "JSON notes (*.json)": "Notas JSON (*.json)",
    "Import failed": "Error al importar",
    "Unsaved library": "Biblioteca sin guardar",
    "Changes are still in memory. Save before closing?":
        "Los cambios siguen en memoria. ¿Guardar antes de cerrar?",
    "AI bridge failed to start: {error}": "No se pudo iniciar el puente de IA: {error}",
    "The AI bridge is not running: {error}": "El puente de IA no está en ejecución: {error}",
    "Could not write {path}: {error}": "No se pudo escribir {path}: {error}",
    # Settings
    "Toolbar size": "Tamaño de la barra de herramientas",
    "Small": "Pequeño",
    "Medium": "Mediano",
    "Large": "Grande",
    "Size of the drawing toolbar buttons": "Tamaño de los botones de la barra de dibujo",
    "Claude model": "Modelo de Claude",
    "Used for new questions; also changeable from the Ask panel.":
        "Se usa en las preguntas nuevas; también se cambia desde el panel Preguntar.",
    "Model that answers Ask Claude questions": "Modelo que responde las preguntas a Claude",
    "Claude effort": "Esfuerzo de Claude",
    "Lower answers faster, higher is more thorough.":
        "Menor responde más rápido; mayor es más minucioso.",
    "How hard Claude thinks": "Cuánto piensa Claude",
    "Language": "Idioma",
    "Restart Lapicero to apply a language change.":
        "Reinicia Lapicero para aplicar el cambio de idioma.",
    "Interface language": "Idioma de la interfaz",
    "Changes apply right away": "Los cambios se aplican al instante",
    "Done": "Listo",
    "Toolbar": "Barra de herramientas",
    "Tick the tools to show and drag them to reorder.":
        "Marca las herramientas a mostrar y arrástralas para reordenarlas.",
    "Reset to default": "Restablecer predeterminados",
    "Customize toolbar…": "Personalizar barra de herramientas…",
    "Undo": "Deshacer",
    "Redo": "Rehacer",
    "Lasso select": "Selección con lazo",
    "Hand select": "Selección con mano",
    "Eraser": "Borrador",
    "Shapes": "Formas",
    "Engineering elements": "Elementos de ingeniería",
    "Paste": "Pegar",
    "New page (Ctrl+N)": "Nueva página (Ctrl+N)",
    "Paste (Ctrl+V)": "Pegar (Ctrl+V)",
    # Ask Claude
    "Claude Code default": "Predeterminado de Claude Code",
    "Default": "Predeterminado",
    "Low": "Bajo",
    "High": "Alto",
    "Extra high": "Muy alto",
    "Max": "Máximo",
    "Ask Claude about this area": "Preguntar a Claude sobre esta zona",
    "What do you want to ask?": "¿Qué quieres preguntar?",
    "Question about the marked area": "Pregunta sobre la zona marcada",
    "Enter sends · Shift+Enter starts a new line · Esc cancels":
        "Intro envía · Mayús+Intro nueva línea · Esc cancela",
    "Enter to send · Esc to cancel": "Intro para enviar · Esc para cancelar",
    "Send": "Enviar",
    "Ask Claude": "Preguntar a Claude",
    "Hide answers": "Ocultar respuestas",
    "Model": "Modelo",
    "Effort": "Esfuerzo",
    "How hard Claude thinks: lower answers faster, higher is more thorough":
        "Cuánto piensa Claude: menor responde más rápido, mayor es más minucioso",
    "Thinking": "Pensando",
    "Thinking…": "Pensando…",
    "Error: {error}": "Error: {error}",
    "New chat": "Nuevo chat",
    "Chats on this page": "Chats de esta página",
    "No chats on this page yet": "Todavía no hay chats en esta página",
    "No answer: the question was interrupted.": "Sin respuesta: la pregunta se interrumpió.",
    "Chat not saved": "Chat sin guardar",
    "Could not save the chat: {error}": "No se pudo guardar el chat: {error}",
    "Start a new conversation": "Empezar una conversación nueva",
    "Question for Claude": "Pregunta para Claude",
    "Enter sends · Shift+Enter starts a new line": "Intro envía · Mayús+Intro nueva línea",
    "Claude is answering…": "Claude está respondiendo…",
    "Ask a follow-up…": "Haz otra pregunta…",
    "Ask Claude anything…": "Pregúntale lo que quieras a Claude…",
    "Continues this conversation": "Sigue esta conversación",
    "Or press A to ask about an area": "O pulsa A para preguntar sobre una zona",
    "Ask a question below, or press A and mark an area of the page to ask about it.":
        "Escribe una pregunta abajo, o pulsa A y marca una zona de la página para preguntar sobre ella.",
    "(Claude returned an empty answer)": "(Claude devolvió una respuesta vacía)",
    "Claude Code failed: {detail}": "Claude Code falló: {detail}",
    "exit code {code}": "código de salida {code}",
    "Claude Code was not found. Install it and sign in once by running `claude` in a terminal, "
    "then ask again.":
        "No se encontró Claude Code. Instálalo e inicia sesión una vez ejecutando `claude` en una "
        "terminal, y vuelve a preguntar.",
    "Claude took more than 5 minutes; the question was cancelled.":
        "Claude tardó más de 5 minutos; se canceló la pregunta.",
}

TRANSLATIONS = {"en": {}, "es": SPANISH}

_language = DEFAULT_LANGUAGE
_qt_translator = None


def language():
    return _language


def set_language(code):
    """Select the interface language; unknown codes fall back to English."""
    global _language
    _language = code if code in TRANSLATIONS else DEFAULT_LANGUAGE
    _install_qt_translator()
    return _language


def tr(text, **values):
    """Translate an English source string, then fill its {placeholders}."""
    translated = TRANSLATIONS[_language].get(text, text)
    return translated.format(**values) if values else translated


def _install_qt_translator():
    """Translate Qt's own strings too (Yes/No/Cancel buttons, file dialogs)."""
    global _qt_translator
    app = QApplication.instance()
    if app is None:
        return
    if _qt_translator is not None:
        app.removeTranslator(_qt_translator)
        _qt_translator = None
    if _language == DEFAULT_LANGUAGE:
        return
    translator = QTranslator(app)
    if translator.load(QLocale(_language), "qtbase", "_",
                       QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
        _qt_translator = translator
