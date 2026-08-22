"""
TDT & Radio VIP - Versión FREE COMPLETA
Coder By X@R
Arranca directamente sin pedir código de activación.
Todas las funciones desbloqueadas.
"""
# Ver core/bootstrap.py — mismo fix que main.py, id distinto para que
# Windows no mezcle esta build Free con la que tiene licencia en la barra
# de tareas si están las dos instaladas a la vez.
from core.bootstrap import bootstrap

bootstrap("CoderByXR.TDTRadioVIP.Free")

from ui.application import run_free


def main():
    return run_free()


if __name__ == "__main__":
    raise SystemExit(main())
