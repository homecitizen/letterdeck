#!/usr/bin/env python3
"""Puente Apple Music (Windows 11) -> CYD por USB.

Lee lo que suena desde los controles multimedia de Windows (SMTC), dibuja la
interfaz con Pillow (render.py) y la manda a la CYD. Los toques de la CYD llegan
de vuelta y se convierten en play/pausa, anterior, siguiente, seek y volumen.
"""
import sys

sys.coinit_flags = 0  # COM en modo MTA: evita el choque entre winrt y comtypes/pycaw

import argparse
import asyncio
import os
import struct
import threading
import time
from datetime import datetime, timezone

import serial
import serial.tools.list_ports

import device
import render

try:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as SessionManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
    )
    from winrt.windows.storage.streams import Buffer, DataReader, InputStreamOptions
except ImportError as e:  # pragma: no cover
    sys.exit(f"Faltan paquetes de Windows ({e}). Ejecuta: pip install -r requirements.txt")

MAGIC = b"\xA5\x5A"
T_FRAME, T_PATCH, T_BRIGHT, T_CALIB = 1, 2, 3, 4
MAX_JPEG = 44_000
POLL = 0.4  # segundos entre lecturas de Windows

ORIENT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "orient.txt")

KNOWN_USB = {(0x1A86, 0x7523), (0x1A86, 0x55D4), (0x10C4, 0xEA60), (0x0403, 0x6001)}


def pkt(kind, payload=b""):
    return MAGIC + bytes([kind]) + struct.pack("<I", len(payload)) + payload


def load_orient():
    try:
        with open(ORIENT_FILE) as f:
            return int(f.read().strip()) % device.COUNT
    except (OSError, ValueError):
        return 0


def calibrate_only(args):
    """Manda la orden de calibrar y sale (sin arrancar el resto)."""
    import time as _t
    port = args.port or find_port()
    if not port:
        sys.exit("No encuentro la CYD (usa --port COM5)")
    ser = serial.Serial()
    ser.port, ser.baudrate = port, args.baud
    ser.dtr = ser.rts = False
    ser.open()
    _t.sleep(1.0)
    ser.write(pkt(T_CALIB))
    ser.flush()
    _t.sleep(0.3)
    ser.close()
    print("Calibracion lanzada: toca el centro de las 4 cruces que salen en la CYD (30 s por cruz).")


def find_port():
    ports = list(serial.tools.list_ports.comports())
    for p in ports:
        if (p.vid, p.pid) in KNOWN_USB:
            return p.device
    for p in ports:
        if any(s in (p.description or "").upper() for s in ("CH340", "CP210", "USB-SERIAL", "USB SERIAL")):
            return p.device
    return None


async def read_thumbnail(ref):
    """Caratula de SMTC -> bytes (PNG/JPEG)."""
    if ref is None:
        return None
    try:
        stream = await ref.open_read_async()
        size = int(stream.size)
        if size <= 0 or size > 12_000_000:
            return None
        try:
            reader = DataReader(stream.get_input_stream_at(0))
            await reader.load_async(size)
            buf = bytearray(size)
            reader.read_bytes(buf)
            return bytes(buf)
        except Exception:
            buf = Buffer(size)
            await stream.read_async(buf, size, InputStreamOptions.READ_AHEAD)
            return bytes(memoryview(buf))
    except Exception:
        return None


class MasterVolume:
    """Volumen general de Windows (Apple Music no expone el suyo por SMTC)."""

    def __init__(self):
        self.ep = None
        self.enabled = True
        self._connect()

    def _connect(self):
        try:
            from ctypes import POINTER, cast
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

            dev = AudioUtilities.GetSpeakers()
            if hasattr(dev, "EndpointVolume"):  # pycaw reciente
                self.ep = dev.EndpointVolume
            else:
                iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                self.ep = cast(iface, POINTER(IAudioEndpointVolume))
        except Exception as e:
            self.ep = None
            if self.enabled:
                print(f"[volumen] desactivado: {e}")
            self.enabled = False

    def get(self):
        if not self.enabled:
            return None
        try:
            return float(self.ep.GetMasterVolumeLevelScalar())
        except Exception:
            self._connect()  # cambio de dispositivo de salida
            return None

    def set(self, v):
        if not self.enabled:
            return
        try:
            self.ep.SetMasterVolumeLevelScalar(max(0.0, min(1.0, v)), None)
        except Exception:
            self._connect()


class App:
    def __init__(self, args):
        self.args = args
        self.orient = device.Orientation(args.orient if args.orient is not None else load_orient())
        self.ser = None
        self.queue = None
        self.need_full = True
        # SMTC
        self.mgr = None
        self.session = None
        self.pending = None
        self.pending_n = 0
        self.track_key = None
        self.art = None
        self.art_hash = None
        self.art_tries = 0
        self.prev_art_hash = None
        self.prev_album = None
        self.empty_n = 0
        # UI
        self.idle = True
        self.base = render.build_idle()
        self.playing = False
        self.dur = 0.0
        self.anchor_pos = 0.0
        self.anchor_t = time.monotonic()
        self.tl_sig = None
        self.vol = 0.5
        self.volume = MasterVolume()
        self.vol_user_t = 0.0
        self.vol_poll_t = 0.0
        self.sent = {}
        self.touch = None
        self.preview = None
        self.last_btn_t = 0.0

    # ------------------------------------------------------------ serie

    def connect(self):
        port = self.args.port or find_port()
        if not port:
            raise OSError("no encuentro la CYD (usa --port COM5)")
        ser = serial.Serial()
        ser.port, ser.baudrate = port, self.args.baud
        ser.dtr = ser.rts = False  # evita reiniciar la placa al abrir el puerto
        ser.timeout, ser.write_timeout = 0.2, 3
        ser.open()
        self.ser = ser
        self.queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        q = self.queue

        def reader():
            try:
                while ser.is_open:
                    line = ser.readline()
                    if line:
                        loop.call_soon_threadsafe(q.put_nowait, line)
            except Exception:
                pass
            loop.call_soon_threadsafe(q.put_nowait, None)

        threading.Thread(target=reader, daemon=True).start()
        print(f"Conectado a la CYD en {port}")

    def disconnect(self):
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None

    def send(self, data):
        if not self.ser:
            return
        try:
            self.ser.write(data)
        except (serial.SerialException, OSError):
            self.disconnect()

    def send_patch(self, box, img):
        x, y = self.orient.box(box)
        data = render.to_jpeg(self.orient.image(img), 92)
        self.send(pkt(T_PATCH, struct.pack("<HH", x, y) + data))

    def send_full(self):
        img = render.compose(self.base, self.cur_pos(), self.dur, self.playing, self.vol,
                             controls=not self.idle)
        self.send(pkt(T_FRAME, render.to_jpeg_fit(self.orient.image(img), MAX_JPEG)))
        self.sent = self.dyn_keys()
        self.need_full = False

    async def link_loop(self):
        while True:
            if self.ser is None:
                try:
                    self.connect()
                    await asyncio.sleep(1.5)  # arranque de la placa
                    if self.args.brightness is not None:
                        self.send(pkt(T_BRIGHT, bytes([self.args.brightness])))
                    self.need_full = True
                except OSError as e:
                    print(f"Esperando a la CYD... ({e})")
                    await asyncio.sleep(2)
                    continue
            line = await self.queue.get()
            if line is None:
                print("CYD desconectada")
                self.disconnect()
                continue
            self.handle_line(line.decode("utf-8", "ignore").strip())

    def handle_line(self, line):
        if line == "READY":
            self.need_full = True
        elif line.startswith("T "):
            try:
                _, x, y, st = line.split()
                ux, uy = self.orient.to_ui(int(x), int(y))
                self.on_touch(ux, uy, st)
            except ValueError:
                pass

    # ------------------------------------------------------------ Windows (SMTC)

    def pick_session(self):
        sessions = list(self.mgr.get_sessions())
        for token in self.args.app:
            for s in sessions:
                if token in (s.source_app_user_model_id or "").lower():
                    return s
        return self.mgr.get_current_session() if self.args.any_player else None

    def cur_pos(self):
        p = self.anchor_pos
        if self.playing:
            p += time.monotonic() - self.anchor_t
        if self.dur > 0:
            p = min(p, self.dur)
        return max(0.0, p)

    def go_idle(self):
        self.empty_n += 1
        if self.empty_n < 3 and not self.idle:  # evita parpadeos entre canciones
            return
        if self.idle and not self.need_full:
            return
        self.idle = True
        self.track_key = self.pending = None
        self.base = render.build_idle()
        self.send_full()

    async def refresh(self):
        s = self.pick_session()
        self.session = s
        if s is None:
            self.go_idle()
            return
        props = await s.try_get_media_properties_async()
        title, artist, album = props.title or "", props.artist or "", props.album_title or ""
        # Apple Music para Windows suele devolver "Artista — Album" en el campo artista
        if " — " in artist:
            artist, alb2 = artist.split(" — ", 1)
            album = album or alb2
        if not title and not artist:
            self.go_idle()
            return
        self.empty_n = 0

        key = (title, artist, album)
        if key != self.pending:  # esperar un ciclo a que los metadatos se estabilicen
            self.pending, self.pending_n = key, 0
        else:
            self.pending_n += 1
        new_track = False
        if self.pending_n >= 1 and key != self.track_key:
            self.prev_art_hash = self.art_hash
            self.prev_album = self.track_key[2] if self.track_key else None
            self.track_key, self.art, self.art_hash, self.art_tries = key, None, None, 0
            new_track = True

        art_changed = False
        if self.track_key == key and self.art is None and self.art_tries < 15:
            self.art_tries += 1
            data = await read_thumbnail(props.thumbnail)
            if data:
                h = hash(data)
                stale = h == self.prev_art_hash and album != self.prev_album and self.art_tries < 6
                if not stale:  # SMTC a veces tarda en cambiar la caratula
                    self.art, self.art_hash, art_changed = data, h, True

        # estado de reproduccion y posicion
        self.playing = s.get_playback_info().playback_status == PlaybackStatus.PLAYING
        tl = s.get_timeline_properties()
        start = tl.start_time.total_seconds()
        self.dur = max(0.0, tl.end_time.total_seconds() - start)
        rp = tl.position.total_seconds() - start
        sig = (rp, tl.last_updated_time, self.playing, self.dur)
        if sig != self.tl_sig or new_track:
            elapsed = 0.0
            try:
                lu = tl.last_updated_time
                if lu.tzinfo is None:
                    lu = lu.replace(tzinfo=timezone.utc)
                e = (datetime.now(timezone.utc) - lu).total_seconds()
                if 0 <= e <= self.dur + 60:
                    elapsed = e
            except Exception:
                pass
            self.anchor_pos = rp + (elapsed if self.playing else 0.0)
            self.anchor_t = time.monotonic()
            self.tl_sig = sig

        if self.track_key == key and (new_track or art_changed or self.idle):
            self.idle = False
            self.base = render.build_base(title, artist, album, self.art)
            self.send_full()

    # ------------------------------------------------------------ interfaz dinamica

    def dyn_keys(self):
        pos = self.preview if self.preview is not None else self.cur_pos()
        return {"prog": (int(pos), int(self.dur)), "btn": self.playing, "vol": round(self.vol * 100)}

    def update_dynamic(self):
        if self.idle or not self.ser:
            return
        pos = self.preview if self.preview is not None else self.cur_pos()
        for name, key in self.dyn_keys().items():
            if self.sent.get(name) == key:
                continue
            self.sent[name] = key
            if name == "prog":
                self.send_patch(render.PROG_BOX, render.render_progress(self.base, pos, self.dur))
            elif name == "btn":
                self.send_patch(render.BTN_BOX, render.render_buttons(self.base, self.playing))
            else:
                self.send_patch(render.VOL_BOX, render.render_volume(self.base, self.vol))

    def sync_volume(self):
        now = time.monotonic()
        if now - self.vol_poll_t < 1.0 or self.touch == "vol" or now - self.vol_user_t < 1.5:
            return
        self.vol_poll_t = now
        v = self.volume.get()
        if v is not None:
            self.vol = v

    async def poll_loop(self):
        while True:
            if self.ser is not None:
                try:
                    if self.need_full:
                        self.send_full()
                    await self.refresh()
                    self.sync_volume()
                    self.update_dynamic()
                except (serial.SerialException, OSError):
                    self.disconnect()
                except Exception as e:  # un fallo de SMTC no debe tumbar el programa
                    print(f"[aviso] {type(e).__name__}: {e}")
            await asyncio.sleep(POLL)

    # ------------------------------------------------------------ toques

    def set_volume_x(self, x):
        self.vol = render.frac_from_x(x, render.VOL_X0, render.VOL_X1)
        self.vol_user_t = time.monotonic()
        self.volume.set(self.vol)
        self.update_dynamic()

    def on_touch(self, x, y, st):
        if self.idle:
            return
        if st == "D":
            self.touch = render.hit_test(x, y)
            if self.touch == "vol":
                self.set_volume_x(x)
            elif self.touch == "seek" and self.dur > 0:
                self.preview = render.frac_from_x(x, render.BAR_X0, render.BAR_X1) * self.dur
                self.update_dynamic()
        elif st == "M":
            if self.touch == "vol":
                self.set_volume_x(x)
            elif self.touch == "seek" and self.dur > 0:
                self.preview = render.frac_from_x(x, render.BAR_X0, render.BAR_X1) * self.dur
                self.update_dynamic()
        elif st == "U":
            t, self.touch = self.touch, None
            if t == "seek" and self.preview is not None:
                target, self.preview = self.preview, None
                asyncio.ensure_future(self.do("seek", target))
            elif t in ("prev", "play", "next") and render.hit_test(x, y) == t:
                now = time.monotonic()
                if now - self.last_btn_t > 0.25:
                    self.last_btn_t = now
                    asyncio.ensure_future(self.do(t))
            elif t == "vol":
                self.vol_user_t = time.monotonic()

    async def do(self, action, arg=None):
        s = self.session
        if s is None:
            return
        try:
            if action == "play":
                self.anchor_pos, self.anchor_t = self.cur_pos(), time.monotonic()
                self.playing = not self.playing  # respuesta inmediata en pantalla
                self.update_dynamic()
                await s.try_toggle_play_pause_async()
            elif action == "next":
                await s.try_skip_next_async()
            elif action == "prev":
                await s.try_skip_previous_async()
            elif action == "seek":
                self.anchor_pos, self.anchor_t = arg, time.monotonic()
                self.update_dynamic()
                await s.try_change_playback_position_async(int(arg * 10_000_000))
        except Exception as e:
            print(f"[aviso] {action}: {e}")

    # ------------------------------------------------------------ prueba de orientacion

    async def orient_test(self):
        count = device.COUNT if self.args.mirrors else 2   # 0 y 1 son giros; 2 y 3 son espejos
        print(f"Mostrando {count} orientaciones, una cada 5 s. Sujeta la placa como la quieres usar y apunta")
        print("el numero de la que se lea bien (derecha y sin espejo). Ctrl+C para salir.")
        while True:
            if self.ser is None:
                try:
                    self.connect()
                    await asyncio.sleep(1.5)
                except OSError as e:
                    print(f"Esperando a la CYD... ({e})")
                    await asyncio.sleep(2)
                    continue
            for n in range(count):
                img = render.build_orient_test(n)
                data = render.to_jpeg_fit(device.Orientation(n).image(img), MAX_JPEG)
                self.send(pkt(T_FRAME, data))
                print(f"  -> orientacion {n}")
                await asyncio.sleep(5)

    # ------------------------------------------------------------ main

    async def run(self):
        self.mgr = await SessionManager.request_async()
        await asyncio.gather(self.link_loop(), self.poll_loop())


async def check(args):
    """Prueba el lado Windows sin CYD: lista apps, lee la cancion, guarda la portada y el fotograma."""
    from PIL import Image
    import io

    mgr = await SessionManager.request_async()
    sessions = list(mgr.get_sessions())
    print(f"Sesiones multimedia abiertas: {len(sessions)}")
    for s in sessions:
        print("  -", s.source_app_user_model_id)
    app = App(args)
    app.mgr = mgr
    s = app.pick_session()
    if s is None:
        print("\nNo veo Apple Music. Abre la app Apple Music de Windows y dale a play.")
        print("(Si usas otro reproductor, prueba con --any-player)")
        return
    print("\nUsando:", s.source_app_user_model_id)
    props = await s.try_get_media_properties_async()
    print("Titulo :", props.title)
    print("Artista:", props.artist)
    print("Album  :", props.album_title)
    tl = s.get_timeline_properties()
    print("Duracion:", int(tl.end_time.total_seconds()), "s | posicion:", int(tl.position.total_seconds()), "s")
    data = None
    for i in range(6):
        data = await read_thumbnail(props.thumbnail)
        if data:
            break
        print(f"Portada: aun no disponible (intento {i + 1}/6)...")
        await asyncio.sleep(1)
        props = await s.try_get_media_properties_async()
    if data:
        img = Image.open(io.BytesIO(data))
        print(f"Portada: OK ({img.width}x{img.height}, {len(data) // 1024} KB) -> cover_test.png")
        img.convert("RGB").save("cover_test.png")
    else:
        print("Portada: Apple Music no la ha entregado (se vera un icono de nota en su lugar)")
    artist, album = props.artist or "", props.album_title or ""
    if " — " in artist:
        artist, alb2 = artist.split(" — ", 1)
        album = album or alb2
    base = render.build_base(props.title or "", artist, album, data)
    frame = render.compose(base, tl.position.total_seconds(), (tl.end_time - tl.start_time).total_seconds(), True, 0.5)
    frame.convert("RGB").resize((640, 480), Image.Resampling.LANCZOS).save("check.png")
    print("Fotograma que veria la CYD -> check.png")


def main():
    ap = argparse.ArgumentParser(description="Apple Music -> CYD")
    ap.add_argument("--port", help="Puerto serie (p. ej. COM5). Por defecto se autodetecta")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--app", nargs="+", default=["apple", "itunes"],
                    help="Texto a buscar en el ID de la app multimedia (por defecto: apple itunes)")
    ap.add_argument("--any-player", action="store_true",
                    help="Si Apple Music no esta abierto, mostrar cualquier otro reproductor")
    ap.add_argument("--brightness", type=int, help="Brillo 0-255")
    ap.add_argument("--calibrate", action="store_true", help="Recalibrar la pantalla tactil y salir")
    ap.add_argument("--list-ports", action="store_true")
    ap.add_argument("--orient", type=int, choices=range(device.COUNT),
                    help="Orientacion de la pantalla (0-3). Se recuerda para la proxima vez. Usa --test para elegirla")
    ap.add_argument("--test", action="store_true", help="Recorrer las orientaciones para elegir la correcta")
    ap.add_argument("--mirrors", action="store_true", help="Con --test, incluir tambien las 2 orientaciones en espejo (2 y 3)")
    ap.add_argument("--check", action="store_true", help="Probar la lectura de Apple Music sin CYD")
    args = ap.parse_args()
    args.app = [a.lower() for a in args.app]

    if args.list_ports:
        for p in serial.tools.list_ports.comports():
            print(p.device, "-", p.description, f"[{p.vid}:{p.pid}]" if p.vid else "")
        return
    if args.orient is not None:
        with open(ORIENT_FILE, "w") as f:
            f.write(str(args.orient))
        print(f"Orientacion {args.orient} guardada")
    if args.calibrate:
        calibrate_only(args)
        return
    if args.check:
        asyncio.run(check(args))
        return
    if args.test:
        try:
            asyncio.run(App(args).orient_test())
        except KeyboardInterrupt:
            pass
        return
    try:
        asyncio.run(App(args).run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
