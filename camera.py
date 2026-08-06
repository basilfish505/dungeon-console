"""Server-side viewport camera with edge-margin scrolling."""

VIEWPORT_H = 20
VIEWPORT_W = 20
EDGE_MARGIN = 4  # scroll when player is within this many tiles of the viewport edge


def update_camera(prev_cam, player_pos, map_h, map_w,
                  vh=VIEWPORT_H, vw=VIEWPORT_W, edge_margin=EDGE_MARGIN):
    """
    Return (cam_y, cam_x) top-left of the viewport.

    Camera scrolls when the player comes within edge_margin tiles of the
    viewport edge, keeping them in the central band. Camera is clamped so
    the viewport never shows tiles outside the map.
    """
    py, px = player_pos

    if prev_cam is None:
        cam_y = py - vh // 2
        cam_x = px - vw // 2
    else:
        cam_y, cam_x = prev_cam
        sy = py - cam_y
        sx = px - cam_x

        if sy < edge_margin:
            cam_y = py - edge_margin
        elif sy > vh - 1 - edge_margin:
            cam_y = py - (vh - 1 - edge_margin)

        if sx < edge_margin:
            cam_x = px - edge_margin
        elif sx > vw - 1 - edge_margin:
            cam_x = px - (vw - 1 - edge_margin)

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
