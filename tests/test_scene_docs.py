# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

import importlib.util
from pathlib import Path

import pytest

from ptzsim import state as st
from ptzsim.onvif import pan_from_onvif, tilt_from_onvif, zoom_from_onvif
from ptzsim.viewfinder import render_view
from ptzsim.visca import ViscaCamera

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("scene_docs", ROOT / "scripts" / "scene_docs.py")
scene_docs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scene_docs)


def test_generated_docs_are_up_to_date():
    assert scene_docs.main(["--check"]) == 0, "run: python3 scripts/scene_docs.py"


@pytest.mark.parametrize("stop", scene_docs.TOUR, ids=lambda stop: stop.slug)
def test_documented_visca_packets_reach_the_viewpoint(stop):
    camera = ViscaCamera()
    for packet in scene_docs.visca(stop):
        camera.handle(bytes.fromhex(packet))
    for _ in range(2000):
        camera.state.tick(0.05)
    s = camera.state
    assert s.pan_degrees == pytest.approx(stop.pan, abs=0.05)
    assert s.tilt_degrees == pytest.approx(stop.tilt, abs=0.05)
    assert s.zoom_ratio == pytest.approx(stop.zoom, abs=0.01)


@pytest.mark.parametrize("stop", scene_docs.TOUR, ids=lambda stop: stop.slug)
def test_documented_onvif_values_match(stop):
    x, y, z = scene_docs.onvif(stop)
    assert pan_from_onvif(x) / st.UNITS_PER_DEGREE == pytest.approx(stop.pan, abs=0.05)
    assert tilt_from_onvif(y) / st.UNITS_PER_DEGREE == pytest.approx(stop.tilt, abs=0.05)
    assert zoom_from_onvif(z) == pytest.approx(scene_docs.zoom_units(stop), abs=1)


@pytest.mark.parametrize("stop", scene_docs.TOUR, ids=lambda stop: stop.slug)
def test_every_viewpoint_shows_a_landmark_and_has_images(stop):
    picture = "".join(render_view(scene_docs.camera(stop), 72, 20))
    assert set(picture) - set(" ·.:+─│◎°0123456789-"), f"{stop.slug}: only background"
    for suffix in ("ndi.png", "tui.svg"):
        assert (scene_docs.IMAGES / f"{stop.slug}-{suffix}").is_file()
