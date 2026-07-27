"""Server-side viewport camera with dead-zone scrolling."""

VIEWPORT_H = 20
VIEWPORT_W = 20
DEADZONE = 8


def update_camera(prev_cam, player_pos, map_h, map_w,
                  vh=VIEWPORT_H, vw=VIEWPORT_W, deadzone=DEADZONE):
    """
    Return (cam_y, cam_x) top-left of the viewport.

    Player may sit within ±deadzone of viewport center before the camera scrolls.
    Camera is clamped so the viewport never shows tiles outside the map.
    """
    py, px = player_pos

    if prev_cam is None:
        cam_y = py - vh // 2
        cam_x = px - vw // 2
    else:
        cam_y, cam_x = prev_cam
        sy = py - cam_y
        sx = px - cam_x
        cy = vh // 2
        cx = vw // 2

        if sy < cy - deadzone:
            cam_y = py - (cy - deadzone)
        elif sy > cy + deadzone:
            cam_y = py - (cy + deadzone)

        if sx < cx - deadzone:
            cam_x = px - (cx - deadzone)
        elif sx > cx + deadzone:
            cam_x = px - (cx + deadzone)

    max_y = max(0, map_h - vh)
    max_x = max(0, map_w - vw)
    cam_y = max(0, min(int(cam_y), max_y))
    cam_x = max(0, min(int(cam_x), max_x))
    return cam_y, cam_x


def slice_map(game_map, cam_y, cam_x, vh=VIEWPORT_H, vw=VIEWPORT_W):
    """Return the viewport slice of game_map."""
    h = len(game_map)
    if h == 0:
        return []
    w = len(game_map[0])
    end_y = min(h, cam_y + vh)
    end_x = min(w, cam_x + vw)
    return [row[cam_x:end_x] for row in game_map[cam_y:end_y]]
