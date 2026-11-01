"""Orientacion de la interfaz respecto a la pantalla de la CYD (ambas 320x240, horizontales).

0 = normal, 1 = girada 180 grados, 2 = espejo horizontal, 3 = espejo vertical.
`python nowplaying.py --test` muestra 0 y 1 (con --mirrors tambien 2 y 3) para elegir.
Las imagenes salen giradas hacia la CYD y los toques entran con el giro inverso.
"""
from PIL import Image

W, H = 320, 240
DEV_W, DEV_H = 320, 240

T = Image.Transpose
# (operacion PIL o None, interfaz->pantalla, pantalla->interfaz)
_ORIENTS = [
    (None,              lambda x, y: (x, y),                 lambda u, v: (u, v)),
    (T.ROTATE_180,      lambda x, y: (W - 1 - x, H - 1 - y), lambda u, v: (W - 1 - u, H - 1 - v)),
    (T.FLIP_LEFT_RIGHT, lambda x, y: (W - 1 - x, y),         lambda u, v: (W - 1 - u, v)),
    (T.FLIP_TOP_BOTTOM, lambda x, y: (x, H - 1 - y),         lambda u, v: (u, H - 1 - v)),
]
COUNT = len(_ORIENTS)


class Orientation:
    def __init__(self, index=0):
        self.index = index % COUNT
        self.op, self._fwd, self._inv = _ORIENTS[self.index]

    def image(self, img):
        """Imagen de la interfaz (o de un parche) -> imagen para enviar a la CYD."""
        return img.copy() if self.op is None else img.transpose(self.op)

    def box(self, box):
        """Caja (x0, y0, x1, y1) de la interfaz -> posicion (x, y) del parche ya girado."""
        x0, y0, x1, y1 = box
        a = self._fwd(x0, y0)
        b = self._fwd(x1 - 1, y1 - 1)
        return min(a[0], b[0]), min(a[1], b[1])

    def to_ui(self, u, v):
        """Toque en la pantalla de la CYD -> coordenadas de la interfaz."""
        x, y = self._inv(u, v)
        return max(0, min(W - 1, x)), max(0, min(H - 1, y))
