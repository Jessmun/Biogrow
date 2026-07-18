"""
interfaz.py — Interfaz gráfica de BioGrow Desktop
Ventana principal completa construida con CustomTkinter y ttk.Treeview.
Toda la lógica de UI está aquí; la lógica de negocio vive en utils.py
y la persistencia en database.py.
"""
import tkinter as tk
from tkinter import ttk, messagebox
import customtkinter as ctk
from typing import Optional

from database import DatabaseManager
from models import DatosLote
from utils import (
    calcular_germino,
    estado_germinacion_texto,
    validar_campos_lote,
    parsear_float,
    formatear_numero,
    formatear_fecha_actual,
    centrar_ventana,
    truncar_texto,
)

# ---------------------------------------------------------------------------
# Configuración global de CustomTkinter
# ---------------------------------------------------------------------------

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# Paleta de colores exacta del sistema web original
COLORS = {
    "bg_primary":    "#0b0f19",
    "bg_secondary":  "#111827",
    "bg_card":       "#161c2d",
    "bg_card_light": "#1e2a3a",
    "accent_green":  "#10b981",
    "accent_hover":  "#34d399",
    "accent_indigo": "#6366f1",
    "accent_red":    "#ef4444",
    "accent_amber":  "#f59e0b",
    "text_primary":  "#f8fafc",
    "text_secondary":"#94a3b8",
    "text_muted":    "#64748b",
    "border":        "#1e293b",
    "row_alt":       "#12192a",
}

NUM_MUESTRAS = 27   # Número fijo de filas en la tabla de captura


# ===========================================================================
# BioGrowApp — Ventana principal
# ===========================================================================

class BioGrowApp(ctk.CTk):
    """
    Ventana principal de BioGrow Analytics.
    Hereda de CTk para obtener el tema oscuro automático.
    """

    def __init__(self, db: DatabaseManager):
        super().__init__()
        self.db = db

        # Estado interno de la tabla de captura
        # Lista de 27 elementos: [{"raiz": StringVar, "tallo": StringVar, "germino": IntVar}]
        self._filas_captura: list = []
        # Widget Entry activo en la tabla de captura (edición inline)
        self._entry_activo: Optional[tk.Widget] = None
        # Coordenada de celda activa (fila_idx, col_idx) — col: 0=raiz, 1=tallo
        self._celda_activa: Optional[tuple] = None

        self._configurar_ventana()
        self._aplicar_estilos_ttk()
        self._construir_ui()
        self._inicializar_tabla_captura()
        self._cargar_historial()

    # -----------------------------------------------------------------------
    # Configuración de ventana
    # -----------------------------------------------------------------------

    def _configurar_ventana(self) -> None:
        """Configura título, tamaño y color de fondo de la ventana principal."""
        self.title("BioGrow Analytics — Monitor de Germinación y Biometría de Semillas")
        self.configure(fg_color=COLORS["bg_primary"])
        centrar_ventana(self, 1400, 900)
        self.minsize(1100, 700)
        # Icono (si existe en assets/)
        try:
            import os
            icon_path = os.path.join(os.path.dirname(__file__), "assets", "icon.ico")
            if os.path.exists(icon_path):
                self.iconbitmap(icon_path)
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # Estilos TTK personalizados (para Treeview en modo oscuro)
    # -----------------------------------------------------------------------

    def _aplicar_estilos_ttk(self) -> None:
        """
        Aplica un tema oscuro personalizado al ttk.Treeview.
        CTk no gestiona los estilos de ttk nativamente, por lo que
        se configuran manualmente para coincidir con la paleta.
        """
        style = ttk.Style(self)
        style.theme_use("clam")

        # Fondo general del Treeview
        style.configure(
            "BioGrow.Treeview",
            background=COLORS["bg_card"],
            foreground=COLORS["text_primary"],
            fieldbackground=COLORS["bg_card"],
            borderwidth=0,
            rowheight=32,
            font=("Segoe UI", 10),
        )
        # Encabezados
        style.configure(
            "BioGrow.Treeview.Heading",
            background=COLORS["bg_secondary"],
            foreground=COLORS["text_secondary"],
            relief="flat",
            font=("Segoe UI", 9, "bold"),
            borderwidth=0,
        )
        style.map(
            "BioGrow.Treeview",
            background=[("selected", COLORS["accent_indigo"])],
            foreground=[("selected", COLORS["text_primary"])],
        )
        style.map(
            "BioGrow.Treeview.Heading",
            background=[("active", COLORS["bg_card_light"])],
        )

        # Estilo compacto para la tabla de captura (filas más cortas)
        style.configure(
            "Captura.Treeview",
            background=COLORS["bg_card"],
            foreground=COLORS["text_primary"],
            fieldbackground=COLORS["bg_card"],
            borderwidth=0,
            rowheight=28,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Captura.Treeview.Heading",
            background=COLORS["bg_secondary"],
            foreground=COLORS["text_secondary"],
            relief="flat",
            font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "Captura.Treeview",
            background=[("selected", COLORS["bg_card_light"])],
            foreground=[("selected", COLORS["text_primary"])],
        )

        # Scrollbar oscura
        style.configure(
            "Dark.Vertical.TScrollbar",
            background=COLORS["bg_secondary"],
            troughcolor=COLORS["bg_primary"],
            arrowcolor=COLORS["text_muted"],
            borderwidth=0,
        )
        style.configure(
            "Dark.Horizontal.TScrollbar",
            background=COLORS["bg_secondary"],
            troughcolor=COLORS["bg_primary"],
            arrowcolor=COLORS["text_muted"],
            borderwidth=0,
        )

    # -----------------------------------------------------------------------
    # Construcción de la UI
    # -----------------------------------------------------------------------

    def _construir_ui(self) -> None:
        """Ensambla todos los paneles de la interfaz."""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._construir_header()
        self._construir_cuerpo()

    def _construir_header(self) -> None:
        """Construye la barra de encabezado superior."""
        header = ctk.CTkFrame(
            self,
            fg_color=COLORS["bg_card"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        header.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        # --- Logo e icono ---
        icono_label = ctk.CTkLabel(
            header,
            text="🌱",
            font=ctk.CTkFont(size=32),
        )
        icono_label.grid(row=0, column=0, padx=(20, 0), pady=16, rowspan=2)

        # --- Títulos ---
        titulo_frame = ctk.CTkFrame(header, fg_color="transparent")
        titulo_frame.grid(row=0, column=1, padx=12, pady=(14, 0), sticky="w")

        ctk.CTkLabel(
            titulo_frame,
            text="BioGrow Analytics",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color=COLORS["text_primary"],
        ).pack(side="top", anchor="w")

        ctk.CTkLabel(
            titulo_frame,
            text="Monitor de Germinación y Biometría de Semillas",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_secondary"],
        ).pack(side="top", anchor="w")

        # --- Badge de estado (verde pulsante) ---
        self._badge_estado = ctk.CTkFrame(
            header,
            fg_color="#052e16",
            corner_radius=20,
            border_width=1,
            border_color="#064e3b",
        )
        self._badge_estado.grid(row=0, column=2, padx=20, pady=16, rowspan=2, sticky="e")

        self._lbl_estado_dot = ctk.CTkLabel(
            self._badge_estado,
            text="●",
            font=ctk.CTkFont(size=10),
            text_color=COLORS["accent_green"],
        )
        self._lbl_estado_dot.pack(side="left", padx=(10, 4), pady=8)

        ctk.CTkLabel(
            self._badge_estado,
            text="Base de Datos Conectada",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLORS["accent_green"],
        ).pack(side="left", padx=(0, 12), pady=8)

        # Iniciar animación del punto pulsante
        self._animar_badge(True)

    def _animar_badge(self, visible: bool) -> None:
        """Alterna la visibilidad del punto del badge para simular pulso."""
        color = COLORS["accent_green"] if visible else COLORS["bg_card"]
        self._lbl_estado_dot.configure(text_color=color)
        self.after(900, lambda: self._animar_badge(not visible))

    def _construir_cuerpo(self) -> None:
        """Construye el área principal con panel izquierdo (registro) y panel inferior (historial)."""
        cuerpo = ctk.CTkFrame(self, fg_color="transparent")
        cuerpo.grid(row=1, column=0, padx=16, pady=(0, 16), sticky="nsew")
        cuerpo.grid_columnconfigure(0, weight=5)
        cuerpo.grid_columnconfigure(1, weight=4)
        cuerpo.grid_rowconfigure(0, weight=1)

        self._construir_panel_registro(cuerpo)
        self._construir_panel_historial(cuerpo)

    # -----------------------------------------------------------------------
    # Panel izquierdo — Registro de muestra
    # -----------------------------------------------------------------------

    def _construir_panel_registro(self, padre: ctk.CTkFrame) -> None:
        """Construye el panel de registro de muestras (formulario + tabla captura)."""
        panel = ctk.CTkFrame(
            padre,
            fg_color=COLORS["bg_card"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        panel.grid(row=0, column=0, padx=(0, 8), sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(2, weight=1)

        # --- Título de sección ---
        ctk.CTkLabel(
            panel,
            text="📥  Registro de Muestra por Lote",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLORS["text_primary"],
            anchor="w",
        ).grid(row=0, column=0, padx=20, pady=(18, 0), sticky="w")

        ctk.CTkFrame(panel, height=1, fg_color=COLORS["border"]).grid(
            row=1, column=0, padx=20, pady=(10, 0), sticky="ew"
        )

        # --- Contenedor interior con scroll ---
        scroll_frame = ctk.CTkScrollableFrame(
            panel,
            fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["text_muted"],
        )
        scroll_frame.grid(row=2, column=0, padx=4, pady=4, sticky="nsew")
        scroll_frame.grid_columnconfigure(0, weight=1)

        self._construir_campos_generales(scroll_frame)
        self._construir_tabla_captura(scroll_frame)
        self._construir_boton_guardar(scroll_frame)

    def _construir_campos_generales(self, padre) -> None:
        """Construye el formulario de campos generales del lote."""
        frame = ctk.CTkFrame(
            padre,
            fg_color="#0f172a",
            corner_radius=8,
            border_width=1,
            border_color=COLORS["border"],
        )
        frame.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="ew")
        frame.grid_columnconfigure((0, 1), weight=1)

        # Identificador del Lote
        self._construir_campo(frame, "Identificador del Lote / Excel", 0, 0,
                              placeholder="Ej: Lote 16-Mayo")
        self._entry_lote = self._ultimo_entry

        # Variedad de Semilla
        lbl2 = ctk.CTkLabel(frame, text="Variedad de Semilla",
                             font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
                             text_color=COLORS["text_secondary"], anchor="w")
        lbl2.grid(row=0, column=1, padx=(8, 16), pady=(16, 4), sticky="w")
        self._combo_semilla = ctk.CTkComboBox(
            frame,
            values=["Semilla-B", "Semilla-Rosa"],
            fg_color="#0f172a",
            border_color=COLORS["border"],
            button_color=COLORS["border"],
            button_hover_color=COLORS["accent_green"],
            dropdown_fg_color=COLORS["bg_card"],
            dropdown_hover_color=COLORS["bg_card_light"],
            text_color=COLORS["text_primary"],
            font=ctk.CTkFont(family="Segoe UI", size=12),
            state="readonly",
        )
        self._combo_semilla.set("Semilla-B")
        self._combo_semilla.grid(row=1, column=1, padx=(8, 16), pady=(0, 16), sticky="ew")

        # Fecha de Registro
        self._construir_campo(frame, "Fecha de Registro", 2, 0,
                              placeholder="YYYY-MM-DD HH:MM",
                              valor_inicial=formatear_fecha_actual())
        self._entry_fecha = self._ultimo_entry

        # Tiempo de Tratamiento
        self._construir_campo(frame, "Tiempo de Tratamiento", 2, 1,
                              placeholder="Ej: 45s, Control, T-1M")
        self._entry_tratamiento = self._ultimo_entry

    def _construir_campo(self, padre, etiqueta: str, fila: int, col: int,
                         placeholder: str = "", valor_inicial: str = "") -> None:
        """Helper para crear un par etiqueta+entry en el grid."""
        ctk.CTkLabel(
            padre,
            text=etiqueta,
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLORS["text_secondary"],
            anchor="w",
        ).grid(row=fila, column=col, padx=(16 if col == 0 else 8, 8 if col == 0 else 16),
               pady=(16, 4), sticky="w")

        entry = ctk.CTkEntry(
            padre,
            placeholder_text=placeholder,
            fg_color="#0f172a",
            border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            placeholder_text_color=COLORS["text_muted"],
            font=ctk.CTkFont(family="Segoe UI", size=12),
        )
        if valor_inicial:
            entry.insert(0, valor_inicial)
        entry.grid(row=fila + 1, column=col,
                   padx=(16 if col == 0 else 8, 8 if col == 0 else 16),
                   pady=(0, 16), sticky="ew")
        # Guardar referencia para el método llamante
        self._ultimo_entry = entry

    # -----------------------------------------------------------------------
    # Tabla de captura de 27 muestras
    # -----------------------------------------------------------------------

    def _construir_tabla_captura(self, padre) -> None:
        """Construye la tabla de captura de 27 filas con edición inline."""
        # Título de la tabla
        ctk.CTkLabel(
            padre,
            text="📊  Tabla de Captura — 27 Muestras",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=COLORS["text_secondary"],
            anchor="w",
        ).grid(row=1, column=0, padx=16, pady=(4, 6), sticky="w")

        # Marco contenedor
        tabla_frame = ctk.CTkFrame(
            padre,
            fg_color=COLORS["bg_card"],
            corner_radius=8,
            border_width=1,
            border_color=COLORS["border"],
        )
        tabla_frame.grid(row=2, column=0, padx=16, pady=(0, 8), sticky="ew")
        tabla_frame.grid_columnconfigure(0, weight=1)

        # Treeview de captura
        columnas = ("no", "raiz", "tallo", "estado")
        self._tree_captura = ttk.Treeview(
            tabla_frame,
            columns=columnas,
            show="headings",
            style="Captura.Treeview",
            height=14,   # Filas visibles sin scroll
            selectmode="browse",
        )

        # Encabezados
        self._tree_captura.heading("no",     text="No.",               anchor="center")
        self._tree_captura.heading("raiz",   text="Longitud Raíz (mm)", anchor="center")
        self._tree_captura.heading("tallo",  text="Longitud Tallo (mm)", anchor="center")
        self._tree_captura.heading("estado", text="Estado de Germinación", anchor="center")

        # Anchos de columna
        self._tree_captura.column("no",     width=50,  minwidth=40,  anchor="center", stretch=False)
        self._tree_captura.column("raiz",   width=160, minwidth=120, anchor="center")
        self._tree_captura.column("tallo",  width=160, minwidth=120, anchor="center")
        self._tree_captura.column("estado", width=180, minwidth=140, anchor="center")

        # Scrollbar vertical
        vsb_captura = ttk.Scrollbar(
            tabla_frame, orient="vertical",
            command=self._tree_captura.yview,
            style="Dark.Vertical.TScrollbar",
        )
        self._tree_captura.configure(yscrollcommand=vsb_captura.set)

        self._tree_captura.grid(row=0, column=0, sticky="nsew")
        vsb_captura.grid(row=0, column=1, sticky="ns")

        # Tags de color para el estado en la tabla de captura
        self._tree_captura.tag_configure("germino_si",
                                          foreground=COLORS["accent_green"])
        self._tree_captura.tag_configure("germino_no",
                                          foreground=COLORS["text_muted"])
        self._tree_captura.tag_configure("row_alt",
                                          background=COLORS["row_alt"])

        # Eventos de la tabla de captura
        self._tree_captura.bind("<Double-1>",    self._on_doble_click_captura)
        self._tree_captura.bind("<Return>",      self._on_enter_captura)
        self._tree_captura.bind("<Up>",          self._on_arrow_captura)
        self._tree_captura.bind("<Down>",        self._on_arrow_captura)
        self._tree_captura.bind("<Left>",        self._on_arrow_captura)
        self._tree_captura.bind("<Right>",       self._on_arrow_captura)
        self._tree_captura.bind("<<TreeviewSelect>>", self._on_seleccion_captura)

    def _inicializar_tabla_captura(self) -> None:
        """Puebla la tabla de captura con 27 filas vacías (0.00)."""
        # Limpiar estado interno
        self._filas_captura = []
        # Eliminar filas existentes en el treeview
        for item in self._tree_captura.get_children():
            self._tree_captura.delete(item)

        for i in range(1, NUM_MUESTRAS + 1):
            fila_data = {"raiz": 0.0, "tallo": 0.0}
            self._filas_captura.append(fila_data)
            tag = "row_alt" if i % 2 == 0 else ""
            self._tree_captura.insert(
                "", "end",
                iid=str(i),
                values=(i, "0.00", "0.00", "○  No germinó"),
                tags=(tag,),
            )

    def _actualizar_fila_estado(self, fila_idx: int) -> None:
        """
        Recalcula el estado de germinación de una fila y actualiza el Treeview.

        Args:
            fila_idx: Índice 0-based de la fila en self._filas_captura
        """
        fila = self._filas_captura[fila_idx]
        germino = calcular_germino(fila["raiz"], fila["tallo"])
        num = fila_idx + 1
        iid = str(num)

        # Determinar etiqueta visual y tag de color
        if germino == 1:
            estado_txt = "✓  Germinó"
            tag_estado = "germino_si"
        else:
            estado_txt = "○  No germinó"
            tag_estado = "germino_no"

        # Conservar el tag de fila alterna si corresponde
        tag_base = "row_alt" if num % 2 == 0 else ""
        tags = (tag_base, tag_estado) if tag_base else (tag_estado,)

        self._tree_captura.item(
            iid,
            values=(num,
                    formatear_numero(fila["raiz"]),
                    formatear_numero(fila["tallo"]),
                    estado_txt),
            tags=tags,
        )

    # -----------------------------------------------------------------------
    # Edición inline de la tabla de captura
    # -----------------------------------------------------------------------

    def _on_seleccion_captura(self, event) -> None:
        """Cierra el editor si se hace clic en otra fila."""
        self._cerrar_entry_activo(guardar=True)

    def _on_doble_click_captura(self, event) -> None:
        """Abre un Entry inline para editar la celda sobre la que se hizo doble clic."""
        region = self._tree_captura.identify_region(event.x, event.y)
        if region != "cell":
            return

        col_id = self._tree_captura.identify_column(event.x)
        item_id = self._tree_captura.identify_row(event.y)
        if not item_id:
            return

        col_num = int(col_id.replace("#", ""))   # #1=no, #2=raiz, #3=tallo, #4=estado
        if col_num not in (2, 3):   # Solo raiz y tallo son editables
            return

        self._abrir_entry_inline(item_id, col_num)

    def _on_enter_captura(self, event) -> None:
        """Al presionar Enter en la tabla, edita la celda de raíz de la fila seleccionada."""
        sel = self._tree_captura.selection()
        if not sel:
            return
        item_id = sel[0]
        # Si ya hay un editor activo, guardar y mover al siguiente
        if self._entry_activo and self._celda_activa:
            self._cerrar_entry_activo(guardar=True)
            fila_idx = int(item_id) - 1
            col_num = self._celda_activa[1]
            # Mover a la misma columna de la siguiente fila
            siguiente = fila_idx + 1
            if siguiente < NUM_MUESTRAS:
                nuevo_iid = str(siguiente + 1)
                self._tree_captura.selection_set(nuevo_iid)
                self._tree_captura.see(nuevo_iid)
                self._abrir_entry_inline(nuevo_iid, col_num)
        else:
            self._abrir_entry_inline(item_id, 2)   # Empezar editando raíz

    def _on_arrow_captura(self, event) -> None:
        """Maneja la navegación con teclas de flecha en la tabla de captura."""
        sel = self._tree_captura.selection()
        if not sel:
            return

        item_id = sel[0]
        fila_idx = int(item_id) - 1
        col_actual = self._celda_activa[1] if self._celda_activa else 2

        nueva_fila = fila_idx
        nueva_col = col_actual

        if event.keysym == "Up" and fila_idx > 0:
            nueva_fila = fila_idx - 1
        elif event.keysym == "Down" and fila_idx < NUM_MUESTRAS - 1:
            nueva_fila = fila_idx + 1
        elif event.keysym == "Left" and col_actual == 3:
            nueva_col = 2   # Mover a raíz
        elif event.keysym == "Right" and col_actual == 2:
            nueva_col = 3   # Mover a tallo

        self._cerrar_entry_activo(guardar=True)

        nuevo_iid = str(nueva_fila + 1)
        self._tree_captura.selection_set(nuevo_iid)
        self._tree_captura.see(nuevo_iid)
        self._abrir_entry_inline(nuevo_iid, nueva_col)

    def _abrir_entry_inline(self, item_id: str, col_num: int) -> None:
        """
        Abre un widget Entry flotante sobre la celda indicada para edición inline.

        Args:
            item_id: IID del ítem en el Treeview (="1" a "27")
            col_num: Número de columna (#2=raiz, #3=tallo)
        """
        self._cerrar_entry_activo(guardar=True)

        fila_idx = int(item_id) - 1
        valores = self._tree_captura.item(item_id, "values")
        valor_actual = valores[col_num - 1]   # col_num 2 → index 1 (raiz), col_num 3 → index 2 (tallo)

        # Obtener bounding box de la celda para posicionar el Entry
        bbox = self._tree_captura.bbox(item_id, f"#{col_num}")
        if not bbox:
            return   # Celda fuera del área visible
        x, y, w, h = bbox

        # Crear Entry flotante directamente sobre el Treeview
        entry = tk.Entry(
            self._tree_captura,
            font=("Segoe UI", 10),
            bg="#0f172a",
            fg=COLORS["text_primary"],
            insertbackground=COLORS["text_primary"],
            relief="flat",
            bd=2,
            highlightthickness=2,
            highlightbackground=COLORS["accent_green"],
            highlightcolor=COLORS["accent_green"],
            justify="center",
        )
        entry.place(x=x, y=y, width=w, height=h)
        entry.insert(0, valor_actual.replace(",", "."))
        entry.select_range(0, tk.END)
        entry.focus_set()

        # Guardar referencias
        self._entry_activo = entry
        self._celda_activa = (fila_idx, col_num)

        # Bindings del entry
        entry.bind("<Return>",    lambda e: self._on_enter_captura(e))
        entry.bind("<Escape>",    lambda e: self._cerrar_entry_activo(guardar=False))
        entry.bind("<FocusOut>",  lambda e: self._cerrar_entry_activo(guardar=True))
        entry.bind("<Tab>",       lambda e: self._tab_captura())
        entry.bind("<Up>",        lambda e: self._arrow_desde_entry("Up"))
        entry.bind("<Down>",      lambda e: self._arrow_desde_entry("Down"))
        entry.bind("<Left>",      lambda e: self._arrow_desde_entry("Left"))
        entry.bind("<Right>",     lambda e: self._arrow_desde_entry("Right"))

    def _cerrar_entry_activo(self, guardar: bool = True) -> None:
        """
        Cierra el Entry inline activo.

        Args:
            guardar: Si True, persiste el valor en self._filas_captura y actualiza la fila.
        """
        if self._entry_activo is None:
            return

        if guardar:
            texto = self._entry_activo.get()
            fila_idx, col_num = self._celda_activa
            valor = parsear_float(texto, default=0.0)
            if col_num == 2:
                self._filas_captura[fila_idx]["raiz"] = valor
            else:
                self._filas_captura[fila_idx]["tallo"] = valor
            self._actualizar_fila_estado(fila_idx)

        try:
            self._entry_activo.destroy()
        except Exception:
            pass
        self._entry_activo = None
        self._celda_activa = None

    def _tab_captura(self) -> None:
        """Tab dentro del editor inline: mueve a la siguiente columna o fila."""
        if not self._celda_activa:
            return
        fila_idx, col_num = self._celda_activa
        self._cerrar_entry_activo(guardar=True)

        if col_num == 2:
            nueva_col = 3
            nueva_fila = fila_idx
        else:
            nueva_col = 2
            nueva_fila = fila_idx + 1

        if nueva_fila < NUM_MUESTRAS:
            nuevo_iid = str(nueva_fila + 1)
            self._tree_captura.selection_set(nuevo_iid)
            self._tree_captura.see(nuevo_iid)
            self._abrir_entry_inline(nuevo_iid, nueva_col)

    def _arrow_desde_entry(self, direccion: str) -> None:
        """Simula el evento de flecha desde dentro del Entry activo."""
        class _Ev:
            def __init__(self, key): self.keysym = key
        self._on_arrow_captura(_Ev(direccion))

    # -----------------------------------------------------------------------
    # Botón Guardar
    # -----------------------------------------------------------------------

    def _construir_boton_guardar(self, padre) -> None:
        """Construye el botón de guardado con su estado visual."""
        self._btn_guardar = ctk.CTkButton(
            padre,
            text="💾   Guardar Registro",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=COLORS["accent_green"],
            hover_color=COLORS["accent_hover"],
            text_color="#ffffff",
            height=44,
            corner_radius=8,
            command=self._guardar_lote,
        )
        self._btn_guardar.grid(row=3, column=0, padx=16, pady=(4, 16), sticky="ew")

    def _guardar_lote(self) -> None:
        """
        Manejador del botón Guardar. Valida, persiste en SQLite y actualiza la UI.
        Usa una única transacción (database.py lo garantiza).
        """
        # Cerrar cualquier editor inline abierto antes de leer valores
        self._cerrar_entry_activo(guardar=True)

        # Leer campos generales
        nombre_lote      = self._entry_lote.get().strip()
        tipo_semilla     = self._combo_semilla.get()
        fecha_registro   = self._entry_fecha.get().strip()
        tiempo_trat      = self._entry_tratamiento.get().strip()

        # Validar campos generales
        valido, msg_error = validar_campos_lote(nombre_lote, tipo_semilla, fecha_registro, tiempo_trat)
        if not valido:
            messagebox.showerror("Campo obligatorio", msg_error, parent=self)
            return

        # Construir lista de mediciones
        mediciones = []
        for i, fila in enumerate(self._filas_captura, start=1):
            mediciones.append({
                "num_muestra":   i,
                "longitud_raiz": fila["raiz"],
                "longitud_tallo": fila["tallo"],
            })

        datos = DatosLote(
            nombre_lote=nombre_lote,
            tipo_semilla=tipo_semilla,
            fecha_registro=fecha_registro,
            tiempo_tratamiento=tiempo_trat,
            mediciones=mediciones,
        )

        # Deshabilitar botón para evitar doble clic
        self._btn_guardar.configure(state="disabled", text="⏳   Guardando...")

        # Guardar en la BD
        exito, mensaje = self.db.guardar_lote(datos)

        # Rehabilitar botón
        self._btn_guardar.configure(state="normal", text="💾   Guardar Registro")

        if exito:
            messagebox.showinfo("✅ Registro Guardado", mensaje, parent=self)
            self._limpiar_formulario()
            self._cargar_historial()
        else:
            messagebox.showerror("❌ Error al Guardar", mensaje, parent=self)

    def _limpiar_formulario(self) -> None:
        """Limpia el formulario y reinicia la tabla de captura a 0.00."""
        self._entry_lote.delete(0, tk.END)
        self._combo_semilla.set("Semilla-B")
        self._entry_fecha.delete(0, tk.END)
        self._entry_fecha.insert(0, formatear_fecha_actual())
        self._entry_tratamiento.delete(0, tk.END)
        self._inicializar_tabla_captura()

    # -----------------------------------------------------------------------
    # Panel derecho — Historial y filtros
    # -----------------------------------------------------------------------

    def _construir_panel_historial(self, padre: ctk.CTkFrame) -> None:
        """Construye el panel del historial con filtros y Treeview."""
        panel = ctk.CTkFrame(
            padre,
            fg_color=COLORS["bg_card"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        panel.grid(row=0, column=1, padx=(8, 0), sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(3, weight=1)

        # --- Título ---
        ctk.CTkLabel(
            panel,
            text="📋  Historial Consolidado",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLORS["text_primary"],
            anchor="w",
        ).grid(row=0, column=0, padx=20, pady=(18, 0), sticky="w")

        ctk.CTkFrame(panel, height=1, fg_color=COLORS["border"]).grid(
            row=1, column=0, padx=20, pady=(10, 0), sticky="ew"
        )

        # --- Barra de filtros ---
        self._construir_filtros(panel)

        # --- Treeview historial ---
        self._construir_treeview_historial(panel)

    def _construir_filtros(self, padre) -> None:
        """Construye los controles de filtro sobre el historial."""
        filtros_frame = ctk.CTkFrame(padre, fg_color="transparent")
        filtros_frame.grid(row=2, column=0, padx=16, pady=(12, 8), sticky="ew")
        filtros_frame.grid_columnconfigure(0, weight=2)
        filtros_frame.grid_columnconfigure(1, weight=1)
        filtros_frame.grid_columnconfigure(2, weight=1)

        # Variables reactivas para los filtros
        self._var_busqueda    = tk.StringVar()
        self._var_semilla     = tk.StringVar(value="")
        self._var_germino     = tk.StringVar(value="")

        # Vincular cambios a la función de filtrado
        self._var_busqueda.trace_add("write", lambda *_: self._cargar_historial())
        self._var_semilla.trace_add("write",  lambda *_: self._cargar_historial())
        self._var_germino.trace_add("write",  lambda *_: self._cargar_historial())

        # Campo de búsqueda general
        ctk.CTkEntry(
            filtros_frame,
            placeholder_text="🔍  Buscar lote, tratamiento...",
            textvariable=self._var_busqueda,
            fg_color="#0f172a",
            border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            placeholder_text_color=COLORS["text_muted"],
            font=ctk.CTkFont(family="Segoe UI", size=11),
        ).grid(row=0, column=0, padx=(0, 6), sticky="ew")

        # Filtro tipo de semilla
        ctk.CTkComboBox(
            filtros_frame,
            variable=self._var_semilla,
            values=["", "Semilla-B", "Semilla-Rosa"],
            fg_color="#0f172a",
            border_color=COLORS["border"],
            button_color=COLORS["border"],
            button_hover_color=COLORS["accent_green"],
            dropdown_fg_color=COLORS["bg_card"],
            dropdown_hover_color=COLORS["bg_card_light"],
            text_color=COLORS["text_primary"],
            font=ctk.CTkFont(family="Segoe UI", size=11),
            state="readonly",
        ).grid(row=0, column=1, padx=(0, 6), sticky="ew")

        # Filtro estado de germinación
        ctk.CTkComboBox(
            filtros_frame,
            variable=self._var_germino,
            values=["", "1", "0"],
            fg_color="#0f172a",
            border_color=COLORS["border"],
            button_color=COLORS["border"],
            button_hover_color=COLORS["accent_green"],
            dropdown_fg_color=COLORS["bg_card"],
            dropdown_hover_color=COLORS["bg_card_light"],
            text_color=COLORS["text_primary"],
            font=ctk.CTkFont(family="Segoe UI", size=11),
            state="readonly",
        ).grid(row=0, column=2, sticky="ew")

        # Etiquetas de referencia para los combos de filtro
        self._lbl_total = ctk.CTkLabel(
            padre,
            text="",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=COLORS["text_muted"],
            anchor="e",
        )
        self._lbl_total.grid(row=2, column=0, padx=20, pady=(0, 0), sticky="e")

    def _construir_treeview_historial(self, padre) -> None:
        """Construye el Treeview principal del historial con scrollbars."""
        tree_frame = ctk.CTkFrame(
            padre,
            fg_color=COLORS["bg_card"],
            corner_radius=8,
            border_width=1,
            border_color=COLORS["border"],
        )
        tree_frame.grid(row=3, column=0, padx=16, pady=(0, 16), sticky="nsew")
        tree_frame.grid_columnconfigure(0, weight=1)
        tree_frame.grid_rowconfigure(0, weight=1)

        columnas = ("lote", "semilla", "muestra", "tratamiento", "raiz", "tallo", "resultado")
        self._tree_historial = ttk.Treeview(
            tree_frame,
            columns=columnas,
            show="headings",
            style="BioGrow.Treeview",
            selectmode="browse",
        )

        # Encabezados
        encabezados = {
            "lote":        ("Lote Origen",    120, "w"),
            "semilla":     ("Tipo Semilla",   110, "center"),
            "muestra":     ("No.",             45,  "center"),
            "tratamiento": ("Tratamiento",     90, "center"),
            "raiz":        ("Raíz (mm)",       70, "center"),
            "tallo":       ("Tallo (mm)",      70, "center"),
            "resultado":   ("Resultado",      100, "center"),
        }
        for col, (texto, ancho, anchor) in encabezados.items():
            self._tree_historial.heading(col, text=texto, anchor=anchor)
            self._tree_historial.column(col, width=ancho, minwidth=40, anchor=anchor, stretch=(col == "lote"))

        # Scrollbars
        vsb = ttk.Scrollbar(tree_frame, orient="vertical",
                             command=self._tree_historial.yview,
                             style="Dark.Vertical.TScrollbar")
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal",
                             command=self._tree_historial.xview,
                             style="Dark.Horizontal.TScrollbar")
        self._tree_historial.configure(
            yscrollcommand=vsb.set,
            xscrollcommand=hsb.set,
        )

        self._tree_historial.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        # Tags de color para el resultado
        self._tree_historial.tag_configure("germino_si",
                                            foreground=COLORS["accent_green"])
        self._tree_historial.tag_configure("germino_no",
                                            foreground=COLORS["accent_red"])
        self._tree_historial.tag_configure("row_alt",
                                            background=COLORS["row_alt"])

    # -----------------------------------------------------------------------
    # Carga y actualización del historial
    # -----------------------------------------------------------------------

    def _cargar_historial(self) -> None:
        """
        Consulta el historial con los filtros activos y actualiza el Treeview.
        Se llama en el arranque y después de guardar un nuevo lote.
        """
        # Leer valores de filtro actuales
        busqueda  = self._var_busqueda.get().strip()
        semilla   = self._var_semilla.get()
        germino   = self._var_germino.get()

        # Normalizar el valor del combo de germinación para la consulta
        filtro_germ = ""
        if germino == "1":
            filtro_germ = "1"
        elif germino == "0":
            filtro_germ = "0"

        registros = self.db.obtener_historial(
            texto_busqueda=busqueda,
            filtro_semilla=semilla,
            filtro_germino=filtro_germ,
        )

        # Limpiar Treeview
        for item in self._tree_historial.get_children():
            self._tree_historial.delete(item)

        # Insertar filas
        for idx, reg in enumerate(registros):
            if reg.germino == 1:
                estado_txt = "✓  Germinó"
                tag_estado = "germino_si"
            else:
                estado_txt = "✗  No germinó"
                tag_estado = "germino_no"

            tag_fila = "row_alt" if idx % 2 == 1 else ""
            tags = (tag_fila, tag_estado) if tag_fila else (tag_estado,)

            self._tree_historial.insert(
                "", "end",
                values=(
                    truncar_texto(reg.nombre_lote, 20),
                    reg.tipo_semilla,
                    reg.num_muestra,
                    reg.condicion_tratamiento,
                    reg.raiz_fmt,
                    reg.tallo_fmt,
                    estado_txt,
                ),
                tags=tags,
            )

        # Actualizar contador
        total = len(registros)
        self._lbl_total.configure(
            text=f"{total} registro{'s' if total != 1 else ''} encontrado{'s' if total != 1 else ''}"
        )
