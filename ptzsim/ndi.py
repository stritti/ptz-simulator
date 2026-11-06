# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""NDI PTZ camera: an NDI source with PTZ support and a rendered test picture.

NDI receivers send PTZ commands as XML metadata (``<ntk_ptz_pan_tilt .../>`` and
friends) back to the sender. :class:`NdiPtzController` turns those into camera
moves; it is plain Python. :class:`NdiSource` needs the NDI runtime via the
``ndi-python`` package (``pip install ndi-python numpy``).

Value ranges follow the NDI SDK (Processing.NDI.Recv.ex.h):
  pan  -1 (left) .. +1 (right)      pan_speed  -1 (moving right) .. +1 (moving left)
  tilt -1 (bottom) .. +1 (top)      tilt_speed -1 (down) .. +1 (up)
  zoom  0 (zoomed in) .. 1 (out)    zoom_speed -1 (outwards) .. +1 (inwards)
  focus 0 (infinity) .. 1 (close)   presets 0 .. 99, recall speed 0 .. 1
"""

from __future__ import annotations

import asyncio
import logging
import socket
import threading
import xml.etree.ElementTree as ET
from typing import Callable, Optional

from . import scenery
from . import state as st
from .onvif import tilt_from_onvif
from .visca import ViscaCamera

log = logging.getLogger("ptzsim")

# Connection metadata a sender sends so receivers report PTZ support.
CAPABILITIES = ('<ndi_capabilities ntk_ptz="true" ntk_pan_tilt="true" ntk_zoom="true" '
                'ntk_focus="true" ntk_autofocus="true" ntk_white_balance="true" '
                'ntk_preset_speed="true"/>')
PRESET_RANGE = range(0, 100)  # NDI SDK: "The preset number is in the range 0 to 99"


class NdiPtzController:
    """Applies NDI PTZ metadata messages to the simulated camera."""

    def __init__(self, camera: ViscaCamera):
        self.camera = camera

    @property
    def state(self) -> st.CameraState:
        return self.camera.state

    def handle(self, xml: str) -> bool:
        """Handle one metadata frame. Returns False if it was not understood."""
        try:
            elem = ET.fromstring(xml)
        except ET.ParseError:
            self.camera.record("NDI", f"invalid metadata {xml[:40]!r}", ok=False)
            return False
        handler = getattr(self, "_" + elem.tag, None)
        if handler is None or not elem.tag.startswith("ntk_ptz"):
            self.camera.record("NDI", f"unsupported metadata <{elem.tag}>", ok=False)
            return False
        try:
            description = handler(elem.attrib)
        except (KeyError, ValueError) as err:
            self.camera.record("NDI", f"<{elem.tag}> bad attribute: {err}", ok=False)
            return False
        if self.camera.instant:
            self.state.finish_moves()
        self.camera.record("NDI", description)
        return True

    @staticmethod
    def _num(attrs, name: str, low: float, high: float) -> float:
        return st.clamp(float(attrs[name]), low, high)

    # ------------------------------------------------------------ pan/tilt
    def _ntk_ptz_pan_tilt(self, a) -> str:
        pan, tilt = self._num(a, "pan", -1, 1), self._num(a, "tilt", -1, 1)
        self.state.move_pan_tilt_to(pan * st.PAN_MAX, tilt_from_onvif(tilt),
                                    st.PAN_SPEED_MAX, st.TILT_SPEED_MAX)
        return f"pan/tilt to {pan:+.2f} {tilt:+.2f}"

    def _ntk_ptz_pan_tilt_speed(self, a) -> str:
        pan, tilt = self._num(a, "pan_speed", -1, 1), self._num(a, "tilt_speed", -1, 1)
        s = self.state
        s.pan_target = s.tilt_target = None
        # NDI: positive pan speed moves left, i.e. towards negative pan.
        s.pan_velocity = -pan * st.PAN_SPEED_MAX * st.PAN_TILT_UNITS_PER_SPEED_STEP
        s.tilt_velocity = tilt * st.TILT_SPEED_MAX * st.PAN_TILT_UNITS_PER_SPEED_STEP
        return "pan/tilt stop" if pan == tilt == 0 else f"pan/tilt speed {pan:+.2f} {tilt:+.2f}"

    # ---------------------------------------------------------------- zoom
    def _ntk_ptz_zoom(self, a) -> str:
        zoom = self._num(a, "zoom", 0, 1)
        self.state.zoom_to(st.ZOOM_MIN + (1 - zoom) * (st.ZOOM_MAX - st.ZOOM_MIN))
        return f"zoom to {zoom:.2f}"

    def _ntk_ptz_zoom_speed(self, a) -> str:
        speed = self._num(a, "zoom_speed", -1, 1)
        self.state.zoom_target = None
        self.state.zoom_velocity = speed * 8 * st.ZOOM_UNITS_PER_SPEED_STEP
        return "zoom stop" if speed == 0 else f"zoom speed {speed:+.2f}"

    # --------------------------------------------------------------- focus
    def _ntk_ptz_focus(self, a) -> str:
        if a.get("mode") == "auto":
            self.state.autofocus = True
            return "auto focus"
        distance = self._num(a, "distance", 0, 1)
        self.state.autofocus = False
        self.state.focus_to(st.FOCUS_MIN + distance * (st.FOCUS_MAX - st.FOCUS_MIN))
        return f"focus to {distance:.2f}"

    def _ntk_ptz_focus_speed(self, a) -> str:
        speed = self._num(a, "distance", -1, 1)
        self.state.autofocus = False
        self.state.focus_target = None
        self.state.focus_velocity = speed * 8 * st.FOCUS_UNITS_PER_SPEED_STEP
        return "focus stop" if speed == 0 else f"focus speed {speed:+.2f}"

    # ------------------------------------------------------------- presets
    def _preset(self, a) -> int:
        number = int(a["index"])
        if number not in PRESET_RANGE:
            raise ValueError(f"preset {number} out of the NDI range 0..99")
        if number >= st.PRESET_COUNT:
            raise ValueError(f"preset {number}: the camera has {st.PRESET_COUNT} presets")
        return number

    def _ntk_ptz_store_preset(self, a) -> str:
        number = self._preset(a)
        self.state.save_preset(number)
        return f"store preset {number}"

    def _ntk_ptz_recall_preset(self, a) -> str:
        number = self._preset(a)
        speed = self._num(a, "speed", 0, 1) if "speed" in a else 1.0
        if not self.state.recall_preset(number, speed):
            raise ValueError(f"preset {number} not set")
        return f"recall preset {number} (speed {speed:.2f})"

    # ------------------------------------------- accepted but not simulated
    def _ignored(self, name: str, a) -> str:
        detail = " ".join(f"{k}={v}" for k, v in a.items())
        return f"{name} {detail} (not simulated)".replace("  ", " ")

    def _ntk_ptz_white_balance(self, a) -> str:
        mode = a.get("mode")
        if mode in ("auto", "indoor", "outdoor"):
            self.state.set_white_balance(mode)
            return f"white balance {mode}"
        if mode == "one_shot":
            self.state.one_push_white_balance()
            return "white balance one shot"
        if mode == "manual":
            red, blue = self._num(a, "red", 0, 1), self._num(a, "blue", 0, 1)
            self.state.set_white_balance("manual")
            self.state.set_gains(round(red * 256), round(blue * 256))  # NDI 0.5 is neutral (0x80)
            return f"white balance manual red {red:.2f} blue {blue:.2f}"
        return self._ignored("white balance", a)

    def _ntk_ptz_exposure(self, a) -> str:
        return self._ignored("exposure", a)

    def _ntk_ptz_iris(self, a) -> str:
        return self._ignored("iris", a)

    def _ntk_ptz_flip(self, a) -> str:
        return self._ignored("flip", a)


# ---------------------------------------------------------------- picture
# 3x5 pixel font for text on landmarks (signs, banner); other characters become a dot.
FONT = {ch: rows.split() for ch, rows in {
    "A": "010 101 111 101 101", "B": "110 101 110 101 110", "C": "011 100 100 100 011",
    "D": "110 101 101 101 110", "E": "111 100 110 100 111", "F": "111 100 110 100 100",
    "G": "011 100 101 101 011", "H": "101 101 111 101 101", "I": "111 010 010 010 111",
    "J": "001 001 001 101 010", "K": "101 101 110 101 101", "L": "100 100 100 100 111",
    "M": "101 111 111 101 101", "N": "110 101 101 101 101", "O": "010 101 101 101 010",
    "P": "110 101 110 100 100", "Q": "010 101 101 110 011", "R": "110 101 110 101 101",
    "S": "011 100 010 001 110", "T": "111 010 010 010 010", "U": "101 101 101 101 111",
    "V": "101 101 101 101 010", "W": "101 101 111 111 101", "X": "101 101 010 101 101",
    "Y": "101 101 010 010 010", "Z": "111 001 010 100 111",
    "0": "111 101 101 101 111", "1": "010 110 010 010 111", "2": "110 001 010 100 111",
    "3": "110 001 010 001 110", "4": "101 101 111 001 001", "5": "111 100 110 001 110",
    "6": "011 100 111 101 111", "7": "111 001 010 010 010", "8": "111 101 111 101 111",
    "9": "111 101 111 001 110", "!": "010 010 010 000 010", ",": "000 000 000 010 100",
    ".": "000 000 000 000 010", ":": "000 010 000 010 000", "<": "001 010 100 010 001",
    ">": "100 010 001 010 100", "/": "001 001 010 100 100", "\\": "100 100 010 001 001",
    "(": "010 100 100 100 010", ")": "010 001 001 001 010", "|": "010 010 010 010 010",
    "'": "010 010 000 000 000", "`": "100 010 000 000 000", "?": "110 001 010 000 010",
}.items()}
SUB_X, SUB_Y = 4, 8  # sub-pixels per art character (square: art cells are 1:2)


def _landmark_bitmap(lm: scenery.Landmark):
    """Colours (BGR) and coverage mask of a landmark at SUB_X x SUB_Y per character."""
    import numpy as np

    rgb = np.zeros((lm.rows * SUB_Y, lm.cols * SUB_X, 3), dtype=np.uint8)
    mask = np.zeros(rgb.shape[:2], dtype=bool)
    for row in range(lm.rows):
        for col in range(lm.cols):
            ch = lm.char(row, col)
            if ch is None:
                continue
            block = np.zeros((SUB_Y, SUB_X), dtype=bool)
            if ch in scenery.SOLID:
                block[:] = True
            elif ch in scenery.H_LINES:
                block[{"_": slice(6, 8), "=": slice(2, 6)}.get(ch, slice(3, 5))] = True
            elif ch in scenery.V_LINES:
                block[:, 1:3] = True
            elif ch in scenery.CORNERS:
                arms = scenery.CORNERS[ch]
                block[3:5, 1:3] = True
                if "r" in arms:
                    block[3:5, 2:] = True
                if "l" in arms:
                    block[3:5, :2] = True
                if "d" in arms:
                    block[4:, 1:3] = True
                if "u" in arms:
                    block[:4, 1:3] = True
            else:  # text: a glyph on the sign's board
                if lm.fill is not None:
                    sub = rgb[row * SUB_Y:(row + 1) * SUB_Y, col * SUB_X:(col + 1) * SUB_X]
                    sub[:] = lm.fill.bgr
                    mask[row * SUB_Y:(row + 1) * SUB_Y, col * SUB_X:(col + 1) * SUB_X] = True
                glyph = FONT.get(ch.upper())
                if glyph is None:
                    block[3:6, 1:3] = True
                else:
                    block[1:6, 0:3] = np.array([[bit == "1" for bit in line] for line in glyph])
            ys, xs = np.nonzero(block)
            rgb[row * SUB_Y + ys, col * SUB_X + xs] = lm.paint(ch).bgr
            mask[row * SUB_Y + ys, col * SUB_X + xs] = True
    return rgb, mask


class SceneRenderer:
    """Draws what the camera "sees": a panorama grid that follows pan/tilt/zoom, with the
    landmarks of ``scenery`` at fixed positions (same scene as the text viewfinder)."""

    BASE_FOV = 60.0  # horizontal field of view at 1x, degrees

    def __init__(self, width: int = 640, height: int = 360):
        import numpy as np

        self.np = np
        self.width, self.height = width, height
        self.u = (np.arange(width, dtype=np.float32) / width - 0.5)[None, :]
        self.v = (np.arange(height, dtype=np.float32) / height - 0.5)[:, None]
        self.landmarks = [(lm,) + _landmark_bitmap(lm) for lm in scenery.LANDMARKS]

    def _draw_landmarks(self, frame, az, el, fov: float, s: st.CameraState) -> None:
        np = self.np
        half_h = fov * self.height / self.width / 2
        for lm, rgb, mask in self.landmarks:
            if not lm.overlaps(s.pan_degrees - fov / 2, s.pan_degrees + fov / 2,
                               s.tilt_degrees - half_h, s.tilt_degrees + half_h):
                continue
            sub_w = lm.px / SUB_X
            sub_h = lm.px * scenery.ART_ASPECT / SUB_Y
            # Pan depends only on the column and tilt only on the row of the frame.
            cols = np.floor((lm.offset(az[0]) + lm.width / 2) / sub_w).astype(np.int64)
            rows = np.floor((lm.top - el[:, 0]) / sub_h).astype(np.int64)
            xs = np.nonzero((cols >= 0) & (cols < mask.shape[1]))[0]
            ys = np.nonzero((rows >= 0) & (rows < mask.shape[0]))[0]
            if not len(xs) or not len(ys):
                continue
            grid = np.ix_(rows[ys], cols[xs])
            hit = mask[grid]
            # xs need not be contiguous: a very wide view can see a landmark twice.
            target = np.ix_(ys, xs)
            region = frame[target]
            region[hit, :3] = rgb[grid][hit]
            frame[target] = region

    def render(self, s: st.CameraState):
        np = self.np
        fov = self.BASE_FOV / s.zoom_ratio
        az = s.pan_degrees + self.u * fov
        el = s.tilt_degrees - self.v * fov * self.height / self.width
        checker = ((np.floor(az / 5) + np.floor(el / 5)) % 2).astype(np.float32)
        sky = el > 0
        frame = np.empty((self.height, self.width, 4), dtype=np.uint8)
        # BGRX: sky blue-ish, ground green-ish, checker pattern every 5 degrees.
        frame[..., 0] = np.where(sky, 150 + 60 * checker, 40 + 30 * checker)
        frame[..., 1] = np.where(sky, 90 + 40 * checker, 110 + 50 * checker)
        frame[..., 2] = np.where(sky, 40 + 20 * checker, 50 + 30 * checker)
        frame[..., 3] = 255
        line = fov / self.width * 1.5
        # Fine 1-degree grid once zoomed in far enough to see it.
        if fov / self.width < 1 / 16:
            fine = (np.abs(((az + 0.5) % 1) - 0.5) < line / 2) | (np.abs(((el + 0.5) % 1) - 0.5) < line / 2)
            frame[np.broadcast_to(fine, frame.shape[:2]), :3] //= 2
        # Landmarks: red posts every 45 degrees of pan, white horizon.
        post = np.abs(((az + 22.5) % 45) - 22.5) < line * 2
        frame[np.broadcast_to(post, frame.shape[:2])] = (40, 40, 220, 255)
        frame[np.broadcast_to(np.abs(el) < line, frame.shape[:2])] = (255, 255, 255, 255)
        self._draw_landmarks(frame, az, el, fov, s)
        # Centre crosshair.
        cx, cy = self.width // 2, self.height // 2
        frame[cy, cx - 12:cx + 13] = (0, 255, 255, 255)
        frame[cy - 12:cy + 13, cx] = (0, 255, 255, 255)
        return frame


# ------------------------------------------------------------- NDI source
class NdiSource:
    """Publishes the camera as an NDI source and executes received PTZ commands."""

    def __init__(self, camera: ViscaCamera, name: str, fps: int = 25,
                 width: int = 640, height: int = 360):
        try:
            import NDIlib  # noqa: F401  (ndi-python)
        except ImportError as err:
            raise RuntimeError("NDI needs the ndi-python package: pip install ndi-python numpy") from err
        self.camera = camera
        self.name = name
        self.fps = fps
        self.renderer = SceneRenderer(width, height)
        self.controller = NdiPtzController(camera)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.source_name: Optional[str] = None

    def start(self, dispatch: Callable[[Callable[[], None]], None]) -> None:
        """Start the sender thread. PTZ commands are handed to ``dispatch`` so
        they run on the simulator's event loop."""
        import NDIlib as ndi

        if not ndi.initialize():
            raise RuntimeError("NDI runtime could not be initialised (CPU not supported?)")
        settings = ndi.SendCreate(self.name, clock_video=True, clock_audio=False)
        sender = ndi.send_create(settings)
        if sender is None:
            raise RuntimeError("could not create NDI sender")
        caps = ndi.MetadataFrame()
        caps.data = CAPABILITIES
        ndi.send_add_connection_metadata(sender, caps)
        try:
            self.source_name = ndi.send_get_source_name(sender).ndi_name
        except TypeError:  # some ndi-python builds cannot convert the return value
            self.source_name = f"{socket.gethostname().split('.')[0].upper()} ({self.name})"
        self._thread = threading.Thread(target=self._run, args=(ndi, sender, dispatch),
                                        name="ndi-sender", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _run(self, ndi, sender, dispatch) -> None:
        frame = ndi.VideoFrameV2()
        frame.FourCC = ndi.FOURCC_VIDEO_TYPE_BGRX
        frame.frame_rate_N, frame.frame_rate_D = self.fps, 1
        try:
            while not self._stop.is_set():
                frame.data = self.renderer.render(self.camera.state)
                ndi.send_send_video_v2(sender, frame)  # blocks to the frame rate
                while True:
                    metadata = ndi.MetadataFrame()
                    ndi.send_capture(sender, metadata, 0)
                    if not metadata.data:
                        break
                    xml = metadata.data
                    ndi.send_free_metadata(sender, metadata)
                    log.debug("NDI metadata %s", xml)
                    dispatch(lambda xml=xml: self.controller.handle(xml))
        finally:
            ndi.send_destroy(sender)


def start_ndi(camera: ViscaCamera, name: str, fps: int = 25) -> NdiSource:
    loop = asyncio.get_running_loop()
    source = NdiSource(camera, name, fps)
    source.start(loop.call_soon_threadsafe)
    return source
