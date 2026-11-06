# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""NDI PTZ commands (metadata XML) and, if ndi-python is installed, a real NDI round trip."""

import asyncio
import sys
import time

import pytest

from ptzsim import state as st
from ptzsim.ndi import NdiPtzController
from ptzsim.visca import ViscaCamera


@pytest.fixture
def ndi():
    return NdiPtzController(ViscaCamera(instant=True))


def test_absolute_pan_tilt(ndi):
    # XML exactly as NDIlib_recv_ptz_pan_tilt(-0.3, 0.4) sends it.
    assert ndi.handle('<ntk_ptz_pan_tilt pan="-0.300000" tilt="0.400000"/>')
    pan, tilt, _, _ = ndi.state.position()
    assert pan == round(-0.3 * st.PAN_MAX) and tilt == round(0.4 * st.TILT_MAX)


def test_pan_speed_positive_moves_left():
    ndi = NdiPtzController(ViscaCamera())
    ndi.handle('<ntk_ptz_pan_tilt_speed pan_speed="0.500000" tilt_speed="-0.250000"/>')
    ndi.state.tick(0.5)
    assert ndi.state.pan < 0 and ndi.state.tilt < 0
    ndi.handle('<ntk_ptz_pan_tilt_speed pan_speed="0.000000" tilt_speed="0.000000"/>')
    assert ndi.state.pan_velocity == ndi.state.tilt_velocity == 0
    assert ndi.camera.log[-1].description == "pan/tilt stop"


def test_white_balance_modes(ndi):
    ndi.handle('<ntk_ptz_white_balance mode="manual" red="0.25" blue="0.75"/>')
    assert ndi.state.white_balance == "manual" and (ndi.state.red_gain, ndi.state.blue_gain) == (64, 192)
    ndi.handle('<ntk_ptz_white_balance mode="indoor"/>')
    assert ndi.state.white_balance == "indoor"
    ndi.handle('<ntk_ptz_white_balance mode="auto"/>')
    assert ndi.state.white_balance == "auto"
    ndi.handle('<ntk_ptz_white_balance mode="one_shot"/>')
    assert ndi.state.white_balance == "manual" and (ndi.state.red_gain, ndi.state.blue_gain) == (0x80, 0x80)
    assert ndi.camera.log[-1].description == "white balance one shot"


def test_zoom_absolute_is_inverted(ndi):
    ndi.handle('<ntk_ptz_zoom zoom="0.000000"/>')
    assert ndi.state.zoom == st.ZOOM_MAX  # 0.0 = zoomed in
    ndi.handle('<ntk_ptz_zoom zoom="1.000000"/>')
    assert ndi.state.zoom == st.ZOOM_MIN


def test_zoom_speed_positive_zooms_in():
    ndi = NdiPtzController(ViscaCamera())
    ndi.handle('<ntk_ptz_zoom_speed zoom_speed="1.000000"/>')
    ndi.state.tick(0.5)
    assert ndi.state.zoom > 0


def test_focus(ndi):
    ndi.handle('<ntk_ptz_focus mode="manual" distance="0.500000"/>')
    assert not ndi.state.autofocus
    assert ndi.state.focus == pytest.approx((st.FOCUS_MIN + st.FOCUS_MAX) / 2)
    ndi.handle('<ntk_ptz_focus mode="auto"/>')
    assert ndi.state.autofocus


def test_presets(ndi):
    ndi.handle('<ntk_ptz_pan_tilt pan="0.500000" tilt="0.000000"/>')
    assert ndi.handle('<ntk_ptz_store_preset index="3"/>')
    ndi.handle('<ntk_ptz_pan_tilt pan="0.000000" tilt="0.000000"/>')
    assert ndi.handle('<ntk_ptz_recall_preset index="3" speed="0.500000"/>')
    assert ndi.state.position()[0] == round(0.5 * st.PAN_MAX)
    assert not ndi.handle('<ntk_ptz_recall_preset index="4" speed="1.0"/>')
    assert not ndi.handle('<ntk_ptz_store_preset index="100"/>')


def test_recall_speed_slows_the_move():
    ndi = NdiPtzController(ViscaCamera())
    ndi.state.pan = 1000
    ndi.handle('<ntk_ptz_store_preset index="1"/>')
    ndi.state.pan = 0
    ndi.handle('<ntk_ptz_recall_preset index="1" speed="0.250000"/>')
    assert ndi.state.pan_target[1] == pytest.approx(
        0.25 * st.PAN_SPEED_MAX * st.PAN_TILT_UNITS_PER_SPEED_STEP)


def test_unsimulated_and_unknown_messages(ndi):
    assert ndi.handle('<ntk_ptz_exposure mode="auto"/>')
    assert "not simulated" in ndi.camera.log[-1].description
    assert not ndi.handle('<ntk_tally on_program="true"/>')
    assert not ndi.handle('<not xml')
    assert not ndi.handle('<ntk_ptz_zoom zoom="abc"/>')


def test_renderer_follows_camera():
    pytest.importorskip("numpy")
    from ptzsim.ndi import SceneRenderer

    renderer = SceneRenderer(160, 90)
    s = st.CameraState()
    first = renderer.render(s)
    assert first.shape == (90, 160, 4)
    s.pan = 500
    assert (renderer.render(s) != first).any()


def test_real_ndi_round_trip():
    """Sender (simulator) and receiver (NDIlib_recv_ptz_*) over the NDI runtime."""
    ndi_lib = pytest.importorskip("NDIlib")
    pytest.importorskip("numpy")
    from ptzsim.ndi import start_ndi
    from ptzsim.transports import Simulator

    async def run():
        camera = ViscaCamera()
        sim = Simulator(camera, tick_interval=0.01)
        ticker = asyncio.ensure_future(sim.run())
        source = start_ndi(camera, f"ptzsim-test-{time.time_ns()}", fps=25)
        loop = asyncio.get_running_loop()

        def receive():
            finder = ndi_lib.find_create_v2(ndi_lib.FindCreate(p_extra_ips="127.0.0.1"))
            found = None
            for _ in range(30):
                ndi_lib.find_wait_for_sources(finder, 500)
                found = next((x for x in ndi_lib.find_get_current_sources(finder)
                              if x.ndi_name.endswith(f"({source.name})")), None)
                if found:
                    break
            assert found, "NDI source not discovered"
            recv = ndi_lib.recv_create_v3(ndi_lib.RecvCreateV3())
            ndi_lib.recv_connect(recv, found)
            for _ in range(100):
                ndi_lib.recv_capture_v2(recv, 100)
                if ndi_lib.recv_ptz_is_supported(recv):
                    break
            supported = ndi_lib.recv_ptz_is_supported(recv)
            ndi_lib.recv_ptz_pan_tilt(recv, 0.5, 0.0)
            ndi_lib.recv_ptz_zoom(recv, 0.0)
            ndi_lib.recv_ptz_store_preset(recv, 7)
            for _ in range(10):
                ndi_lib.recv_capture_v2(recv, 100)
            ndi_lib.recv_destroy(recv)
            ndi_lib.find_destroy(finder)
            return supported

        try:
            supported = await loop.run_in_executor(None, receive)
            await asyncio.sleep(0.5)
            return supported, camera
        finally:
            source.stop()
            ticker.cancel()

    supported, camera = asyncio.run(run())
    assert supported
    assert camera.state.pan_target is not None or camera.state.pan > 0
    assert 7 in camera.state.presets


def test_ndi_preset_range_is_0_to_99():
    from ptzsim.ndi import NdiPtzController
    from ptzsim.visca import ViscaCamera
    ndi = NdiPtzController(ViscaCamera(instant=True))
    assert ndi.handle('<ntk_ptz_store_preset index="99"/>')
    assert not ndi.handle('<ntk_ptz_store_preset index="100"/>')  # outside the SDK range


def test_ndi_announces_ptz_capabilities():
    import xml.etree.ElementTree as ET
    from ptzsim.ndi import CAPABILITIES
    attrs = ET.fromstring(CAPABILITIES).attrib
    assert attrs["ntk_ptz"] == "true" and attrs["ntk_zoom"] == "true" and attrs["ntk_preset_speed"] == "true"


# ------------------------------------------------- controller edge cases
def test_focus_speed(ndi):
    assert ndi.handle('<ntk_ptz_focus_speed distance="0.500000"/>')
    assert not ndi.state.autofocus
    assert ndi.state.focus_velocity == pytest.approx(0.5 * 8 * st.FOCUS_UNITS_PER_SPEED_STEP)
    assert "focus speed +0.50" in ndi.camera.log[-1].description
    assert ndi.handle('<ntk_ptz_focus_speed distance="0.000000"/>')
    assert ndi.state.focus_velocity == 0
    assert ndi.camera.log[-1].description == "focus stop"
    assert ndi.handle('<ntk_ptz_focus_speed distance="9"/>')  # clamped to 1
    assert ndi.state.focus_velocity == 8 * st.FOCUS_UNITS_PER_SPEED_STEP


def test_unknown_white_balance_mode_is_accepted_but_not_simulated(ndi):
    assert ndi.handle('<ntk_ptz_white_balance mode="weird"/>')
    assert "not simulated" in ndi.camera.log[-1].description
    assert ndi.state.white_balance == "auto"  # unchanged


def test_iris_and_flip_are_accepted_but_not_simulated(ndi):
    assert ndi.handle('<ntk_ptz_iris mode="auto"/>')
    assert "iris" in ndi.camera.log[-1].description
    assert ndi.handle('<ntk_ptz_flip mode="h"/>')
    assert "flip" in ndi.camera.log[-1].description


def test_missing_attribute_is_rejected(ndi):
    assert not ndi.handle('<ntk_ptz_zoom/>')
    assert ndi.camera.log[-1].ok is False
    assert "bad attribute" in ndi.camera.log[-1].description


# ------------------------------------------------------- scene picture (numpy)
def test_landmark_bitmap_shapes_and_coverage():
    np = pytest.importorskip("numpy")
    from ptzsim import scenery
    from ptzsim.ndi import SUB_X, SUB_Y, _landmark_bitmap

    lm = scenery.LANDMARKS[0]
    rgb, mask = _landmark_bitmap(lm)
    assert rgb.shape == (lm.rows * SUB_Y, lm.cols * SUB_X, 3)
    assert mask.shape == rgb.shape[:2]
    assert mask.any()
    assert rgb[mask].any()  # painted pixels are not all black


def test_renderer_draws_sky_ground_and_crosshair():
    np = pytest.importorskip("numpy")
    from ptzsim.ndi import SceneRenderer

    renderer = SceneRenderer(160, 90)
    frame = renderer.render(st.CameraState())
    assert frame.shape == (90, 160, 4)
    assert (frame[..., 3] == 255).all()  # fully opaque
    cy, cx = 45, 80
    assert tuple(frame[cy, cx]) == (0, 255, 255, 255)  # centre crosshair, BGRX
    assert tuple(frame[cy, cx + 12]) == (0, 255, 255, 255)
    side = 10  # away from the red post every 45 degrees at the centre column
    assert frame[0, side, 0] > frame[0, side, 2]  # sky: more blue than red
    assert frame[-1, side, 1] > frame[-1, side, 0]  # ground: more green than blue


def test_renderer_zoom_narrows_the_field_of_view():
    pytest.importorskip("numpy")
    from ptzsim.ndi import SceneRenderer

    renderer = SceneRenderer(160, 90)
    s = st.CameraState()
    wide = renderer.render(s)
    s.zoom = st.ZOOM_MAX  # 20x zoom
    tele = renderer.render(s)
    assert (wide != tele).any()


def test_renderer_draws_a_landmark_at_its_pan_tilt():
    np = pytest.importorskip("numpy")
    from ptzsim import scenery
    from ptzsim.ndi import SceneRenderer

    renderer = SceneRenderer(320, 180)
    lm = next(lm for lm in scenery.LANDMARKS if lm.fill is not None)  # a sign with a board
    s = st.CameraState()
    s.pan = lm.az * st.UNITS_PER_DEGREE
    s.tilt = (lm.el + lm.top) / 2 * st.UNITS_PER_DEGREE
    frame = renderer.render(s)
    bgr = np.array(lm.fill.bgr, dtype=np.uint8)
    assert (frame[..., :3] == bgr).all(axis=-1).any()  # the sign board is visible


# --------------------------------------------------- NdiSource with a fake NDIlib
import types


def make_fake_ndilib(metadata=(), source_name="HOST (cam)", init_ok=True, sender="sender"):
    mod = types.ModuleType("NDIlib")
    mod.FOURCC_VIDEO_TYPE_BGRX = "BGRX"
    state = {"caps": None, "sent": 0, "destroyed": 0, "metadata": list(metadata)}

    class SendCreate:
        def __init__(self, name, clock_video=True, clock_audio=False):
            self.ndi_name = name

    class MetadataFrame:
        def __init__(self):
            self.data = None

    class VideoFrameV2:
        pass

    class SourceName:
        def __init__(self, name):
            self.ndi_name = name

    mod.SendCreate = SendCreate
    mod.MetadataFrame = MetadataFrame
    mod.VideoFrameV2 = VideoFrameV2
    mod.initialize = lambda: init_ok
    mod.send_create = lambda settings: sender
    mod.send_add_connection_metadata = lambda snd, caps: state.__setitem__("caps", caps.data)
    mod.send_get_source_name = lambda snd: SourceName(source_name)

    def send_video(snd, frame):
        state["sent"] += 1
        time.sleep(0.005)  # the real call blocks to the frame rate

    def capture(snd, md, timeout):
        md.data = state["metadata"].pop(0) if state["metadata"] else None

    mod.send_send_video_v2 = send_video
    mod.send_capture = capture
    mod.send_free_metadata = lambda snd, md: None
    mod.send_destroy = lambda snd: state.__setitem__("destroyed", state["destroyed"] + 1)
    return mod, state


def test_ndi_source_needs_the_ndilib_package(monkeypatch):
    monkeypatch.setitem(sys.modules, "NDIlib", None)  # import NDIlib raises ImportError
    from ptzsim.ndi import NdiSource

    with pytest.raises(RuntimeError, match="ndi-python"):
        NdiSource(ViscaCamera(), "cam")


def test_ndi_source_start_sends_metadata_and_applies_ptz_commands(monkeypatch):
    pytest.importorskip("numpy")
    from ptzsim.ndi import CAPABILITIES, NdiSource

    mod, state = make_fake_ndilib(metadata=['<ntk_ptz_pan_tilt pan="0.500000" tilt="0.000000"/>'])
    monkeypatch.setitem(sys.modules, "NDIlib", mod)
    cam = ViscaCamera(instant=True)
    source = NdiSource(cam, "cam", fps=25)
    handled = []
    source.start(lambda fn: (handled.append(fn), fn()))
    try:
        assert source.source_name == "HOST (cam)"
        assert state["caps"] == CAPABILITIES
        time.sleep(0.1)
    finally:
        source.stop()
    assert state["sent"] > 0 and state["destroyed"] == 1
    assert handled  # the PTZ metadata was dispatched
    assert cam.state.pan == round(0.5 * st.PAN_MAX)  # instant mode: move finished


def test_ndi_source_name_falls_back_when_the_sdk_cannot_convert_it(monkeypatch):
    pytest.importorskip("numpy")
    from ptzsim.ndi import NdiSource

    mod, _ = make_fake_ndilib()

    def broken(snd):
        raise TypeError("cannot convert")

    mod.send_get_source_name = broken
    monkeypatch.setitem(sys.modules, "NDIlib", mod)
    source = NdiSource(ViscaCamera(), "cam")
    source.start(lambda fn: fn())
    try:
        assert source.source_name.endswith("(cam)")
    finally:
        source.stop()


def test_ndi_source_start_fails_without_runtime_or_sender(monkeypatch):
    pytest.importorskip("numpy")
    from ptzsim.ndi import NdiSource

    mod, _ = make_fake_ndilib(init_ok=False)
    monkeypatch.setitem(sys.modules, "NDIlib", mod)
    with pytest.raises(RuntimeError, match="could not be initialised"):
        NdiSource(ViscaCamera(), "cam").start(lambda fn: fn())

    mod, _ = make_fake_ndilib(sender=None)
    monkeypatch.setitem(sys.modules, "NDIlib", mod)
    with pytest.raises(RuntimeError, match="could not create NDI sender"):
        NdiSource(ViscaCamera(), "cam").start(lambda fn: fn())


def test_start_ndi_dispatches_on_the_running_loop(monkeypatch):
    pytest.importorskip("numpy")
    from ptzsim.ndi import start_ndi

    mod, _ = make_fake_ndilib()
    monkeypatch.setitem(sys.modules, "NDIlib", mod)

    async def run():
        source = start_ndi(ViscaCamera(), "cam")
        await asyncio.sleep(0.05)
        source.stop()
        return source

    source = asyncio.run(run())
    assert source.source_name == "HOST (cam)"


def test_ndi_plugin_starts_and_stops_a_source(monkeypatch):
    pytest.importorskip("numpy")
    from ptzsim.testing import serve

    mod, state = make_fake_ndilib()
    monkeypatch.setitem(sys.modules, "NDIlib", mod)

    async def run():
        async with serve("--ndi") as ctx:
            titles = [str(e) for e in ctx.endpoints]
            assert titles == ["NDI HOST (cam)"]
            await asyncio.sleep(0.05)

    asyncio.run(run())
    assert state["destroyed"] == 1  # stop() ended the sender thread
