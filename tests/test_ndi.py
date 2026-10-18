"""NDI PTZ commands (metadata XML) and, if ndi-python is installed, a real NDI round trip."""

import asyncio
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
    assert ndi.handle('<ntk_ptz_white_balance mode="auto"/>')
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
