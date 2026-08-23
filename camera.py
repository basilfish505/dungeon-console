"""Server-side viewport camera with edge-margin scrolling and OOB fill."""

VIEWPORT_H = 20
VIEWPORT_W = 20
# Tile margin at default zoom (DEFAULT_VIEW_SPAN tiles across). Scales with viewport
# so on-screen lead-in distance stays roughly constant when zooming.
EDGE_MARGIN = 4
DEFAULT_VIEW_SPAN = 20

# Adaptive viewport bounds (client may request sizes within this range).
# Clients send rectangular viewports; each axis is clamped independently.
# Zoom is "N tiles across the shorter axis"; the longer axis may show more.
MIN_VIEWPORT = 4
MAX_VIEWPORT = 120


def clamp_viewport_size(vh, vw, min_size=MIN_VIEWPORT, max_size=MAX_VIEWPORT):
    """Clamp requested viewport dimensions per axis (rectangular allowed)."""
    try:
        vh = int(vh)
        vw = int(vw)
    except (TypeError, ValueError):
        return VIEWPORT_H, VIEWPORT_W
    vh = max(min_size, min(max_size, vh))
    vw = max(min_size, min(max_size, vw))
    return vh, vw


def margin_for_span(span, ref_margin=EDGE_MARGIN, ref_span=DEFAULT_VIEW_SPAN):
    """
    Scale edge margin with visible tile count so screen distance stays similar.

    At DEFAULT_VIEW_SPAN (20) → EDGE_MARGIN (4). Zoomed in to 10 → 2; out to 40 → 8.
    """
    try:
        span = int(span)
    except (TypeError, ValueError):
        return ref_margin
    if span <= 0:
        return 0
    # Round half up so highly zoomed views keep a full lead-in tile
    return max(1, int((ref_margin * span + ref_span // 2) // ref_span))


def effective_margin(size, edge_margin=EDGE_MARGIN):
    """Margin that fits inside a one-dimensional viewport span."""
    if size <= 1:
        return 0
    return min(edge_margin, (size - 1) // 2)


def update_camera(prev_cam, player_pos, map_h, map_w,
                  vh=VIEWPORT_H, vw=VIEWPORT_W, edge_margin=None):
    """
    Return integer (cam_y, cam_x) top-left of the viewport.

    Camera scrolls when the player comes within the edge margin of the
    viewport edge. When edge_margin is None (default), margin scales with
    vh/vw so on-screen lead-in matches EDGE_MARGIN at DEFAULT_VIEW_SPAN.

    When the viewport is at least as large as the map on an axis, that axis
    is centered (camera may be negative so OOB pads with #).
    Near map edges the camera may leave the map so the margin is preserved.
    """
    py, px = player_pos
    if edge_margin is None:
        my = effective_margin(vh, margin_for_span(vh))
        mx = effective_margin(vw, margin_for_span(vw))
    else:
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


def clamp_pan_extents(cam_y, cam_x, map_h, map_w, vh, vw, pad=EDGE_MARGIN):
    """
    Clamp a free-look camera. The player may leave the viewport.

    Extents allow EDGE_MARGIN tiles of # beyond the map; when the viewport is
    larger than the map, the camera may shift around the centered position.
    """
    def _axis(cam, map_span, view_span):
        min_c = -pad
        max_c = map_span - view_span + pad
        if max_c < min_c:
            center = (map_span - view_span) // 2
            min_c = center - pad
            max_c = center + pad
        return max(min_c, min(int(cam), max_c))

    return _axis(cam_y, map_h, vh), _axis(cam_x, map_w, vw)


def pan_camera(prev_cam, dcam_y, dcam_x, player_pos, map_h, map_w,
               vh=VIEWPORT_H, vw=VIEWPORT_W):
    """
    Offset the camera by integer tile deltas for free look.

    Does not keep the player on-screen. Camera is clamped to map extents with
    a small # padding so you can inspect any part of the dungeon.
    """
    if prev_cam is None:
        cam_y, cam_x = update_camera(None, player_pos, map_h, map_w, vh=vh, vw=vw)
    else:
        cam_y, cam_x = int(prev_cam[0]), int(prev_cam[1])

    try:
        dcam_y = int(dcam_y)
        dcam_x = int(dcam_x)
    except (TypeError, ValueError):
        dcam_y, dcam_x = 0, 0

    cam_y = cam_y + dcam_y
    cam_x = cam_x + dcam_x
    return clamp_pan_extents(cam_y, cam_x, map_h, map_w, vh, vw)


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
