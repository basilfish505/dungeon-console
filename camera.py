"""Server-side viewport camera with edge-margin scrolling and OOB fill."""

VIEWPORT_H = 20
VIEWPORT_W = 20
EDGE_MARGIN = 4  # scroll when player is within this many tiles of the viewport edge

# Adaptive viewport bounds (client may request sizes within this range)
MIN_VIEWPORT = 8
MAX_VIEWPORT = 80


def clamp_viewport_size(vh, vw, min_size=MIN_VIEWPORT, max_size=MAX_VIEWPORT):
    """Clamp requested viewport dimensions to allowed bounds."""
    try:
        vh = int(vh)
        vw = int(vw)
    except (TypeError, ValueError):
        return VIEWPORT_H, VIEWPORT_W
    vh = max(min_size, min(max_size, vh))
    vw = max(min_size, min(max_size, vw))
    return vh, vw


def effective_margin(size, edge_margin=EDGE_MARGIN):
    """Margin that fits inside a one-dimensional viewport span."""
    if size <= 1:
        return 0
    return min(edge_margin, (size - 1) // 2)


def update_camera(prev_cam, player_pos, map_h, map_w,
                  vh=VIEWPORT_H, vw=VIEWPORT_W, edge_margin=EDGE_MARGIN):
    """
    Return integer (cam_y, cam_x) top-left of the viewport.

    Camera scrolls when the player comes within edge_margin tiles of the
    viewport edge. When the viewport is at least as large as the map on an
    axis, that axis is centered (camera may be negative so OOB pads with #).
    Near map edges the camera may leave the map so the margin is preserved.
    """
    py, px = player_pos
    my = effective_margin(vh, edge_margin)
    mx = effective_margin(vw, edge_margin)

    if vh >= map_h:
        cam_y = (map_h - vh) // 2
    elif prev_cam is None:
        cam_y = py - vh // 2
    else:
        cam_y = prev_cam[0]
        sy = py - cam_y
        if sy < my:
            cam_y = py - my
        elif sy > vh - 1 - my:
            cam_y = py - (vh - 1 - my)

    if vw >= map_w:
        cam_x = (map_w - vw) // 2
    elif prev_cam is None:
        cam_x = px - vw // 2
    else:
        cam_x = prev_cam[1]
        sx = px - cam_x
        if sx < mx:
            cam_x = px - mx
        elif sx > vw - 1 - mx:
            cam_x = px - (vw - 1 - mx)

    # Keep the player inside the viewport (allows OOB # padding).
    if vh < map_h:
        cam_y = max(py - (vh - 1), min(int(cam_y), py))
    if vw < map_w:
        cam_x = max(px - (vw - 1), min(int(cam_x), px))

    return int(cam_y), int(cam_x)


def slice_map(game_map, cam_y, cam_x, vh=VIEWPORT_H, vw=VIEWPORT_W, oob='#'):
    """Return an exact vh×vw viewport slice; out-of-bounds cells are `oob`."""
    h = len(game_map)
    w = len(game_map[0]) if h else 0
    rows = []
    for vy in range(vh):
        wy = cam_y + vy
        row = []
        for vx in range(vw):
            wx = cam_x + vx
            if 0 <= wy < h and 0 <= wx < w:
                row.append(game_map[wy][wx])
            else:
                row.append(oob)
        rows.append(row)
    return rows
