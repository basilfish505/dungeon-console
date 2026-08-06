"""Unit tests for adaptive viewport camera and OOB map slicing."""
import unittest

from camera import (
    EDGE_MARGIN,
    clamp_viewport_size,
    effective_margin,
    slice_map,
    update_camera,
)


def _grid(h, w, fill='.'):
    return [[fill for _ in range(w)] for _ in range(h)]


class ClampViewportTests(unittest.TestCase):
    def test_clamp_within_bounds(self):
        self.assertEqual(clamp_viewport_size(20, 30), (20, 30))

    def test_clamp_raises_floor(self):
        self.assertEqual(clamp_viewport_size(2, 3), (8, 8))

    def test_clamp_caps_ceiling(self):
        self.assertEqual(clamp_viewport_size(200, 99), (80, 80))

    def test_clamp_invalid_falls_back(self):
        self.assertEqual(clamp_viewport_size('x', None), (20, 20))


class EffectiveMarginTests(unittest.TestCase):
    def test_full_margin(self):
        self.assertEqual(effective_margin(20), EDGE_MARGIN)

    def test_tiny_viewport(self):
        self.assertEqual(effective_margin(5), 2)
        self.assertEqual(effective_margin(1), 0)


class SliceMapOobTests(unittest.TestCase):
    def test_exact_size_and_oob_hash(self):
        m = _grid(5, 5, '.')
        sliced = slice_map(m, cam_y=-2, cam_x=-1, vh=4, vw=4)
        self.assertEqual(len(sliced), 4)
        self.assertEqual(len(sliced[0]), 4)
        # Row 0 is fully OOB (wy=-2)
        self.assertEqual(sliced[0], ['#', '#', '#', '#'])
        # Row 2, col 1 is map[0][0]
        self.assertEqual(sliced[2][1], '.')

    def test_interior_slice_no_oob(self):
        m = _grid(10, 10, 'a')
        sliced = slice_map(m, 2, 3, vh=3, vw=3)
        self.assertEqual(sliced, [['a', 'a', 'a']] * 3)


class CameraMarginTests(unittest.TestCase):
    def test_initial_centers_on_player(self):
        cam = update_camera(None, (10, 10), 40, 40, vh=20, vw=20)
        self.assertEqual(cam, (0, 0))  # 10 - 10 = 0

    def test_margin_scrolls_before_edge(self):
        # Player near top of viewport with margin 4 → camera moves up (may go OOB)
        cam = update_camera((5, 5), (6, 10), 40, 40, vh=20, vw=20)
        # sy = 6-5 = 1 < 4 → cam_y = 6-4 = 2
        self.assertEqual(cam[0], 2)
        self.assertEqual(cam[1], 5)

    def test_edge_allows_negative_camera_for_margin(self):
        # Player at map origin; initial camera centers then keeps player in view (OOB #).
        cam = update_camera(None, (0, 0), 40, 40, vh=20, vw=20)
        self.assertEqual(cam, (-10, -10))
        self.assertTrue(0 <= 0 - cam[0] < 20)

    def test_player_never_leaves_view(self):
        cam_y, cam_x = update_camera((0, 0), (15, 15), 40, 40, vh=10, vw=10)
        self.assertTrue(0 <= 15 - cam_y < 10)
        self.assertTrue(0 <= 15 - cam_x < 10)

    def test_center_when_viewport_fits_map(self):
        cam = update_camera(None, (2, 2), 10, 10, vh=20, vw=20)
        self.assertEqual(cam, (-5, -5))  # (10-20)//2

    def test_margin_preserved_near_map_edge(self):
        # Start with camera at 0; player at y=1 → within margin → cam goes negative
        cam = update_camera((0, 0), (1, 5), 30, 30, vh=20, vw=20)
        sy = 1 - cam[0]
        self.assertGreaterEqual(sy, EDGE_MARGIN)


if __name__ == '__main__':
    unittest.main()
