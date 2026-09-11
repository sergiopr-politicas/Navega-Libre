"""
NavegaLibre — Motor: QtWebEngine Puro (Con Persistencia Local Avanzada)
UI: PyQt6 (Pestaña de Configuración, Personalización, Addons e HISTORIAL)
"""
import sys
import os
import json
import threading
import time
import random
import urllib.request
import urllib.parse
import pdfplumber
from datetime import datetime
from PIL import Image
 
from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
 
# 1. INICIALIZACIÓN CRÍTICA DEL ENTORNO DE WINDOWS
# GPU habilitada — necesaria para renderizar PDFs y páginas complejas
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
 
# 2. IMPORTACIONES BASE DE QT
from PyQt6.QtCore    import QTimer, pyqtSignal, QObject, Qt, QUrl, QThread, pyqtSlot
from PyQt6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
                              QWidget, QLineEdit, QPushButton, QTabWidget,
                              QMenu, QLabel, QDialog, QComboBox, QCheckBox, 
                              QFileDialog, QListWidget, QListWidgetItem, QScrollArea)
from PyQt6.QtGui     import QIcon, QCursor
from PyQt6.QtNetwork import QNetworkProxy
from PyQt6.QtWebChannel import QWebChannel
import base64
import tempfile



# 3. IMPORTACIONES DEL MOTOR WEB
print("  [3a] Importando QWebEngineView...")
from PyQt6.QtWebEngineWidgets import QWebEngineView
print("  [3b] Importando QWebEngineCore...")
from PyQt6.QtWebEngineCore    import (QWebEngineProfile, QWebEngineScript,
                                       QWebEngineSettings, QWebEnginePage)
print("  [3c] Imports WebEngine OK")
 

class PdfBridge(QObject):
    # Señal para pasar el trabajo al hilo principal — evita congelamiento
    pdf_recibido = pyqtSignal(str, bool)  # base64, imprimir
 
    def __init__(self, parent):
        super().__init__()
        self.ventana = parent
        # Conectar señal al slot del hilo principal
        self.pdf_recibido.connect(self._procesar_en_hilo_principal)
 
    @pyqtSlot(str, bool)
    def recibirPdf(self, pdf_base64, imprimir):
        # Este método se llama desde el hilo de WebChannel
        # Emitir señal para que el trabajo pesado ocurra en el hilo principal
        self.pdf_recibido.emit(pdf_base64, imprimir)
 
    def _procesar_en_hilo_principal(self, pdf_base64, imprimir):
        """Se ejecuta en el hilo principal de Qt — seguro para diálogos y OS."""
        try:
            import base64 as b64
            datos = b64.b64decode(pdf_base64)
 
            # Siempre preguntar dónde guardar
            ruta, _ = QFileDialog.getSaveFileName(
                self.ventana,
                "Guardar PDF editado",
                os.path.join(os.environ.get("USERPROFILE",""), "Downloads", "documento_editado.pdf"),
                "PDF (*.pdf)"
            )
            if not ruta:
                return
 
            with open(ruta, "wb") as f:
                f.write(datos)
 
            if imprimir:
                # Imprimir usando el visor del sistema
                try:
                    os.startfile(ruta, "print")
                except Exception:
                    os.startfile(ruta)  # abrir para imprimir manualmente
            else:
                # Solo guardar — abrir para confirmar
                self.ventana.statusBar().showMessage(
                    f"✅ PDF guardado: {os.path.basename(ruta)}", 5000)
 
        except Exception as e:
            print(f"Error PdfBridge: {e}")

    @pyqtSlot(int)
    def notificarBusqueda(self, total_coincidencias):
        """Llamado desde JS para mostrar resultados de búsqueda en la barra de estado."""
        msg = (f"🔍 {total_coincidencias} coincidencias encontradas."
               if total_coincidencias > 0 else "🔍 Sin resultados.")
        self.ventana.statusBar().showMessage(msg, 4000)

from PyQt6.QtWebEngineCore import QWebEngineUrlRequestInterceptor
 
class PaginaPersonalizada(QWebEnginePage):
    """QWebEnginePage que bloquea el menú contextual nativo de Chromium."""
    def __init__(self, perfil, ventana_padre):
        super().__init__(perfil, ventana_padre)
        self._ventana = ventana_padre
 
    def createStandardContextMenu(self):
        from PyQt6.QtWidgets import QMenu
        return QMenu()  # menú vacío — el personalizado lo maneja customContextMenuRequested
 
 
class AntiSpamInterceptor(QWebEngineUrlRequestInterceptor):
    def __init__(self, navegador_padre):
        super().__init__()
        self.navegador = navegador_padre
        # Lista negra de palabras clave típicas de servidores de anuncios y pop-ups
        self.lista_negra = [
            "analytics", "adsense", "doubleclick", "popads", "popunder", 
            "adsystem", "adserver", "tracking", "scorecardresearch", "zedo"
        ]
 
    def interceptRequest(self, info):
        # Solo bloquear cuando el usuario activa explícitamente el antispam
        # Por defecto está DESACTIVADO para no interferir con cookies de login (Canvas, etc.)
        if not getattr(self.navegador, "_antispam", False):
            return

        url_string = info.requestUrl().toString().lower()

        # Nunca bloquear dominios de login/autenticación aunque tengan palabras clave
        dominios_seguros = [
            "instructure.com", "canvas", "google.com", "microsoft.com",
            "outlook.com", "office.com", "zoom.us", "cloudflare.com",
        ]
        for seguro in dominios_seguros:
            if seguro in url_string:
                return  # dejar pasar siempre

        for palabra in self.lista_negra:
            if palabra in url_string:
                info.block(True)
                return

def obtener_ruta_recurso(nombre_archivo):
    """ Obtiene la ruta absoluta de un recurso, compatible con desarrollo y PyInstaller (.exe) """
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller crea una carpeta temporal y guarda la ruta en sys._MEIPASS
        return os.path.join(sys._MEIPASS, nombre_archivo)
    
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), nombre_archivo)
# Carpeta base real donde se encuentra el .exe ejecutable (para persistencia de archivos de escritura)
if hasattr(sys, '_MEIPASS'):
    BASE_DIR_DATOS = os.path.dirname(sys.executable)
else:
    BASE_DIR_DATOS = os.path.dirname(os.path.abspath(__file__))    
 
# 3. CONFIGURACIÓN DE RUTAS LOCALES
BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
FAVORITOS_PATH = os.path.join(BASE_DIR, "favoritos.json")
DESCARGAS_PATH = os.path.join(BASE_DIR, "descargas_historial.json")
CONFIG_PATH    = os.path.join(BASE_DIR, "configuracion_navegador.json")
HISTORIAL_PATH = os.path.join(BASE_DIR, "historial.json")  
PERFIL_DATOS_DIR = os.path.join(BASE_DIR, "Almacenamiento_Sesiones")
 
# Forzar la creación física de la carpeta de almacenamiento de inmediato si no existe
if not os.path.exists(PERFIL_DATOS_DIR):
    os.makedirs(PERFIL_DATOS_DIR, exist_ok=True)

# ── 3. CONFIGURACIÓN DE RECURSOS EMPAQUETADOS (LECTURA) ─────────────────────
# Esta es la variable exacta que debes usar para alimentar tu QWebEngineView o el cargador del editor
EDITOR_PDF_PATH = obtener_ruta_recurso("editor_pdf.html")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
 
CONFIG_DEFAULT = {
    "tema": "Oscuro Premium",
    "idioma": "es-MX",
    "javascript": True,
    "addons_rutas": []
}
 
def _cargar_icono() -> QIcon:
    ruta = os.path.join(BASE_DIR, "world_logo.ico")
    return QIcon(ruta) if os.path.exists(ruta) else QIcon()
 
def _leer(path, default):
    try:
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default, f, ensure_ascii=False, indent=2)
            return default
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except: return default
 
def _guardar(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except: pass
 
SCRIPT_STEALTH = """
(function() {
  // 1. Ocultar huellas de automatizacion
  try { Object.defineProperty(navigator, 'webdriver',  { get: () => undefined }); } catch(e){}
  try { Object.defineProperty(navigator, 'plugins',    { get: () => [1,2,3,4,5] }); } catch(e){}
  try { Object.defineProperty(navigator, 'languages',  { get: () => ['es-MX','es','en-US','en'] }); } catch(e){}
  try { Object.defineProperty(navigator, 'platform',   { get: () => 'Win32' }); } catch(e){}
  try { Object.defineProperty(navigator, 'vendor',     { get: () => 'Google Inc.' }); } catch(e){}
  try { Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 }); } catch(e){}
  try { Object.defineProperty(navigator, 'deviceMemory',        { get: () => 8 }); } catch(e){}
 
  // 2. chrome.runtime completo — cada llamada devuelve algo valido, nunca null
  var _port = {
    postMessage: function() {},
    disconnect:  function() {},
    onMessage:   { addListener: function() {}, removeListener: function() {} },
    onDisconnect:{ addListener: function() {}, removeListener: function() {} }
  };
  if (!window.chrome) window.chrome = {};
  window.chrome.runtime = {
    id:           'navegalibrechrome',
    connect:      function() { return _port; },
    sendMessage:  function(a, b, c) {
      // Aceptar callback o ignorar silenciosamente
      if (typeof c === 'function') c(null);
      else if (typeof b === 'function') b(null);
    },
    onMessage:    { addListener: function() {}, removeListener: function() {}, hasListener: function() { return false; } },
    onConnect:    { addListener: function() {}, removeListener: function() {} },
    onInstalled:  { addListener: function() {} },
    getManifest:  function() { return { version: '1.0', name: 'NavegaLibre' }; },
    getURL:       function(p) { return 'chrome-extension://navegalibrechrome/' + p; },
    lastError:    null
  };
  window.chrome.loadTimes = function() { return {}; };
  window.chrome.csi       = function() { return { startE: Date.now(), onloadT: Date.now(), pageT: 1, tran: 15 }; };
  window.chrome.app       = { isInstalled: false, InstallState: {}, RunningState: {} };
 
  // 3. MediaSource — soporte de codecs H.264/AAC
  if (window.MediaSource) {
    var _s = MediaSource.isTypeSupported.bind(MediaSource);
    MediaSource.isTypeSupported = function(t) {
      if (t.includes('avc1') || t.includes('mp4a') || t.includes('vp9')) return true;
      return _s(t);
    };
  }
 
  // 4. canPlayType
  var _c = HTMLMediaElement.prototype.canPlayType;
  HTMLMediaElement.prototype.canPlayType = function(t) {
    if (t.includes('mp4') || t.includes('avc1') || t.includes('mp4a')) return 'probably';
    return _c.call(this, t);
  };
 
  // 5. Permissions API
  if (navigator.permissions && navigator.permissions.query) {
    var _q = navigator.permissions.query.bind(navigator.permissions);
    navigator.permissions.query = function(p) {
      if (p.name === 'notifications') return Promise.resolve({ state: 'denied' });
      return _q(p).catch(function() { return { state: 'granted' }; });
    };
  }
})();
"""

TEMAS = {
    "Oscuro Premium": """
        QMainWindow, QWidget { background: #282828; color: #e8eaed; }
        QTabWidget::pane { border: none; background: #202124; }
        QTabBar::tab { background: #393d42; padding: 6px 14px; border-radius: 4px 4px 0 0; margin-right: 2px; min-width: 120px; color: #e8eaed; }
        QTabBar::tab:selected { background: #393d42; font-weight: bold; border-bottom: 2px solid #8ab4f8; }
        QLineEdit { background: #35363a; border: 1px solid #5f6368; border-radius: 14px; padding: 4px 12px; color: #e8eaed; }
        QPushButton { background: #35363a; border: none; border-radius: 4px; padding: 6px; font-size: 13px; color: #e8eaed; }
        QPushButton:hover { background: #3c4043; }
        QComboBox, QCheckBox { background: #35363a; color: #e8eaed; padding: 4px; border-radius:4px; }
        QListWidget { background: #292a2d; border: 1px solid #5f6368; color: #e8eaed; padding: 5px; border-radius: 6px; }
    """,
    "Claro Clásico": """
        QMainWindow, QWidget { background: #f1f3f4; color: #202124; }
        QTabWidget::pane { border: none; background: #f1f3f4; }
        QTabBar::tab { background: #e8eaed; padding: 6px 14px; border-radius: 4px 4px 0 0; margin-right: 2px; min-width: 120px; color: #202124; }
        QTabBar::tab:selected { background: #ffffff; font-weight: bold; border-bottom: 2px solid #1a73e8; }
        QLineEdit { background: #ffffff; border: 1px solid #cccccc; border-radius: 14px; padding: 4px 12px; color: #202124; }
        QPushButton { background: #e8eaed; border: none; border-radius: 4px; padding: 6px; font-size: 13px; color: #202124; }
        QPushButton:hover { background: #dcdcdc; }
        QComboBox, QCheckBox { background: #ffffff; color: #202124; padding: 4px; border: 1px solid #cccccc; }
        QListWidget { background: #ffffff; border: 1px solid #cccccc; color: #202124; border-radius: 6px; }
    """,
    "Pink Premium": """
        QMainWindow, QWidget { background: #f54967; color: #ffffff; }
        QTabWidget::pane { border: 1px solid #282828; background: #282828; }
        QTabBar::tab { background: #f6d9de; padding: 6px 14px; border-radius: 4px 4px 0 0; margin-right: 2px; min-width: 120px; color: #282828; }
        QTabBar::tab:selected { background: #f6d9de; font-weight: bold; border-bottom: 2px solid #282828; }
        QLineEdit { background: #f6d9de; border: 1px solid #cccccc; border-radius: 14px; padding: 4px 12px; color: #282828; }
        QPushButton { background: #f6d9de; border: none; border-radius: 4px; padding: 6px; font-size: 13px; color: #f6d9de; }
        QPushButton:hover { background: #f44336; }
        QComboBox, QCheckBox { background: #f6d9de; color: #282828; padding: 4px; border: 1px solid #282828; }
        QListWidget { background: #ffffff; border: 1px solid #282828; color: #282828; border-radius: 6px; }
    """,
    "Orange Premium": """
        QMainWindow, QWidget { background: #ff9913; color: #ffffff; }
        QTabWidget::pane { border: 1px solid #282828; background: #282828; }
        QTabBar::tab { background: #ffad00; padding: 6px 14px; border-radius: 4px 4px 0 0; margin-right: 2px; min-width: 120px; color: #282828; }
        QTabBar::tab:selected { background: #ffad00; font-weight: bold; border-bottom: 2px solid #282828; }
        QLineEdit { background: #ffad00; border: 1px solid #cccccc; border-radius: 14px; padding: 4px 12px; color: #282828; }
        QPushButton { background: #ffad00; border: none; border-radius: 4px; padding: 6px; font-size: 13px; color: #ffad00; }
        QPushButton:hover { background: #ffffff; }
        QComboBox, QCheckBox { background: #fdae44; color: #282828; padding: 4px; border: 1px solid #282828; }
        QListWidget { background: #ffffff; border: 1px solid #282828; color: #282828; border-radius: 6px; }
    """
}

PINTURAS_TEMAS = {
    "La Noche Estrellada (Van Gogh)": {
        "fondo": "#0f172a",       # Azul oscuro profundo
        "barra": "#1e293b",       # Azul noche
        "botones": "#f59e0b",     # Amarillo estrella
        "texto": "#f8fafc"        # Blanco brillante
    },
    "El Grito (Munch)": {
        "fondo": "#292524",       # Gris ceniza oscuro
        "barra": "#44403c",       # Piedra cálida
        "botones": "#ea580c",     # Naranja fuego del cielo
        "texto": "#f5f5f4"
    },
    "La Persistencia de la Memoria (Dalí)": {
        "fondo": "#1c1917",       # Marrón tierra oscuro
        "barra": "#78350f",       # Ocre desierto
        "botones": "#ca8a04",     # Oro viejo reloj
        "texto": "#f5f5f4"
    }
}


def generar_css_personalizado(paleta):
    return f"""
        QMainWindow, QWidget {{ 
            background: {paleta['fondo']}; 
            color: {paleta['texto']}; 
        }}
        QTabWidget::pane {{ border: none; background: {paleta['fondo']}; }}
        QTabBar::tab {{ 
            background: {paleta['barra']}; 
            color: {paleta['texto']}; 
            padding: 6px 14px; 
            border-radius: 4px 4px 0 0; 
            margin-right: 2px; 
        }}
        QTabBar::tab:selected {{ 
            background: {paleta['fondo']}; 
            border-bottom: 2px solid {paleta['botones']}; 
            font-weight: bold; 
        }}
        QLineEdit {{ 
            background: {paleta['barra']}; 
            border: 1px solid {paleta['botones']}; 
            border-radius: 14px; 
            padding: 4px 12px; 
            color: {paleta['texto']}; 
        }}
        QPushButton {{ 
            background: {paleta['barra']}; 
            border: 1px solid {paleta['botones']}; 
            border-radius: 4px; 
            padding: 6px; 
            color: {paleta['texto']}; 
        }}
        QPushButton:hover {{ 
            background: {paleta['botones']}; 
            color: #000000; 
        }}
    """


def extraer_colores_de_imagen(ruta_imagen):
    try:
        img = Image.open(ruta_imagen)
        # Reducimos drásticamente para promediar los colores del cuadro
        img = img.resize((15, 15), Image.Resampling.LANCZOS)
        img = img.convert("RGB")
        
        # Sacamos el color de los pixeles centrales
        color_centro = img.getpixel((7, 7))
        color_esquina = img.getpixel((2, 2))
        
        # Convertimos los canales RGB a formato Hexadecimal para CSS
        hex_fondo = "#{:02x}{:02x}{:02x}".format(max(15, color_centro[0]-30), max(15, color_centro[1]-30), max(15, color_centro[2]-30))
        hex_barra = "#{:02x}{:02x}{:02x}".format(color_centro[0], color_centro[1], color_centro[2])
        hex_boton = "#{:02x}{:02x}{:02x}".format(color_esquina[0], color_esquina[1], color_esquina[2])
        
        return {
            "fondo": hex_fondo,  # Un tono más oscuro del centro
            "barra": hex_barra,  # Color base del centro
            "botones": hex_boton, # Color de contraste de la esquina
            "texto": "#ffffff"   # Texto blanco genérico seguro
        }
    except Exception as e:
        print(f"Error procesando imagen: {e}")
        return PINTURAS_TEMAS["La Noche Estrellada (Van Gogh)"] # Fallback seguro

# ─────────────────────────────────────────────────────────────
# PROXY WORKER (HILO ASÍNCRONO SEGURO DE QT)
# ─────────────────────────────────────────────────────────────
class ProxyWorker(QThread):
    proxy_cambiado = pyqtSignal(str, int)
    proxy_caido    = pyqtSignal()
    log_msg        = pyqtSignal(str)
    
    def __init__(self, intervalo=180):
        super().__init__()
        self.intervalo = intervalo
        self._activo   = False
        self.fuentes = [
            "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/https/data.txt",
            "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/https.txt"
        ]

    def iniciar(self):
        if self.isRunning(): return
        self._activo = True
        self.start()

    def detener(self):
        self._activo = False
        self.proxy_caido.emit()
        self.quit()
        self.wait()

    def run(self):
        while self._activo:
            proxies = self._obtener()
            if proxies and self._activo:
                p = random.choice(proxies)
                self.proxy_cambiado.emit(p[0], p[1])
                self.log_msg.emit(f"🌐 VPN Conectada: {p[0]}:{p[1]}")
                self.msleep(self.intervalo * 1000)
            else:
                self.proxy_caido.emit()
                self.msleep(5000)

    def _obtener(self):
        lista = []
        for url in self.fuentes:
            if not self._activo: break
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=4) as r:
                    for l in r.read().decode('utf-8', errors='ignore').splitlines():
                        if ":" in l:
                            parts = l.strip().split(":")
                            if len(parts) == 2: lista.append((parts[0], int(parts[1])))
                if lista: break
            except: pass
        return lista


# ─────────────────────────────────────────────────────────────
# VENTANA PRINCIPAL
# ─────────────────────────────────────────────────────────────
class NavegaLibre(QMainWindow):
    def __init__(self):
        print("    [4a] super().__init__...")
        super().__init__()
        print("    [4b] setWindowTitle...")
        self.setWindowTitle("Navega Libre")
        self.setGeometry(100, 100, 1300, 850)
        _ico = _cargar_icono()
        if not _ico.isNull():
            self.setWindowIcon(_ico)
        print("    [4c] Leyendo configs...")
        self.config_db     = _leer(CONFIG_PATH, CONFIG_DEFAULT)
        print("    [4d] config OK")
        self.favoritos     = _leer(FAVORITOS_PATH, [])
        print("    [4e] favoritos OK")
        self.historial_dl  = _leer(DESCARGAS_PATH, [])
        print("    [4f] descargas OK")
        self.historial_web = _leer(HISTORIAL_PATH, [])
        print("    [4g] historial OK")
        
        _guardar(CONFIG_PATH, self.config_db)
        _guardar(FAVORITOS_PATH, self.favoritos)
        _guardar(DESCARGAS_PATH, self.historial_dl)
        _guardar(HISTORIAL_PATH, self.historial_web)
        print("    [4h] archivos guardados OK")
 
 
        self._vpn_activo   = False
        self._incognito    = False
 
        # Activa la capacidad de la ventana para recibir archivos arrastrados
        self.setAcceptDrops(True)
 
        print("    [4i] Creando ProxyWorker...")
        self._proxy = ProxyWorker()
        print("    [4j] ProxyWorker OK")
        self._proxy.proxy_cambiado.connect(self._on_proxy_cambiado)
        self._proxy.proxy_caido.connect(self._on_proxy_caido)
        self._proxy.log_msg.connect(lambda m: self.statusBar().showMessage(m, 4000))
        print("    [4k] señales proxy conectadas")
 
        self._antispam = False
        self.interceptor_spam = AntiSpamInterceptor(self)
        QWebEngineProfile.defaultProfile().setUrlRequestInterceptor(self.interceptor_spam)
 
        # UI Controles
        print("    [4l] QPushButton atras...")
        self.btn_atras    = QPushButton("⬅️")
        self.btn_atras.setToolTip("Atrás")
        print("    [4l2] adelante...")
        self.btn_adelante = QPushButton("➡️")
        self.btn_adelante.setToolTip("Adelante")
        print("    [4l3] recargar...")
        self.btn_recargar = QPushButton("🔄")
        self.btn_recargar.setToolTip("Recargar página")
        print("    [4l4] inicio...")
        self.btn_inicio   = QPushButton("🏠")
        self.btn_inicio.setToolTip("Ir a Google")
        print("    [4l5] QLineEdit...")
        self.barra_url    = QLineEdit()
        self.barra_url.setPlaceholderText("Escribe una URL o busca...")
        print("    [4l6] fav...")
        self.btn_fav        = QPushButton("⭐")
        self.btn_fav.setToolTip("Agregar / quitar favorito")
        self.btn_marcadores = QPushButton("📌")
        self.btn_marcadores.setToolTip("Ver mis favoritos")
        self.btn_dl         = QPushButton("⬇️")
        self.btn_dl.setToolTip("Ver descargas")
        self.btn_incognito  = QPushButton("🕵🏼")
        self.btn_incognito.setToolTip("Modo incógnito — sin historial ni cookies")
        self.btn_nueva      = QPushButton("➕")
        self.btn_nueva.setToolTip("Nueva pestaña")
        self.btn_vpn        = QPushButton("🌍")
        self.btn_vpn.setToolTip("VPN — proxy rotativo para enmascarar IP")
        self.btn_config     = QPushButton("⚙️")
        self.btn_config.setToolTip("Configuración")
        print("    [4l7] todos los botones creados")
        self.btn_antispam = QPushButton("🛡️")
        self.btn_antispam.setToolTip("Anti-spam / Bloqueador de rastreadores")
        # setMaximumWidth diferido al evento loop para evitar bloqueo en Windows
 
        # ─────────────────────────────────────────────────────────────
        # ENLACE DE SEÑALES CORREGIDO Y LIMPIO (SIN SYNTAX ERROR)
        # ─────────────────────────────────────────────────────────────
        
        print("[417] todos los botones creados")
        
        # Conexiones que ya viste que sí jalan perfectamente:
        self.btn_atras.clicked.connect(self._ir_atras)
        self.btn_adelante.clicked.connect(self._ir_adelante)
        self.btn_recargar.clicked.connect(self._recargar)
        self.btn_inicio.clicked.connect(lambda: self._navegar("https://www.google.com"))
        self.barra_url.returnPressed.connect(self._procesar_barra_url)
        self.btn_fav.clicked.connect(self._toggle_favorito)
        self.btn_marcadores.clicked.connect(self._mostrar_menu_favoritos)
        self.btn_dl.clicked.connect(self._ver_descargas)
        self.btn_incognito.clicked.connect(self._toggle_incognito)
        self.btn_nueva.clicked.connect(lambda: self._nueva_tab())
        self.btn_vpn.clicked.connect(self._toggle_vpn)
        self.btn_antispam.clicked.connect(self._toggle_antispam)
 
        # Enlazamos a la nueva función de prueba limpia para que no truene al iniciar
        self.btn_config.clicked.connect(self._abrir_config_seguro)
 
        print("[4l8] Saliendo del bloque de conexiones con éxito")
 
        print("[4l7-B] Todas las señales se procesaron.")
 
        print("    [4m] creando QTabWidget...")
        self.tabs = QTabWidget()
        print("    [4m2] QTabWidget OK")
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self._cerrar_tab)
        self.tabs.currentChanged.connect(self._on_tab_cambiada)
        print("    [4n] Tabs OK")
 
        barra = QHBoxLayout(); barra.setSpacing(4)
        barra.addWidget(self.btn_atras)
        barra.addWidget(self.btn_adelante)
        barra.addWidget(self.btn_recargar)
        barra.addWidget(self.btn_inicio)
        barra.addWidget(self.barra_url, stretch=1)
        barra.addWidget(self.btn_fav)
        barra.addWidget(self.btn_marcadores)
        barra.addWidget(self.btn_dl)
        barra.addWidget(self.btn_incognito)
        barra.addWidget(self.btn_nueva)
        barra.addWidget(self.btn_vpn)
        barra.addWidget(self.btn_config)
        barra.addWidget(self.btn_antispam)
 
        lay = QVBoxLayout(); lay.setContentsMargins(6,6,6,4); lay.setSpacing(4)
        lay.addLayout(barra)
        lay.addWidget(self.tabs)
 
        cnt = QWidget(); cnt.setLayout(lay)
        self.setCentralWidget(cnt)
 
        print("    [4o] Layout OK, aplicando tema...")
        self._aplicar_estilo_tema(self.config_db.get("tema", "Oscuro Premium"))
        print("    [4p] Tema OK")
 
        # Diferir TODO lo que toca WebEngine al evento loop — evita bloqueo en Windows
        QTimer.singleShot(200, self._iniciar_motor)
        print("    [4z] __init__ completado OK")
        
        
        
    def _iniciar_motor(self):
       # ─────────────────────────────────────────────────────────────
        # CONTROL DE ANCHOS CON DETECTOR DE ERRORES
        # ─────────────────────────────────────────────────────────────
        print("[4l8] Iniciando setMaximumWidth...")
        
        botones_lista = [
            ("atras", self.btn_atras), 
            ("adelante", self.btn_adelante), 
            ("recargar", self.btn_recargar), 
            ("inicio", self.btn_inicio), 
            ("fav", self.btn_fav), 
            ("marcadores", self.btn_marcadores), 
            ("dl", self.btn_dl), 
            ("incognito", self.btn_incognito), 
            ("nueva", self.btn_nueva), 
            ("config", self.btn_config),
            ("antispam", self.btn_antispam)
        ]
 
        for nombre, boton in botones_lista:
            try:
                # Si el botón no se ha creado o es un string/None, esto va a saltar al except
                boton.setFixedWidth(32)
                print(f"   -> Botón [{nombre}] configurado OK")
            except Exception as err_boton:
                print(f"❌ ¡EL ERROR ESTÁ AQUÍ! El botón [{nombre}] rompió el programa. Detalles: {err_boton}")
 
        print("[4l9] Todos los anchos procesados correctamente")
        self.btn_vpn.setFixedWidth(70)
 
        # Crear perfil persistente con nombre — defaultProfile ignora setPersistentStoragePath
        self._perfil_persistente = QWebEngineProfile("NavegaLibre")
        self._perfil_persistente.setPersistentStoragePath(PERFIL_DATOS_DIR)
        self._perfil_persistente.setCachePath(os.path.join(PERFIL_DATOS_DIR, "Cache"))
        self._perfil_persistente.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        self._perfil_persistente.downloadRequested.connect(self._gestionar_descarga_segura)
        self._configurar_perfil_antidetect(self._perfil_persistente, privado=False)
 
        self._nueva_tab("https://www.google.com", "Inicio")
 
 
    def _aplicar_estilo_tema(self, nombre_tema):
        estilo = TEMAS.get(nombre_tema, TEMAS["Oscuro Premium"])
        self.setStyleSheet(estilo)
 
    def _configurar_perfil_antidetect(self, perfil, privado=False):
        perfil.setHttpUserAgent(USER_AGENT)
        idioma = self.config_db.get("idioma", "es-MX")
        perfil.setHttpAcceptLanguage(f"{idioma},{idioma.split('-')[0]};q=0.9")
        
        if not privado:
            perfil.setPersistentStoragePath(PERFIL_DATOS_DIR)
            perfil.setCachePath(os.path.join(PERFIL_DATOS_DIR, "Cache"))
            perfil.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)
        else:
            perfil.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
        
        settings = perfil.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, self.config_db.get("javascript", True))
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        
        perfil.scripts().clear()
        script = QWebEngineScript()
        script.setName("BypassStealth")
        script.setSourceCode(SCRIPT_STEALTH)
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(True)
        perfil.scripts().insert(script)
 
    def _nueva_tab(self, url="https://www.google.com", titulo="Nueva pestaña"):
        from PyQt6.QtCore import QUrl, QTimer, Qt
        from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings, QWebEngineScript
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        from PyQt6.QtWebChannel import QWebChannel
        import os
        import time
        from datetime import datetime

        browser = QWebEngineView()
 
        # 1. PERFIL
        # Incógnito: cookies EN MEMORIA (funciona igual que normal pero no persiste al cerrar)
        # Normal:    cookies en disco (sesiones sobreviven al cerrar el navegador)
        if self._incognito:
            # Nombre único por pestaña — cookies en memoria, no en disco
            perfil = QWebEngineProfile(f"incognito_{int(time.time())}", self)
            perfil.setPersistentCookiesPolicy(
                QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
            perfil.setHttpUserAgent(USER_AGENT)
            perfil.setUrlRequestInterceptor(self.interceptor_spam)
            perfil.downloadRequested.connect(self._gestionar_descarga_segura)
            # Script stealth también en incógnito
            sc = QWebEngineScript()
            sc.setName("BypassStealth")
            sc.setSourceCode(SCRIPT_STEALTH)
            sc.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
            sc.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            sc.setRunsOnSubFrames(True)
            perfil.scripts().insert(sc)
        else:
            perfil = getattr(self, '_perfil_persistente', QWebEngineProfile.defaultProfile())
 
        # 2. SETTINGS — aplicar al perfil (afecta todas las páginas incluyendo PDF)
        cfg = perfil.settings()
        cfg.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled,             True)
        cfg.setAttribute(QWebEngineSettings.WebAttribute.PdfViewerEnabled,           True)
        cfg.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled,          True)
        cfg.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled,        True)
        cfg.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        cfg.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, True)
        cfg.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        cfg.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled,               True)
 
        # 3. Crear página con el perfil
        browser.setPage(PaginaPersonalizada(perfil, self))
 
        # 4. WebChannel para editor PDF — DESPUÉS de setPage
        bridge = PdfBridge(self)
        canal  = QWebChannel(browser.page())
        canal.registerObject("pdfBridge", bridge)
        browser.page().setWebChannel(canal)
        browser._pdf_bridge = bridge
        browser._pdf_canal  = canal
 
        # 5. printRequested → nuestro modal (nunca el de Chromium)
        browser.page().printRequested.connect(
            lambda b=browser: self._manejar_ctrl_p(b))
 
        # 6. Menú contextual personalizado
        browser.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        browser.customContextMenuRequested.connect(
            lambda pos, b=browser: self._menu_contextual(pos, b))
    
        browser.urlChanged.connect(lambda qurl: self._on_url_cambiada(browser, qurl))
        browser.titleChanged.connect(lambda t: self._on_titulo_cambiado(browser, t))
 
        idx = self.tabs.addTab(browser, titulo)
        self.tabs.setCurrentIndex(idx)
 
        # 7. Cargar URL — UNA SOLA VEZ y correción de exportación en pyinstaller

        url_normalizada = os.path.normpath(url)

        if url.startswith("file://"):
            browser.setUrl(QUrl(url))
        elif url.endswith(".html") and (os.path.isabs(url_normalizada) or "_MEIPASS" in url or "Temp" in url):
            browser.setUrl(QUrl.fromLocalFile(url_normalizada))
        else:
            QTimer.singleShot(50, lambda: browser.setUrl(QUrl(url)))
 
 
    def _on_url_cambiada(self, browser, qurl):
        url_str = qurl.toString()
        if not url_str or url_str.startswith("about:") or "configuracion" in url_str: return
 
        if self.tabs.currentWidget() == browser:
            self.barra_url.setText(url_str)
            self.btn_fav.setText("★" if any(f["url"] == url_str for f in self.favoritos) else "☆")
        
        if not self._incognito:
            fecha_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            titulo_temp = browser.title() if browser.title().strip() else url_str
            item_historial = {"titulo": titulo_temp, "url": url_str, "fecha": fecha_hora}
            
            if not self.historial_web or self.historial_web[0]["url"] != url_str:
                self.historial_web.insert(0, item_historial)  
                _guardar(HISTORIAL_PATH, self.historial_web)
 
    def _on_titulo_cambiado(self, browser, titulo):
        idx = self.tabs.indexOf(browser)
        if idx != -1:
            self.tabs.setTabText(idx, (titulo[:12] + "..") if len(titulo) > 12 else titulo)
            url_actual = browser.url().toString()
            for item in self.historial_web[:5]:
                if item["url"] == url_actual:
                    item["titulo"] = titulo
                    _guardar(HISTORIAL_PATH, self.historial_web)
                    break
 
    def _on_tab_cambiada(self, idx):
        widget = self.tabs.widget(idx)
        if widget and isinstance(widget, QWebEngineView):
            self.barra_url.setText(widget.url().toString())
            self.barra_url.setEnabled(True)
        else:
            self.barra_url.setText("navegalibre://configuracion")
            self.barra_url.setEnabled(False)
 
    def _browser_actual(self):
        w = self.tabs.currentWidget()
        return w if isinstance(w, QWebEngineView) else None
 
    def _abrir_config_seguro(self):
 
                    
        print("⚙️ Diste clic en Configuración. Intentando renderizar el panel...")
        try:
            # 1. Verificar si la pestaña ya existe para no duplicarla
            for i in range(self.tabs.count()):
                if self.tabs.tabText(i) == "⚙️ Configuración":
                    self.tabs.setCurrentIndex(i)
                    return
 
            # 2. Crear contenedor base
            panel_config = QWidget()
            v_lay = QVBoxLayout(panel_config)
            v_lay.setSpacing(12)
            v_lay.setContentsMargins(30, 20, 30, 20)
            
            titulo = QLabel("<h2>Configuración del Sistema</h2>")
            v_lay.addWidget(titulo)
            
            # ─────────────────────────────────────────────────────────────
            # 3. Combo de Temas y Carga de Imagen Personalizada
            # ─────────────────────────────────────────────────────────────
            h_lay1 = QHBoxLayout()
            h_lay1.addWidget(QLabel("Tema Visual:"))
            combo_tema = QComboBox()
            
            temas_disponibles = ["Oscuro Premium", "Claro Clásico", "La Noche Estrellada", "El Grito", "La Persistencia de la Memoria", "Pink Premium", "Orange Premium"]
            combo_tema.addItems(temas_disponibles)
            
            if hasattr(self, 'config_db'):
                combo_tema.setCurrentText(self.config_db.get("tema", "Oscuro Premium"))
            h_lay1.addWidget(combo_tema)
            v_lay.addLayout(h_lay1)
 
            # Función local perfectamente alineada para procesar la imagen
            def _procesar_imagen_local():
                print("🎨 Selector de imágenes abierto...")
                ruta, _ = QFileDialog.getOpenFileName(self, "Seleccionar Pintura o Imagen", "", "Imágenes (*.png *.jpg *.jpeg)")
                if ruta:
                    try:
                        from PIL import Image
                        img = Image.open(ruta).resize((15, 15), Image.Resampling.LANCZOS).convert("RGB")
                        
                        color_centro = img.getpixel((7, 7))
                        color_esquina = img.getpixel((2, 2))
                        
                        paleta = {
                            "fondo": "#{:02x}{:02x}{:02x}".format(max(15, color_centro[0]-30), max(15, color_centro[1]-30), max(15, color_centro[2]-30)),
                            "barra": "#{:02x}{:02x}{:02x}".format(color_centro[0], color_centro[1], color_centro[2]),
                            "botones": "#{:02x}{:02x}{:02x}".format(color_esquina[0], color_esquina[1], color_esquina[2]),
                            "texto": "#ffffff"
                        }
                        
                        self.config_db["tema_dinamico"] = paleta
                        self.config_db["tema"] = "Personalizado por Imagen"
                        _guardar(CONFIG_PATH, self.config_db)
                        
                        # Generamos y aplicamos el estilo dinámico al instante
                        css = f"""
                            QMainWindow, QWidget {{ background: {paleta['fondo']}; color: {paleta['texto']}; }}
                            QTabWidget::pane {{ border: none; background: {paleta['fondo']}; }}
                            QTabBar::tab {{ background: {paleta['barra']}; color: {paleta['texto']}; padding: 6px 14px; border-radius: 4px 4px 0 0; margin-right: 2px; }}
                            QTabBar::tab:selected {{ background: {paleta['fondo']}; border-bottom: 2px solid {paleta['botones']}; font-weight: bold; }}
                            QLineEdit {{ background: {paleta['barra']}; border: 1px solid {paleta['botones']}; border-radius: 14px; padding: 4px 12px; color: {paleta['texto']}; }}
                            QPushButton {{ background: {paleta['barra']}; border: 1px solid {paleta['botones']}; border-radius: 4px; padding: 6px; color: {paleta['texto']}; }}
                            QPushButton:hover {{ background: {paleta['botones']}; color: #000000; }}
                        """
                        self.setStyleSheet(css)
                        print("🎨 Tema generado y aplicado en vivo.")
                    except Exception as e_pil:
                        print(f"❌ Error al procesar imagen (Asegúrate de ejecutar: pip install Pillow). Error: {e_pil}")
 
            # BOTÓN NUEVO: Apunta directamente a la función local limpia sin usar 'self.'
            btn_subir_imagen_tema = QPushButton("🎨 Cargar Imagen / Pintura como Tema")
            btn_subir_imagen_tema.setStyleSheet("background: #35363a; border: 1px dashed #8ab4f8; padding: 5px; font-weight: bold; color: #8ab4f8;")
            btn_subir_imagen_tema.clicked.connect(_procesar_imagen_local)
            v_lay.addWidget(btn_subir_imagen_tema)
 
 
            # 4. Combo de Idioma
            h_lay2 = QHBoxLayout()
            h_lay2.addWidget(QLabel("Idioma regional (Anti-Detección):"))
            combo_lang = QComboBox()
            combo_lang.addItems(["es-MX", "es-ES", "en-US", "fr-FR"])
            if hasattr(self, 'config_db'):
                combo_lang.setCurrentText(self.config_db.get("idioma", "es-MX"))
            h_lay2.addWidget(combo_lang)
            v_lay.addLayout(h_lay2)
 
            # 5. Checkbox de JS
            chk_js = QCheckBox("Habilitar motor Javascript nativo")
            if hasattr(self, 'config_db'):
                chk_js.setChecked(self.config_db.get("javascript", True))
            v_lay.addWidget(chk_js)
 
            # 6. Historial de Navegación
            v_lay.addWidget(QLabel("<h3>📜 Historial de Navegación</h3>"))
 
            # Cada fila: [fecha] titulo — url  +  botón ✕
            # Clic en la fila → abre la URL directamente
            contenedor_hist = QWidget()
            scroll_hist = QScrollArea()
            scroll_hist.setWidgetResizable(True)
            scroll_hist.setMinimumHeight(200)
            inner = QWidget()
            inner_lay = QVBoxLayout(inner)
            inner_lay.setSpacing(2)
            inner_lay.setContentsMargins(0, 0, 0, 0)
            inner_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
            scroll_hist.setWidget(inner)
            v_lay.addWidget(scroll_hist)
 
            def _poblar():
                # Limpiar filas anteriores
                while inner_lay.count():
                    it = inner_lay.takeAt(0)
                    if it.widget(): it.widget().deleteLater()
 
                historial = getattr(self, "historial_web", [])
                if not historial:
                    lbl = QLabel("Sin historial.")
                    lbl.setStyleSheet("color:#9aa0a6; padding:8px;")
                    inner_lay.addWidget(lbl)
                    return
 
                for i, h in enumerate(historial):
                    if not isinstance(h, dict): continue
                    url   = h.get("url", "")
                    fecha = h.get("fecha", "")
                    titulo = (h.get("titulo") or url)[:70]
                    txt   = f"[{fecha}]  {titulo}"
 
                    fila      = QWidget()
                    fila_lay  = QHBoxLayout(fila)
                    fila_lay.setContentsMargins(4, 2, 4, 2)
                    fila_lay.setSpacing(6)
 
                    # Botón con el texto — clic abre la URL
                    btn_url = QPushButton(txt)
                    btn_url.setFlat(True)
                    btn_url.setStyleSheet(
                        "text-align:left; padding:3px 6px; color:#8ab4f8;"
                        "font-size:12px; border:none;")
                    btn_url.setToolTip(url)
                    btn_url.setCursor(Qt.CursorShape.PointingHandCursor)
                    btn_url.clicked.connect(lambda _, u=url: self._navegar(u))
 
                    # Botón ✕ para eliminar solo esa entrada
                    btn_x = QPushButton("✕")
                    btn_x.setMaximumWidth(24)
                    btn_x.setFlat(True)
                    btn_x.setStyleSheet("color:#ef5350; font-size:12px;")
                    btn_x.setToolTip("Eliminar esta entrada")
                    btn_x.clicked.connect(lambda _, idx=i: _eliminar(idx))
 
                    fila_lay.addWidget(btn_url, stretch=1)
                    fila_lay.addWidget(btn_x)
                    inner_lay.addWidget(fila)
 
            def _eliminar(idx):
                if 0 <= idx < len(self.historial_web):
                    self.historial_web.pop(idx)
                    _guardar(HISTORIAL_PATH, self.historial_web)
                    _poblar()
 
            _poblar()
 
            # Solo el botón de limpiar todo al fondo
            btn_clear_h = QPushButton("🧹 Limpiar todo el historial")
            btn_clear_h.setStyleSheet("margin-top:4px;")
            def _clear_h():
                self.historial_web.clear()
                _guardar(HISTORIAL_PATH, self.historial_web)
                _poblar()
                try:
                    p = getattr(self, "_perfil_persistente", None)
                    if p: p.clearAllVisitedLinks()
                except Exception: pass
                self.statusBar().showMessage("Historial limpiado.", 3000)
            btn_clear_h.clicked.connect(_clear_h)
            v_lay.addWidget(btn_clear_h)
 
            # ── Sección: Cookies, Caché y Contraseñas ─────────────────
            v_lay.addWidget(QLabel("<h3>🍪 Cookies, Caché y Datos</h3>"))
            fila_data_btns = QHBoxLayout()
 
            btn_del_cookies = QPushButton("🍪 Borrar cookies")
            def _del_cookies():
                try:
                    p = getattr(self, "_perfil_persistente",
                                QWebEngineProfile.defaultProfile())
                    p.cookieStore().deleteAllCookies()
                    self.statusBar().showMessage("Cookies eliminadas.", 3000)
                except Exception as e:
                    self.statusBar().showMessage(f"Error: {e}", 4000)
            btn_del_cookies.clicked.connect(_del_cookies)
 
            btn_del_cache = QPushButton("🗄 Borrar caché")
            def _del_cache():
                try:
                    p = getattr(self, "_perfil_persistente",
                                QWebEngineProfile.defaultProfile())
                    p.clearHttpCache()
                    self.statusBar().showMessage("Caché eliminada.", 3000)
                except Exception as e:
                    self.statusBar().showMessage(f"Error: {e}", 4000)
            btn_del_cache.clicked.connect(_del_cache)
 
            btn_del_todo = QPushButton("⚠️ Borrar todo")
            btn_del_todo.setStyleSheet("background:#c62828;color:white;font-weight:bold;")
            btn_del_todo.setToolTip("Borra historial, cookies, caché y contraseñas guardadas")
            def _del_todo():
                from PyQt6.QtWidgets import QMessageBox
                resp = QMessageBox.question(
                    self, "Confirmar",
                    "¿Borrar historial, cookies, caché y contraseñas? Esto cerrará todas las sesiones activas.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if resp != QMessageBox.StandardButton.Yes: return
                # Historial
                self.historial_web.clear()
                _guardar(HISTORIAL_PATH, self.historial_web)
                _poblar()
                # Perfil WebEngine
                try:
                    p = getattr(self, "_perfil_persistente",
                                QWebEngineProfile.defaultProfile())
                    p.cookieStore().deleteAllCookies()
                    p.clearHttpCache()
                    p.clearAllVisitedLinks()
                except Exception: pass
                # Contraseñas (JSON local)
                passwords_path = os.path.join(BASE_DIR, "passwords.json")
                if os.path.exists(passwords_path):
                    _guardar(passwords_path, {})
                self.statusBar().showMessage(
                    "✅ Historial, cookies, caché y contraseñas borrados.", 5000)
            btn_del_todo.clicked.connect(_del_todo)
 
            for b in [btn_del_cookies, btn_del_cache, btn_del_todo]:
                fila_data_btns.addWidget(b)
            v_lay.addLayout(fila_data_btns)
 
             # ─────────────────────────────────────────────────────────────
            # SECCIÓN DE ADDONS / EXTENSIONES (ÚLTIMO PASO)
            # ─────────────────────────────────────────────────────────────
            v_lay.addWidget(QLabel("<h3>🧩 Extensiones / Addons de Chromium</h3>"))
            
            # Lista para mostrar las extensiones que ya están cargadas
            lista_addons_widget = QListWidget()
            lista_addons_widget.setFixedHeight(100)
            
            # Rellenar la lista con los nombres de las carpetas guardadas
            addons_guardados = self.config_db.get("addons_rutas", [])
            for ruta in addons_guardados:
                lista_addons_widget.addItem(QListWidgetItem(os.path.basename(ruta)))
            v_lay.addWidget(lista_addons_widget)
            
            # Botones para Administrar los Addons
            h_botones_addons = QHBoxLayout()
            btn_cargar_addon = QPushButton("➕ Agregar Extensión (.destilada / carpeta)")
            btn_cargar_addon.setStyleSheet("background: #1a73e8; color: white; font-weight: bold;")
            btn_eliminar_addon = QPushButton("🗑️ Quitar Seleccionada")
            
            h_botones_addons.addWidget(btn_cargar_addon)
            h_botones_addons.addWidget(btn_eliminar_addon)
            v_lay.addLayout(h_botones_addons)
            
 
            # FUNCIÓN LOCAL INTERNA: Para evitar el fallo de AttributeError con self
 
            def _agregar_addon_local():
                print("🧩 Abriendo selector de carpetas para Addon...")
                ruta_carpeta = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de la extensión (Descomprimida)")
                
                if ruta_carpeta:
                    rutas_actuales = self.config_db.get("addons_rutas", [])
                    if ruta_carpeta in rutas_actuales:
                        print("⚠️ Esta extensión ya fue agregada anteriormente.")
                        return
                        
                    rutas_actuales.append(ruta_carpeta)
                    self.config_db["addons_rutas"] = rutas_actuales
                    _guardar(CONFIG_PATH, self.config_db)
                    
                    lista_addons_widget.addItem(QListWidgetItem(os.path.basename(ruta_carpeta)))
                    print(f"✅ Addon registrado con éxito en: {ruta_carpeta}")
                    print("💡 Reinicia el navegador para que Chromium cargue la extensión.")
            
            def _eliminar_addon_seleccionado():
                fila = lista_addons_widget.currentRow()
                if fila >= 0:
                    rutas = self.config_db.get("addons_rutas", [])
                    print(f"🗑️ Eliminando addon: {rutas[fila]}")
                    rutas.pop(fila)
                    self.config_db["addons_rutas"] = rutas
                    _guardar(CONFIG_PATH, self.config_db)
                    lista_addons_widget.takeItem(fila)
                    print("⚠️ Addon removido. Aplica los cambios al reiniciar.")
            
            # Conexiones limpias a las funciones locales (Sin usar self._metodo)
            btn_cargar_addon.clicked.connect(_agregar_addon_local)        
            btn_eliminar_addon.clicked.connect(_eliminar_addon_seleccionado)
            # ─────────────────────────────────────────────────────────────
 
            # 7. Botón de Guardar Cambios
            btn_guardar_ajustes = QPushButton("💾 Guardar y Aplicar Ajustes")
            btn_guardar_ajustes.setStyleSheet("background: #2e7d32; font-weight: bold; padding: 6px; color: white;")
            
 
 
            def _guardar_cambios_interno():
                try:
                    self.config_db["tema"] = combo_tema.currentText()
                    self.config_db["idioma"] = combo_lang.currentText()
                    self.config_db["javascript"] = chk_js.isChecked()
                    # Usamos la función global _guardar que ya tienes arriba
                    _guardar(CONFIG_PATH, self.config_db)
                    self._aplicar_estilo_tema(self.config_db["tema"])
                    print("💾 Ajustes guardados correctamente.")
                except Exception as e_guardar:
                    print(f"❌ Error al guardar configuraciones: {e_guardar}")
 
            btn_guardar_ajustes.clicked.connect(_guardar_cambios_interno)
            v_lay.addWidget(btn_guardar_ajustes)
 
            # 8. Añadir la pestaña formalmente al TabWidget
            idx = self.tabs.addTab(panel_config, "⚙️ Configuración")
            self.tabs.setCurrentIndex(idx)
            print("✅ Panel de configuración abierto con éxito.")
 
        except Exception as err_panel:
            print(f"❌ ERROR CRÍTICO al construir la interfaz de configuración: {err_panel}")
 
    
                
            def _seleccionar_y_agregar_addon(self, lista_widget_addons):
                print("🧩 Abriendo selector de carpetas para Addon...")
        # Abrir el explorador de archivos para seleccionar la carpeta de la extensión
                ruta_carpeta = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de la extensión (Descomprimida)")
        
                if ruta_carpeta:
            # Verificar si ya está agregada para no duplicar
                    rutas_actuales = self.config_db.get("addons_rutas", [])
                    if ruta_carpeta in rutas_actuales:
                        print("⚠️ Esta extensión ya fue agregada anteriormente.")
                        return
                
            # Guardar la nueva ruta en la base de datos local
                rutas_actuales.append(ruta_carpeta)
                self.config_db["addons_rutas"] = rutas_actuales
                _guardar(CONFIG_PATH, self.config_db)
            
            # Reflejar el cambio visualmente en la lista del panel
                lista_widget_addons.addItem(QListWidgetItem(os.path.basename(ruta_carpeta)))
                print(f"✅ Addon registrado con éxito en: {ruta_carpeta}")
                print("💡 Nota: Reinicia el navegador para que Chromium cargue la extensión por seguridad.")
 
    def verificar_navegacion_pdf(self, url):
        """Si la URL es un PDF, lo abre en una nueva pestaña dedicada."""
        url_string = url.toString()
        if url_string.lower().endswith(".pdf"):
            # Detener la carga en la pestaña actual
            pestaña_actual = self.tabs.currentWidget()
            if pestaña_actual and isinstance(pestaña_actual, QWebEngineView):
                pestaña_actual.stop()
            # Abrir en pestaña nueva — la misma que ya funciona
            self._nueva_tab(url_string, "📄 PDF")
 
    def _procesar_barra_url(self):
        entrada = self.barra_url.text().strip()
        if not entrada or entrada.startswith("navegalibre://"): return
        if "," in entrada and " " not in entrada: entrada = entrada.replace(",", ".")
        url_destino = "https://www.google.com/search?q=" + urllib.parse.quote_plus(entrada) if " " in entrada or "." not in entrada else (entrada if entrada.startswith(("http://", "https://")) else "https://" + entrada)
        self._navegar(url_destino)
 
    def _navegar(self, url):
        b = self._browser_actual(); b.setUrl(QUrl(url)) if b else None
 
    def _ir_atras(self):
        b = self._browser_actual(); b.back() if b else None
 
    def _ir_adelante(self):
        b = self._browser_actual(); b.forward() if b else None
 
    def _recargar(self):
        b = self._browser_actual(); b.reload() if b else None
 
    def _cerrar_tab(self, idx):
        if self.tabs.count() > 1:
            w = self.tabs.widget(idx)
            ruta_borrar = None

            if w and isinstance(w, QWebEngineView):
                try:
                    perfil = w.page().profile()
                    nombre = perfil.storageName()
                    if nombre and nombre.startswith("incognito_"):
                        perfil.clearAllVisitedLinks()
                        perfil.clearHttpCache()
                        storage = perfil.persistentStoragePath()
                        if storage and os.path.exists(storage):
                            ruta_borrar = storage
                except Exception:
                    pass
                w.deleteLater()

            self.tabs.removeTab(idx)

            # Borrar el directorio DESPUÉS de que Qt libere los handles
            # 1500ms es suficiente para que Windows cierre los archivos del perfil
            if ruta_borrar:
                QTimer.singleShot(1500, lambda r=ruta_borrar: self._borrar_dir(r))
        else:
            self.close()

    def _borrar_dir(self, ruta):
        import shutil
        try:
            if os.path.exists(ruta):
                shutil.rmtree(ruta, ignore_errors=False)
        except Exception:
            # Si Windows todavía tiene el dir bloqueado, reintentar una vez más
            QTimer.singleShot(2000, lambda r=ruta: (
                __import__('shutil').rmtree(r, ignore_errors=True)
                if os.path.exists(r) else None
            ))
 
    def _menu_contextual(self, pos, browser):
        """Menú contextual personalizado."""
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction
 
        from PyQt6.QtWebEngineCore import QWebEnginePage
        import urllib.parse
 
        # 1. Obtener la información de qué hay exactamente debajo del cursor
        datos_clic = browser.lastContextMenuRequest()
        es_enlace = datos_clic.linkUrl().isValid()
 
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background:#2d2d2d; color:#e8eaed; border:1px solid #5f6368; }
            QMenu::item:selected { background:#3c4043; }
            QMenu::separator { background:#5f6368; height:1px; }
        """)
 
        # Navegación
        a_atras = QAction("Atrás", self)
        a_atras.setEnabled(browser.history().canGoBack())
        a_atras.triggered.connect(browser.back)
        menu.addAction(a_atras)
 
        a_adelante = QAction("Adelante", self)
        a_adelante.setEnabled(browser.history().canGoForward())
        a_adelante.triggered.connect(browser.forward)
        menu.addAction(a_adelante)
 
        a_recargar = QAction("Recargar", self)
        a_recargar.triggered.connect(browser.reload)
        menu.addAction(a_recargar)
 
        menu.addSeparator()
 
        # Edición
        a_copiar = QAction("Copiar", self)
        a_copiar.triggered.connect(lambda: browser.page().triggerAction(
            QWebEnginePage.WebAction.Copy))
        menu.addAction(a_copiar)
 
        a_pegar = QAction("Pegar", self)
        a_pegar.triggered.connect(lambda: browser.page().triggerAction(
            QWebEnginePage.WebAction.Paste))
        menu.addAction(a_pegar)
 
        a_selec = QAction("Seleccionar todo", self)
        a_selec.triggered.connect(lambda: browser.page().triggerAction(
            QWebEnginePage.WebAction.SelectAll))
        menu.addAction(a_selec)
 
        menu.addSeparator()
 
        # Página
        a_imprimir = QAction("Imprimir", self)
        a_imprimir.triggered.connect(lambda: self._manejar_ctrl_p(browser))
        menu.addAction(a_imprimir)
 
        a_guardar = QAction("Descargar página", self)
        a_guardar.triggered.connect(lambda: browser.page().triggerAction(
            QWebEnginePage.WebAction.SavePage))
        menu.addAction(a_guardar)
 
        a_fuente = QAction("Ver código fuente", self)
        a_fuente.triggered.connect(lambda: self._nueva_tab(
            "view-source:" + browser.url().toString(), "Fuente"))
        menu.addAction(a_fuente)
 
        a_inspect = QAction("Inspeccionar", self)
        a_inspect.triggered.connect(lambda: self._abrir_devtools(browser))
        menu.addAction(a_inspect)
 
        menu.addSeparator()
 
        # Buscar texto seleccionado en Google
        texto_sel = datos_clic.selectedText().strip() if datos_clic else ""
        if texto_sel:
            a_buscar_sel = QAction(f'🔍 Buscar "{texto_sel[:30]}" en Google', self)
            url_buscar = f"https://www.google.com/search?q={urllib.parse.quote(texto_sel)}"
            a_buscar_sel.triggered.connect(lambda: self._nueva_tab(url_buscar, f"Buscar: {texto_sel[:20]}"))
            menu.addAction(a_buscar_sel)

            a_buscar_pag = QAction(f'📄 Buscar en esta página', self)
            a_buscar_pag.triggered.connect(lambda t=texto_sel: browser.page().runJavaScript(
                f"var si=document.getElementById('search-input'); if(si){{si.value={repr(t)};si.dispatchEvent(new Event('input'));}} "
                f"else window.find({repr(t)});"))
            menu.addAction(a_buscar_pag)

            menu.addSeparator()

        # Google Lens
        a_lens = QAction("Buscar con Google Lens", self)
        url_lens = f"https://lens.google.com/uploadbyurl?url={urllib.parse.quote(browser.url().toString())}"
        a_lens.triggered.connect(lambda: self._nueva_tab(url_lens, "Google Lens"))
        menu.addAction(a_lens)
 
        # --- SECCIÓN DINÁMICA DE NUEVA PESTAÑA CON PROTECCIÓN CONTRA CRASHES ---
        from PyQt6.QtCore import QTimer
 
        a_nueva = QAction("Abrir enlace en nueva pestaña", self)
        if es_enlace:
            url_destino = datos_clic.linkUrl().toString()
        else:
            # Si hizo clic en fondo blanco o imágenes sueltas, duplica la URL actual de la pestaña
            url_destino = browser.url().toString()
            a_nueva = QAction("Duplicar pestaña actual", self)
 
        # El QTimer ejecuta _nueva_tab 50ms después, permitiendo que el menú muera en paz
        a_nueva.triggered.connect(
            lambda: QTimer.singleShot(50, lambda: self._nueva_tab(url_destino))
        )
        menu.addAction(a_nueva)
 
        menu.exec(browser.mapToGlobal(pos))
 
    def _abrir_devtools(self, browser):
        if not hasattr(self, '_devtools_wins'):
            self._devtools_wins = {}
        idx = self.tabs.indexOf(browser)
        if idx in self._devtools_wins and self._devtools_wins[idx].isVisible():
            self._devtools_wins[idx].close()
            return
        dev = QWebEngineView()
        browser.page().setDevToolsPage(dev.page())
        dev.setWindowTitle(f"DevTools — {self.tabs.tabText(idx)}")
        dev.resize(1100, 650)
        dev.show()
        self._devtools_wins[idx] = dev
 
    def _manejar_ctrl_p(self, browser):
        """printRequested — editor PDF usa modal JS, resto usa modal Python."""
        url = browser.url().toString()
        if "editor_pdf.html" in url:
            browser.page().runJavaScript("abrirModalImprimir();")
        else:
            self._abrir_modal_imprimir(browser)
 
    def _abrir_modal_imprimir(self, browser):
        """Modal Python de selección de páginas — reemplaza el diálogo nativo."""
        import os
        import tempfile
        from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                      QRadioButton, QSpinBox, QLabel,
                                      QPushButton, QGroupBox, QButtonGroup, QFileDialog)
        
        dlg = QDialog(self)
        dlg.setWindowTitle("🖨️  Imprimir / Guardar PDF")
        dlg.setMinimumWidth(360)
        lay = QVBoxLayout(dlg)
 
        grp = QGroupBox("Acción")
        gl  = QVBoxLayout(grp)
        bg_acc = QButtonGroup(dlg)
        rb_imp  = QRadioButton("🖨️  Imprimir"); rb_imp.setChecked(True)
        rb_pdf  = QRadioButton("💾  Guardar como PDF")
        bg_acc.addButton(rb_imp); bg_acc.addButton(rb_pdf)
        gl.addWidget(rb_imp); gl.addWidget(rb_pdf)
        lay.addWidget(grp)
 
        grp2 = QGroupBox("Páginas")
        gl2  = QVBoxLayout(grp2)
        bg_pag = QButtonGroup(dlg)
        rb_todas  = QRadioButton("Todas las páginas"); rb_todas.setChecked(True)
        rb_actual = QRadioButton("Página actual")
        rb_rango  = QRadioButton("Rango personalizado:")
        bg_pag.addButton(rb_todas); bg_pag.addButton(rb_actual); bg_pag.addButton(rb_rango)
 
        fila_r = QHBoxLayout()
        sp_d = QSpinBox(); sp_d.setMinimum(1); sp_d.setValue(1)
        sp_h = QSpinBox(); sp_h.setMinimum(1); sp_h.setValue(99)
        fila_r.addWidget(QLabel("De:")); fila_r.addWidget(sp_d)
        fila_r.addWidget(QLabel("a:")); fila_r.addWidget(sp_h)
        fila_r.addStretch()
 
        gl2.addWidget(rb_todas); gl2.addWidget(rb_actual)
        gl2.addWidget(rb_rango); gl2.addLayout(fila_r)
        lay.addWidget(grp2)
 
        btns = QHBoxLayout()
        bc = QPushButton("Cancelar"); ba = QPushButton("Continuar ▶")
        bc.clicked.connect(dlg.reject); ba.clicked.connect(dlg.accept)
        btns.addWidget(bc); btns.addWidget(ba)
        lay.addLayout(btns)
 
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
 
        imprimir = rb_imp.isChecked()
        
        # Determinamos el destino final
        if imprimir:
            tmp  = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            ruta = tmp.name; tmp.close()
        else:
            titulo = self.tabs.tabText(self.tabs.currentIndex()).strip() or "pagina"
            for c in r'\/:*?"<>|': titulo = titulo.replace(c, "_")
            downloads = os.path.join(
                os.environ.get("USERPROFILE", os.path.expanduser("~")), "Downloads")
            ruta, _ = QFileDialog.getSaveFileName(
                self, "Guardar PDF",
                os.path.join(downloads, titulo+".pdf"), "PDF (*.pdf)")
            if not ruta:
                return
 
        self.statusBar().showMessage("⏳ Procesando…")
 
        # --- CORRECCIÓN CRÍTICA: El Callback ahora recibe los bytes de PyQt6 ---
        def _cb(pdf_bytes):
            if not pdf_bytes:
                self.statusBar().showMessage("❌ Error al procesar el PDF.", 4000)
                return
            
            try:
                # Escribimos los bytes generados directamente en la ruta asignada
                with open(ruta, "wb") as f:
                    f.write(pdf_bytes)
                
                if imprimir:
                    try:
                        os.startfile(ruta, "print")
                        self.statusBar().showMessage("✅ Enviado a impresora.", 4000)
                    except Exception:
                        os.startfile(ruta)
                        self.statusBar().showMessage("⚠️ Usa Ctrl+P en el visor.", 5000)
                else:
                    self.statusBar().showMessage(
                        f"✅ PDF guardado: {os.path.basename(ruta)}", 5000)
                        
            except Exception as e:
                print(f"Error de escritura: {e}")
                self.statusBar().showMessage("❌ Error al guardar archivo.", 4000)
 
        # Pasamos la función callback como primer parámetro para cumplir con PyQt6
        browser.page().printToPdf(_cb)
 
    def _toggle_favorito(self):
        url = self.barra_url.text().strip()
        if not url or url.startswith("about:") or "configuracion" in url: return
        existente = next((f for f in self.favoritos if f["url"] == url), None)
        if existente: self.favoritos.remove(existente); self.btn_fav.setText("☆")
        else: self.favoritos.append({"titulo": self.tabs.tabText(self.tabs.currentIndex()), "url": url}); self.btn_fav.setText("★")
        _guardar(FAVORITOS_PATH, self.favoritos)
 
    def _mostrar_menu_favoritos(self):
        from PyQt6.QtWidgets import QWidgetAction
        menu = QMenu(self)
        menu.setMinimumWidth(300)
        if not self.favoritos:
            a = menu.addAction("(Sin marcadores)")
            a.setEnabled(False)
        else:
            for fav in list(self.favoritos):
                url    = fav["url"]
                titulo = (fav.get("titulo") or url)[:45]
                fila   = QWidget()
                fl     = QHBoxLayout(fila)
                fl.setContentsMargins(4, 2, 4, 2)
                fl.setSpacing(4)
                btn_ir = QPushButton(titulo)
                btn_ir.setFlat(True)
                btn_ir.setStyleSheet("text-align:left;")
                btn_ir.clicked.connect(lambda _, u=url: (self._navegar(u), menu.close()))
                btn_x  = QPushButton("✕")
                btn_x.setMaximumWidth(24)
                btn_x.setFlat(True)
                btn_x.setStyleSheet("color:#ef5350;")
                btn_x.setToolTip("Eliminar marcador")
                btn_x.clicked.connect(lambda _, u=url: (self._eliminar_favorito(u), menu.close()))
                fl.addWidget(btn_ir, stretch=1)
                fl.addWidget(btn_x)
                wa = QWidgetAction(menu)
                wa.setDefaultWidget(fila)
                menu.addAction(wa)
            menu.addSeparator()
            a2 = menu.addAction("🗑 Eliminar todos los marcadores")
            a2.triggered.connect(lambda: (self._eliminar_todos_favoritos(), menu.close()))
        menu.exec(QCursor.pos())
 
    def _eliminar_favorito(self, url):
        self.favoritos = [f for f in self.favoritos if f["url"] != url]
        _guardar(FAVORITOS_PATH, self.favoritos)
        self.btn_fav.setText("☆")
 
    def _eliminar_todos_favoritos(self):
        self.favoritos.clear()
        _guardar(FAVORITOS_PATH, self.favoritos)
        self.btn_fav.setText("☆")
 
    def _gestionar_descarga_segura(self, item):
        """PDFs -> nueva pestaña, salvo que venga de una pestaña que ya es PDF/visor."""
        url_str = item.url().toString()
 
        if url_str.lower().endswith(".pdf"):
            # Revisar desde qué pestaña se originó la descarga
            pagina_origen = item.page()
            referer = pagina_origen.url().toString() if pagina_origen else ""
 
            # Si ya estamos viendo un PDF o el visor de Google, es descarga explícita
            es_descarga_explicita = (
                referer.lower().endswith(".pdf") or
                "docs.google.com/viewer" in referer or
                "drive.google.com" in referer
            )
 
            if not es_descarga_explicita:
                item.cancel()
                self._nueva_tab(url_str, "📄 PDF")
                return
 
        self._gestionar_descarga(item)
 
    # Mapa de MIME types a extensiones
    _MIME_EXT = {
        "application/pdf": ".pdf",
        "application/zip": ".zip",
        "application/x-rar-compressed": ".rar",
        "application/x-7z-compressed": ".7z",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.ms-excel": ".xls",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "application/vnd.ms-powerpoint": ".ppt",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        "text/plain": ".txt",
        "text/html": ".html",
        "text/csv": ".csv",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "audio/mpeg": ".mp3",
        "audio/ogg": ".ogg",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "application/octet-stream": "",
    }
 
    def _deducir_nombre(self, item):
        """Devuelve un nombre de archivo limpio deducido de la URL y el MIME type."""
        nombre = item.downloadFileName()
 
        # Quitar sufijos falsos que agrega QtWebEngine
        for sufijo in [".download", ".crdownload", ".tmp"]:
            if nombre.lower().endswith(sufijo):
                nombre = nombre[:-len(sufijo)]
 
        # Si el nombre ya tiene extensión válida, usarlo
        _, ext_actual = os.path.splitext(nombre)
        if ext_actual and ext_actual.lower() not in [".download", ".crdownload", ".tmp"]:
            return nombre
 
        # Intentar deducir extensión del MIME type
        mime = item.mimeType() if hasattr(item, "mimeType") else ""
        ext  = self._MIME_EXT.get(mime, "")
 
        # Si no hay MIME, intentar deducir de la URL
        if not ext:
            from urllib.parse import urlparse
            path = urlparse(item.url().toString()).path
            _, ext_url = os.path.splitext(path)
            if ext_url:
                ext = ext_url
 
        return nombre + ext if ext and not nombre.endswith(ext) else nombre or "archivo"
 
    def _gestionar_descarga(self, item):
        nombre_sugerido = self._deducir_nombre(item)
        dir_sugerido    = os.path.join(os.environ.get("USERPROFILE", "C:\\Users\\Default"), "Downloads")
        ruta_sugerida   = os.path.join(dir_sugerido, nombre_sugerido)
 
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar archivo como...", ruta_sugerida)
        if not ruta:
            item.cancel()
            return
 
        item.setDownloadDirectory(os.path.dirname(ruta))
        item.setDownloadFileName(os.path.basename(ruta))
        item.accept()
 
        info = {"nombre": os.path.basename(ruta), "ruta": ruta, "estado": "descargando"}
        self.historial_dl.append(info)
        _guardar(DESCARGAS_PATH, self.historial_dl)
 
        item.isFinishedChanged.connect(lambda: [
            info.update({"estado": "completado"}),
            _guardar(DESCARGAS_PATH, self.historial_dl)
        ])
 
    def filtrar_y_descargar(self, item):
        """Alias de _gestionar_descarga_segura para compatibilidad."""
        self._gestionar_descarga_segura(item)
 
    def _ver_descargas(self):
        from PyQt6.QtWidgets import QScrollArea, QFrame
        dial = QDialog(self)
        dial.setWindowTitle("📥 Panel de Descargas")
        dial.setMinimumWidth(560)
        dial.setMinimumHeight(400)
        vl = QVBoxLayout(dial)
 
        # Área scrollable
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        contenedor = QWidget()
        self._dl_lista_layout = QVBoxLayout(contenedor)
        self._dl_lista_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(contenedor)
        vl.addWidget(scroll)
 
 
 
        def _poblar():
            # Limpiar items anteriores
            while self._dl_lista_layout.count():
                it = self._dl_lista_layout.takeAt(0)
                if it.widget(): it.widget().deleteLater()
            if not self.historial_dl:
                self._dl_lista_layout.addWidget(QLabel("No hay descargas registradas."))
                return
            for d in reversed(self.historial_dl):
                fila = QFrame(); fila.setFrameShape(QFrame.Shape.StyledPanel)
                fl   = QHBoxLayout(fila); fl.setContentsMargins(6,4,6,4)
                estado = d.get("estado","?")
                ico    = "✅" if estado=="completado" else "⏳" if estado=="descargando" else "❌"
                lbl    = QLabel(f"{ico}  {d.get('nombre','?')}")
                lbl.setToolTip(d.get("ruta",""))
                fl.addWidget(lbl, stretch=1)
                ruta = d.get("ruta","")
                if estado == "completado" and ruta and os.path.exists(ruta):
                    btn_abrir = QPushButton("📂")
                    btn_abrir.setMaximumWidth(32)
                    btn_abrir.setToolTip("Mostrar en carpeta")
                    
                    # FUNCIÓN CORREGIDA: Abre el Explorador de Windows y selecciona el archivo ejecutable
                    def _mostrar_en_explorador(_, r=ruta):
                        import subprocess
                        # Convertimos las barras / a \ por compatibilidad estricta con Windows
                        ruta_fija = os.path.normpath(r)
                        subprocess.Popen(f'explorer /select,"{ruta_fija}"')
                    
 
                    # REEMPLAZADO CON SINTAXIS SEGURA DE PYTHON (os.startfile)
                    # Usamos una función anónima limpia para evitar que se cuelgue el hilo de Qt
                    btn_abrir.clicked.connect(_mostrar_en_explorador)
                    
                    fl.addWidget(btn_abrir)
                self._dl_lista_layout.addWidget(fila)
 
        _poblar()
 
        # Botones inferiores
        fila_btns = QHBoxLayout()
        btn_actualizar = QPushButton("🔄 Actualizar")
        btn_limpiar    = QPushButton("🗑 Limpiar completadas")
        btn_limpiar_todo = QPushButton("🗑 Limpiar todo")
        btn_cerrar     = QPushButton("Cerrar")
 
        def _limpiar_completadas():
            self.historial_dl = [d for d in self.historial_dl if d.get("estado") != "completado"]
            _guardar(DESCARGAS_PATH, self.historial_dl)
            _poblar()
 
        def _limpiar_todo():
            self.historial_dl.clear()
            _guardar(DESCARGAS_PATH, self.historial_dl)
            _poblar()
 
        btn_actualizar.clicked.connect(_poblar)
        btn_limpiar.clicked.connect(_limpiar_completadas)
        btn_limpiar_todo.clicked.connect(_limpiar_todo)
        btn_cerrar.clicked.connect(dial.close)
 
        for b in [btn_actualizar, btn_limpiar, btn_limpiar_todo, btn_cerrar]:
            fila_btns.addWidget(b)
        vl.addLayout(fila_btns)
 
        # show() en vez de exec() — no bloqueante, no se cierra al abrir archivos externos
        dial.setWindowModality(Qt.WindowModality.NonModal)
        dial.show()
        # Guardar referencia para que Python no destruya el diálogo
        self._panel_descargas = dial
 
    def _toggle_vpn(self):
        self._vpn_activo = not self._vpn_activo
        if self._vpn_activo: self.btn_vpn.setText("🟠 VPN"); self.btn_vpn.setStyleSheet("color:#2e7d32; font-weight:bold;"); self._proxy.iniciar()
        else: self._proxy.detener(); self.btn_vpn.setText("🌍"); self.btn_vpn.setStyleSheet(""); QNetworkProxy.setApplicationProxy(QNetworkProxy())
 
    def _on_proxy_cambiado(self, host, port):
        p = QNetworkProxy(); p.setType(QNetworkProxy.ProxyType.HttpProxy); p.setHostName(host); p.setPort(port); QNetworkProxy.setApplicationProxy(p)
 
    def _on_proxy_caido(self): QNetworkProxy.setApplicationProxy(QNetworkProxy())
    
    def _toggle_incognito(self):
        # 1. Invertimos el estado del interruptor (True -> False / False -> True)
        self._incognito = not self._incognito
        
        # 2. Cambiamos el estilo visual del botón para saber si está activo
        if self._incognito:
            self.btn_incognito.setStyleSheet("color:#8ab4f8; font-weight:bold; background:#1f1f1f;")
            print("🕵️ Modo Incógnito Activado. Abriendo entorno seguro...")
            
            # 3. Si se activó, abrimos la pestaña segura automáticamente en el buscador privado Duck Duck
            self._nueva_tab("https://duckduckgo.com/", "🕵️ Incógnito")
        else:
            self.btn_incognito.setStyleSheet("")
            print("🕵️ Modo Incógnito Desactivado. Volviendo a navegación normal.")
 
    def _toggle_antispam(self):
        # Invertimos el estado del interruptor
        self._antispam = not self._antispam
        
        # Guardamos la preferencia en tu JSON de configuración para que recuerde el estado
        self.config_db["antispam_activo"] = self._antispam
        _guardar(CONFIG_PATH, self.config_db)
        
        if self._antispam:
            # Estilo visual activo (Azul/Cian premium)
            self.btn_antispam.setStyleSheet("color:#00e5ff; font-weight:bold; background:#1f1f1f; border: 1px solid #00e5ff;")
            print("🛡️ Filtro Anti-Spam y Bloqueador de publicidad ACTIVADO.")
        else:
            # Volver al estado normal deshabilitado
            self.btn_antispam.setStyleSheet("")
            print("⚠️ Filtro Anti-Spam DESACTIVADO. Publicidad permitida.")
 
 
    def closeEvent(self, event):
        # Forzar escritura de cookies al disco antes de cerrar
        if hasattr(self, '_perfil_persistente'):
            self._perfil_persistente.setPersistentCookiesPolicy(
                QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        self._proxy.detener()
        event.accept()
 
    def guardar_pagina_pdf(self, browser=None):
        """Guarda la página actual como PDF con callback real."""
        if browser is None:
            browser = self._browser_actual()
        if not browser:
            return
        titulo = self.tabs.tabText(self.tabs.currentIndex()).strip() or "pagina"
        for c in r'\/:*?"<>|':
            titulo = titulo.replace(c, "_")
        downloads = os.path.join(
            os.environ.get("USERPROFILE", os.path.expanduser("~")), "Downloads")
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Guardar como PDF",
            os.path.join(downloads, titulo + ".pdf"),
            "PDF (*.pdf)")
        if not ruta:
            return
        self.statusBar().showMessage("⏳ Generando PDF…")
 
        def _cb(ok):
            if ok and os.path.exists(ruta):
                self.statusBar().showMessage(
                    f"✅ Guardado: {os.path.basename(ruta)}", 5000)
            else:
                self.statusBar().showMessage("❌ Error al guardar PDF.", 4000)
 
        browser.page().printToPdf(ruta, _cb)
 
    def ejecutar_impresion_tabs(self, browser=None):
        """Imprime usando printToPdf + callback real — no se cuelga."""
        if browser is None:
            browser = self._browser_actual()
        if not browser:
            return
        import tempfile
        tmp  = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        ruta = tmp.name
        tmp.close()
        self.statusBar().showMessage("⏳ Preparando impresión…")
 
        def _cb(ok):
            if not ok or not os.path.exists(ruta) or os.path.getsize(ruta) == 0:
                self.statusBar().showMessage("❌ Error al preparar la impresión.", 4000)
                return
            try:
                os.startfile(ruta, "print")
                self.statusBar().showMessage("✅ Enviado a la impresora.", 4000)
            except Exception:
                os.startfile(ruta)
                self.statusBar().showMessage("⚠️ Usa Ctrl+P en el visor.", 5000)
 
        browser.page().printToPdf(ruta, _cb)
    
    def dragEnterEvent(self, event):
        """Detecta si el usuario está arrastrando un archivo hacia el navegador"""
        # Verificamos si lo que se arrastra contiene URLs (enlaces o archivos locales)
        if event.mimeData().hasUrls():
            event.acceptProposedAction()  # Cambia el cursor del ratón a modo "Copiar/Soltar"
        else:
            event.ignore()
 
    def dropEvent(self, event):
        """Abre el archivo PDF usando nuestra herramienta de edición interactiva."""
        import os
        from PyQt6.QtCore import QUrl
 
        for url in event.mimeData().urls():
            ruta_pdf = url.toLocalFile()
            
            if ruta_pdf.lower().endswith('.pdf') and os.path.exists(ruta_pdf):
                # 1. Localizamos dónde guardaste el archivo HTML del editor
                # Asumiendo que está en la misma carpeta que Navega_libre.py
                ruta_editor_html = obtener_ruta_recurso("editor_pdf.html")
                
                if os.path.exists(ruta_editor_html):
                    # 2. Construimos la URL combinada: editor_pdf.html?file=file:///C:/...
                    url_editor = QUrl.fromLocalFile(ruta_editor_html)
                    url_final_string = f"{url_editor.toString()}?file={url.toString()}"
                    
                    print(f"🛠️ Abriendo Editor de PDF en pestaña: {url_final_string}")
                    
                    # 3. Lo mandamos a tu función nativa de pestañas
                    self._nueva_tab(url_final_string)
                else:
                    # Si no encuentra el HTML del editor, abre el PDF normal
                    self._nueva_tab(url.toString())
            else:
                # Si es otro tipo de archivo, se abre normal
                self._nueva_tab(url.toString())
                
        event.acceptProposedAction()
 
    def imprimir_con_contexto(self, browser):
 
        url = browser.url().toString()
 
    # Si estamos en el editor PDF
        if "editor_pdf.html" in url:
 
            browser.page().runJavaScript("""
                imprimirDocumento();
        """)
 
    # Cualquier otra página web
        else:
 
            self.ejecutar_impresion_tabs(browser)
 
 
 
# ─────────────────────────────────────────────────────────────
# BLOQUE DE ARRANQUE OFICIAL (RESOLUCIÓN DE CONTEXTO OPENGL)
# ─────────────────────────────────────────────────────────────
import re as _re

class _FiltroStderr:
    """Filtra mensajes específicos de Qt que son warnings inofensivos."""
    _IGNORAR = [
        "Release of profile requested but WebEnginePage still not deleted",
        "gpu/ipc/client/command_buffer_proxy_impl",
        "Use of deprecated",
    ]
    def __init__(self, stream):
        self._s = stream
    def write(self, msg):
        if not any(p in msg for p in self._IGNORAR):
            self._s.write(msg)
    def flush(self): self._s.flush()
    def fileno(self): return self._s.fileno()

import sys as _sys
_sys.stderr = _FiltroStderr(_sys.stderr)


if __name__ == "__main__":
    import traceback
    print("▶ Iniciando NavegaLibre...")
 
    try:
        os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
        # SwiftShader: renderizado software — sin pantalla negra, sin driver GPU
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
            "--use-angle=swiftshader "
            "--disable-blink-features=AutomationControlled "
            "--autoplay-policy=no-user-gesture-required "
            "--disable-logging --log-level=3"
        )
 
        from PyQt6.QtCore import Qt as QtCoreQt
        QApplication.setAttribute(QtCoreQt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
 
        argumentos_qt = sys.argv[:]
        config_inicial = _leer(CONFIG_PATH, CONFIG_DEFAULT)
        addons_instalados = config_inicial.get("addons_rutas", [])
        if addons_instalados:
            argumentos_qt.append(f"--load-extension={','.join(addons_instalados)}")
        app = QApplication(argumentos_qt)
        app.setApplicationName("Navega Libre")
 
        ventana = NavegaLibre()
 
        icono_sistema = _cargar_icono()
        if not icono_sistema.isNull():
            ventana.setWindowIcon(icono_sistema)
            app.setWindowIcon(icono_sistema)
 
        ventana.show()
        sys.exit(app.exec())
 
    except Exception as e:
        print("\n❌ ERROR FATAL:")
        traceback.print_exc()
        input("\nPresiona Enter para cerrar...")
        sys.exit(1)