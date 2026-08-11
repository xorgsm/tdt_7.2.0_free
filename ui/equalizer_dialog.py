"""
Diálogo "Ecualizador": graves/medios/agudos reales sobre el audio en
curso (TV o radio, es el mismo VLCPlayer para ambos), usando el
ecualizador gráfico de fábrica de libVLC -- no es el visual animado de
ui/widgets.EqualizerWidget (ese sigue siendo solo un indicador visual).

Coder By X@R
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QCheckBox, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QSlider, QVBoxLayout, QWidget,
)

from core import config as cfg
from ui import palette
from ui.visual import set_surface

# Índices fijos al principio del combo de presets, antes de los presets
# reales de libVLC (que se añaden a partir de aquí en __init__).
_INDICE_PERSONALIZADO = 0
_INDICE_PLANO = 1
_PRIMER_PRESET_LIBVLC = 2

_PREAMP_MIN, _PREAMP_MAX = -20, 20
_BANDA_MIN, _BANDA_MAX = -20, 20


class EqualizerDialog(QDialog):
    """Ecualizador de audio real (graves/medios/agudos) para TV y radio."""

    def __init__(self, window):
        super().__init__(window)
        set_surface(self, "dialog")
        self.win = window
        self.player = window.player
        self.setWindowTitle("Ecualizador")
        self.setMinimumWidth(520)

        self._banda_sliders = []
        self._banda_labels = []
        self._actualizando = False  # evita reentradas al fijar sliders desde un preset

        layout = QVBoxLayout(self)

        if not self.player.disponible or self.player.equalizer_band_count() == 0:
            layout.addWidget(QLabel(
                "El ecualizador no está disponible (el motor de VLC no se "
                "pudo inicializar en este equipo)."
            ))
            buttons = QDialogButtonBox(QDialogButtonBox.Close)
            buttons.rejected.connect(self.accept)
            layout.addWidget(buttons)
            return

        self._num_bandas = self.player.equalizer_band_count()
        self._frecuencias = [
            self.player.equalizer_band_frequency(i) for i in range(self._num_bandas)
        ]

        estado = window.settings
        self._enabled = bool(estado.get("equalizer_enabled", False))
        self._preamp = float(estado.get("equalizer_preamp", 0.0))
        bandas_guardadas = estado.get("equalizer_bands") or []
        if len(bandas_guardadas) == self._num_bandas:
            self._bands = [float(v) for v in bandas_guardadas]
        else:
            self._bands = [0.0] * self._num_bandas

        # ---------- activar/desactivar ----------
        self.enable_check = QCheckBox("Activar ecualizador")
        self.enable_check.setChecked(self._enabled)
        self.enable_check.toggled.connect(self._on_toggle_enabled)
        layout.addWidget(self.enable_check)

        # ---------- presets ----------
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("Personalizado")
        self.preset_combo.addItem("Plano (sin efecto)")
        for nombre in self.player.equalizer_preset_names():
            self.preset_combo.addItem(nombre)
        self.preset_combo.setCurrentIndex(_INDICE_PERSONALIZADO)
        self.preset_combo.activated.connect(self._on_preset_chosen)
        preset_row.addWidget(self.preset_combo, stretch=1)
        layout.addLayout(preset_row)

        # ---------- preamplificación ----------
        preamp_row = QHBoxLayout()
        preamp_row.addWidget(QLabel("Preamplificación"))
        self.preamp_slider = QSlider(Qt.Horizontal)
        self.preamp_slider.setRange(_PREAMP_MIN, _PREAMP_MAX)
        self.preamp_slider.setValue(round(self._preamp))
        self.preamp_slider.valueChanged.connect(self._on_preamp_changed)
        self.preamp_slider.sliderReleased.connect(self._guardar_estado)
        preamp_row.addWidget(self.preamp_slider, stretch=1)
        self.preamp_value_label = QLabel(f"{self.preamp_slider.value():+d} dB")
        self.preamp_value_label.setMinimumWidth(50)
        preamp_row.addWidget(self.preamp_value_label)
        layout.addLayout(preamp_row)

        # ---------- bandas de frecuencia ----------
        bands_row = QHBoxLayout()
        bands_row.setSpacing(4)
        for i in range(self._num_bandas):
            columna = QVBoxLayout()
            slider = QSlider(Qt.Vertical)
            slider.setRange(_BANDA_MIN, _BANDA_MAX)
            slider.setValue(round(self._bands[i]))
            slider.setMinimumHeight(140)
            slider.valueChanged.connect(lambda valor, idx=i: self._on_band_changed(idx, valor))
            slider.sliderReleased.connect(self._guardar_estado)
            columna.addWidget(slider, alignment=Qt.AlignHCenter)

            valor_label = QLabel(f"{slider.value():+d}")
            valor_label.setAlignment(Qt.AlignCenter)
            valor_label.setStyleSheet(f"color: {palette.TEXT_MUTED}; font-size: 8pt;")
            columna.addWidget(valor_label)

            freq = self._frecuencias[i]
            texto_freq = f"{freq / 1000:.1f}k" if freq >= 1000 else f"{freq:.0f}"
            freq_label = QLabel(texto_freq)
            freq_label.setAlignment(Qt.AlignCenter)
            freq_label.setStyleSheet(f"color: {palette.TEXT_MUTED}; font-size: 8pt;")
            columna.addWidget(freq_label)

            contenedor = QWidget()
            contenedor.setLayout(columna)
            bands_row.addWidget(contenedor)

            self._banda_sliders.append(slider)
            self._banda_labels.append(valor_label)
        layout.addLayout(bands_row)

        # ---------- botones ----------
        botones_row = QHBoxLayout()
        reset_btn = QPushButton("Restablecer (plano)")
        reset_btn.clicked.connect(self._restablecer)
        botones_row.addWidget(reset_btn)
        botones_row.addStretch(1)
        cerrar_btn = QDialogButtonBox(QDialogButtonBox.Close)
        cerrar_btn.rejected.connect(self.accept)
        botones_row.addWidget(cerrar_btn)
        layout.addLayout(botones_row)

        self._set_controles_habilitados(self._enabled)
        if self._enabled:
            self.player.set_equalizer(self._preamp, self._bands)

    # ---------- estado / aplicar ----------

    def _set_controles_habilitados(self, habilitado: bool):
        self.preset_combo.setEnabled(habilitado)
        self.preamp_slider.setEnabled(habilitado)
        for slider in self._banda_sliders:
            slider.setEnabled(habilitado)

    def _on_toggle_enabled(self, checked: bool):
        self._enabled = checked
        self._set_controles_habilitados(checked)
        if checked:
            self.player.set_equalizer(self._preamp, self._bands)
        else:
            self.player.clear_equalizer()
        self._guardar_estado()

    def _on_preamp_changed(self, valor: int):
        self._preamp = float(valor)
        self.preamp_value_label.setText(f"{valor:+d} dB")
        if not self._actualizando:
            self.preset_combo.setCurrentIndex(_INDICE_PERSONALIZADO)
        if self._enabled:
            self.player.set_equalizer(self._preamp, self._bands)

    def _on_band_changed(self, indice: int, valor: int):
        self._bands[indice] = float(valor)
        self._banda_labels[indice].setText(f"{valor:+d}")
        if not self._actualizando:
            self.preset_combo.setCurrentIndex(_INDICE_PERSONALIZADO)
        if self._enabled:
            self.player.set_equalizer(self._preamp, self._bands)

    def _on_preset_chosen(self, indice: int):
        if indice == _INDICE_PERSONALIZADO:
            return
        if indice == _INDICE_PLANO:
            preamp, bandas = 0.0, [0.0] * self._num_bandas
        else:
            preamp, bandas = self.player.equalizer_preset_values(indice - _PRIMER_PRESET_LIBVLC)
            if not bandas:
                bandas = [0.0] * self._num_bandas

        self._actualizando = True
        try:
            self.preamp_slider.setValue(round(preamp))
            for slider, valor in zip(self._banda_sliders, bandas):
                slider.setValue(round(valor))
        finally:
            self._actualizando = False

        self._preamp = preamp
        self._bands = list(bandas)
        if self._enabled:
            self.player.set_equalizer(self._preamp, self._bands)
        self._guardar_estado()

    def _restablecer(self):
        self.preset_combo.setCurrentIndex(_INDICE_PLANO)
        self._on_preset_chosen(_INDICE_PLANO)

    def _guardar_estado(self):
        estado = self.win.settings
        estado["equalizer_enabled"] = self._enabled
        estado["equalizer_preamp"] = self._preamp
        estado["equalizer_bands"] = list(self._bands)
        if not cfg.save_settings(estado):
            QMessageBox.warning(
                self,
                "No se pudieron guardar los ajustes",
                "No se pudieron guardar los ajustes. Inténtalo de nuevo.",
            )
