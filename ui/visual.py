"""Helpers visuales compartidos, sin lógica de negocio."""

from PySide6.QtWidgets import QWidget


VALID_VARIANTS = frozenset({
    "default",
    "primary",
    "secondary",
    "ghost",
    "danger",
    "info",
    "success",
    "cast",
    "sleep",
    "tv",
    "radio",
    "podcast",
    "download",
})

VALID_STATES = frozenset({"default", "active", "loading", "empty", "error"})
VALID_SURFACES = frozenset({"default", "dialog", "floating", "sidebar", "mediaPanel", "homeSectionCard"})


def _set_dynamic(widget: QWidget, name: str, value: str) -> None:
    widget.setProperty(name, value)
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()


def set_variant(widget: QWidget, variant: str) -> str:
    """Aplica una variante conocida y degrada las desconocidas a default."""
    safe = variant if variant in VALID_VARIANTS else "default"
    _set_dynamic(widget, "uiVariant", safe)
    return safe


def set_visual_state(widget: QWidget, state: str) -> str:
    """Aplica un estado visual conocido sin alterar el estado funcional."""
    safe = state if state in VALID_STATES else "default"
    _set_dynamic(widget, "uiState", safe)
    return safe


def set_surface(widget: QWidget, surface: str) -> str:
    """Asigna una superficie reutilizable y segura al widget."""
    safe = surface if surface in VALID_SURFACES else "default"
    _set_dynamic(widget, "uiSurface", safe)
    return safe
