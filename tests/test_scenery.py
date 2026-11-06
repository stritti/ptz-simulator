# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

import pytest

from ptzsim import scenery
from ptzsim import state as st
from ptzsim.state import CameraState
from ptzsim.viewfinder import BASE_FOV, framed_picture, render_view

COLS, ROWS = 59, 15
BACKGROUND = set(" ·.:+─│◎°0123456789-")


def camera(pan_deg, tilt_deg, ratio=1.0):
    ratio = min(max(ratio, 1.0), st.MAX_OPTICAL_ZOOM)
    zoom = (ratio - 1) / (st.MAX_OPTICAL_ZOOM - 1) * (st.ZOOM_MAX - st.ZOOM_MIN)
    return CameraState(pan=pan_deg * st.UNITS_PER_DEGREE, tilt=tilt_deg * st.UNITS_PER_DEGREE,
                       zoom=round(zoom))


def aim_at(lm):
    """Camera pointed at the middle of a landmark, zoomed so it shows at its own scale."""
    az, el = lm.point(lm.rows // 2, lm.cols // 2)
    return camera(az, el, BASE_FOV / (lm.px * COLS))


def test_landmarks_are_well_formed_and_reachable():
    names = [lm.name for lm in scenery.LANDMARKS]
    assert len(names) == len(set(names)) >= 12
    for lm in scenery.LANDMARKS:
        assert lm.rows and lm.cols and lm.px > 0, lm
        if scenery.FILL in "".join(lm.art):
            assert lm.fill is not None, lm
        for line in lm.art:
            for ch in line.replace(" ", ""):
                lm.paint(ch)  # every character has a colour
        # Reachable: pan ±170° and tilt -30..+90° plus half the 60° field of view.
        assert -200 <= lm.az <= 200 and -45 <= lm.el and lm.top <= 105, lm


@pytest.mark.parametrize("lm", scenery.LANDMARKS, ids=lambda lm: lm.name)
def test_every_landmark_shows_at_its_coordinates(lm):
    art = set("".join(lm.art)) - {" ", scenery.FILL} - BACKGROUND
    seen = set("".join(render_view(aim_at(lm), COLS, ROWS)))
    assert art & seen, f"{lm.name}: none of {sorted(art)} in the picture"


def test_landmarks_stay_at_fixed_positions():
    ufo = "".join(render_view(camera(140, 17.5), COLS, ROWS))
    balloon = "".join(render_view(camera(-140, 24), COLS, ROWS))
    assert "═" in ufo and "═" not in balloon
    assert "▓" in balloon and "▲" not in balloon
    assert "▲" in "".join(render_view(camera(80, 5), COLS, ROWS))  # the Alps
    assert render_view(camera(80, 5), COLS, ROWS) == render_view(camera(80, 5), COLS, ROWS)


def test_home_view_keeps_horizon_and_zero_post_clear():
    lines = render_view(camera(0, 0), COLS, ROWS)
    assert "♣" in "".join(lines)  # the forest is in sight left of the 0° post
    assert set(lines[ROWS // 2].replace("◎", "")) == {"─"}


def test_pan_wraps_around_behind_the_camera():
    # Pan +170 sees up to +200°, which is where the -165° billboard stands.
    assert scenery.VISCA_SIGN.cell(195.0, 3.0) is not None
    assert scenery.VISCA_SIGN.overlaps(170, 200, -10, 10)
    assert not scenery.ALPS.overlaps(140, 200, -10, 10)
    right = [line[60:] for line in render_view(camera(170, 2), 88, 25)]
    assert "━" in "".join(right)


def test_text_is_drawn_once_when_zoomed_in():
    lines = render_view(camera(-165, 2.8, 4), 88, 25)
    text = "\n".join(lines)
    for letter in "VISHOMEND":
        assert letter in text
    assert not any(a == b and a.isalpha() for line in lines for a, b in zip(line, line[1:]))


def test_hidden_details_need_zoom():
    summit = scenery.SUMMIT
    az, el = summit.point(1, 1)
    wide = "".join(render_view(camera(az, el, 1), COLS, ROWS))
    tele = "".join(render_view(camera(az, el, st.MAX_OPTICAL_ZOOM), COLS, ROWS))
    assert "\\o/" not in wide and "o" in tele


def test_picture_styles_match_the_characters():
    s = camera(140, 17.5)
    lines, styles = framed_picture(s, COLS + 2, ROWS + 2)
    assert len(styles) == ROWS and all(len(row) == COLS for row in styles)
    hull = [styles[r][c] for r, line in enumerate(lines[1:-1]) for c, ch in enumerate(line[1:-1])
            if ch == "═"]
    assert hull and set(hull) == {scenery.PAINTS["hull"].term}
    assert styles[ROWS // 2][COLS // 2] == "yellow+bold"  # crosshair


def test_ndi_picture_shows_landmarks():
    np = pytest.importorskip("numpy")
    from ptzsim.ndi import FONT, SceneRenderer

    assert all(len(rows) == 5 and all(len(r) == 3 for r in rows) for rows in FONT.values())
    renderer = SceneRenderer(320, 180)
    frame = renderer.render(camera(140, 17.5))
    hull = np.array(scenery.PAINTS["hull"].bgr, dtype=np.uint8)
    assert (frame[..., :3] == hull).all(axis=-1).any()
    frame = renderer.render(camera(-140, 24))
    assert not (frame[..., :3] == hull).all(axis=-1).any()


def test_overlaps_matches_a_brute_force_check():
    for lm in scenery.LANDMARKS:
        for start in range(-200, 200, 7):
            for span in (3, 30, 60):
                expected = any(abs(lm.offset(start + i * 0.05)) <= lm.width / 2
                               for i in range(int(span / 0.05) + 1))
                assert lm.overlaps(start, start + span, lm.el, lm.top) == expected, (lm, start, span)


def test_magnified_text_never_drops_or_doubles_a_character():
    lm = scenery.STRAGGLER
    az, el = lm.point(0, lm.cols // 2)
    for step in range(40):  # sweep, so character centres fall on cell borders too
        lines = render_view(camera(az + step * 0.0113, el + step * 0.0071, 15), 88, 25)
        assert "".join(lines).count("!") == 1, step
