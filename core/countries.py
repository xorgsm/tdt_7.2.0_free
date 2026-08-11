"""
Lista de países soportados para canales de TV (iptv-org) y emisoras de
radio (Radio-Browser).

Ambas fuentes aceptan el mismo código ISO 3166-1 alfa-2 en minúsculas:
- iptv-org: https://iptv-org.github.io/iptv/countries/{code}.m3u
- Radio-Browser: /json/stations/bycountrycodeexact/{CODE}

Así que un único código por país sirve para las dos, sin tener que mantener
dos listas distintas ni traducir nombres de un formato a otro.

Coder By X@R
"""
from typing import List, Tuple

# (código ISO 3166-1 alfa-2, nombre en español)
# No es la lista completa de países del mundo: es una selección amplia de
# los que de verdad tienen listas de canales o emisoras activas y con
# contenido en sus fuentes públicas. Añadir uno nuevo es una línea más aquí,
# no hace falta tocar nada más.
COUNTRIES: List[Tuple[str, str]] = [
    ("DE", "Alemania"),
    ("AD", "Andorra"),
    ("AR", "Argentina"),
    ("AT", "Austria"),
    ("AU", "Australia"),
    ("BE", "Bélgica"),
    ("BO", "Bolivia"),
    ("BR", "Brasil"),
    ("CA", "Canadá"),
    ("CL", "Chile"),
    ("CO", "Colombia"),
    ("KR", "Corea del Sur"),
    ("CR", "Costa Rica"),
    ("CU", "Cuba"),
    ("DK", "Dinamarca"),
    ("EC", "Ecuador"),
    ("EG", "Egipto"),
    ("SV", "El Salvador"),
    ("AE", "Emiratos Árabes Unidos"),
    ("ES", "España"),
    ("US", "Estados Unidos"),
    ("FI", "Finlandia"),
    ("FR", "Francia"),
    ("GR", "Grecia"),
    ("GT", "Guatemala"),
    ("NL", "Países Bajos"),
    ("HN", "Honduras"),
    ("HU", "Hungría"),
    ("IN", "India"),
    ("IE", "Irlanda"),
    ("IT", "Italia"),
    ("JP", "Japón"),
    ("MA", "Marruecos"),
    ("MX", "México"),
    ("NI", "Nicaragua"),
    ("NO", "Noruega"),
    ("NZ", "Nueva Zelanda"),
    ("PA", "Panamá"),
    ("PY", "Paraguay"),
    ("PE", "Perú"),
    ("PL", "Polonia"),
    ("PT", "Portugal"),
    ("GB", "Reino Unido"),
    ("CZ", "República Checa"),
    ("DO", "República Dominicana"),
    ("RO", "Rumanía"),
    ("RU", "Rusia"),
    ("SA", "Arabia Saudí"),
    ("SE", "Suecia"),
    ("CH", "Suiza"),
    ("TN", "Túnez"),
    ("TR", "Turquía"),
    ("UA", "Ucrania"),
    ("UY", "Uruguay"),
    ("VE", "Venezuela"),
    ("ZA", "Sudáfrica"),
]

# Orden alfabético por nombre visible en el desplegable.
COUNTRIES.sort(key=lambda item: item[1])

DEFAULT_COUNTRY = "ES"

_BY_CODE = {code: name for code, name in COUNTRIES}


def country_name(code: str) -> str:
    """Nombre en español de un código, o el propio código si no está en la lista."""
    return _BY_CODE.get((code or "").upper(), code or DEFAULT_COUNTRY)


def is_known(code: str) -> bool:
    return (code or "").upper() in _BY_CODE
