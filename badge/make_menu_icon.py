#!/usr/bin/env python3
"""Emit the jC mark as Badgeware menu-icon contours.

The BadgeOS launcher draws each tile from ICONS[slug]: a tuple of closed
polygons in coordinates normalized to the tile (centre 0,0, glyph within
about +/-0.5). This converts the geometry of
docs/branding/logo/jobcontextmcp-mark-dark.svg (ring, C, j) into four such
polygons: an annulus, a stroked arc with round caps, a dot, and a stroked
polyline with round caps. Output is pasted into badge/install.py's
_BADGEOS_ICON, which the installer injects into the menu at install time.

    python3 badge/make_menu_icon.py
"""

import math

W = 320.0  # SVG viewBox; centre (160, 160)
OX = -12  # the glyph group's translate(-12 0)


def norm(points):
    return tuple(round((v - 160.0) / W, 3) for xy in points for v in xy)


def circle(cx, cy, r, n=24):
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n))
            for i in range(n)]


def annulus(cx, cy, r_out, r_in, n=40):
    """Ring as one nonzero-fill polygon: outer loop + reversed inner loop."""
    outer = circle(cx, cy, r_out, n)
    inner = circle(cx, cy, r_in, n)[::-1]
    return outer + [outer[0]] + [inner[-1]] + inner


def stroked_arc(cx, cy, r, a0, sweep, half, steps=36):
    """Arc stroke with round caps as one polygon."""
    angles = [a0 - sweep * i / steps for i in range(steps + 1)]
    outer = [(cx + (r + half) * math.cos(a), cy + (r + half) * math.sin(a)) for a in angles]
    inner = [(cx + (r - half) * math.cos(a), cy + (r - half) * math.sin(a)) for a in reversed(angles)]

    def cap(angle, sign):
        # semicircle around the end point, bulging along the travel direction
        ex, ey = cx + r * math.cos(angle), cy + r * math.sin(angle)
        ux, uy = math.cos(angle), math.sin(angle)  # radial (outer)
        tx, ty = sign * uy, -sign * ux  # tangent, in travel direction
        return [(ex + half * (math.cos(p) * ux + math.sin(p) * tx),
                 ey + half * (math.cos(p) * uy + math.sin(p) * ty))
                for p in [math.pi * i / 8 for i in range(1, 8)]]

    return outer + cap(angles[-1], 1) + inner + cap(angles[0], -1)


def stroked_polyline(points, half, cap_steps=8):
    """Polyline stroke with round caps as one polygon (gentle curves only)."""
    normals = []
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy) or 1.0
        normals.append((-dy / length, dx / length))
    sides = [normals[0]] + [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                            for a, b in zip(normals, normals[1:])] + [normals[-1]]
    left = [(p[0] + half * n[0], p[1] + half * n[1]) for p, n in zip(points, sides)]
    right = [(p[0] - half * n[0], p[1] - half * n[1]) for p, n in zip(points, sides)][::-1]

    def cap(point, normal, flip):
        nx, ny = (normal[0], normal[1]) if not flip else (-normal[0], -normal[1])
        return [(point[0] + half * (math.cos(p) * nx - math.sin(p) * ny),
                 point[1] + half * (math.sin(p) * nx + math.cos(p) * ny))
                for p in [math.pi * i / cap_steps for i in range(1, cap_steps)]]

    return left + cap(points[-1], sides[-1], False) + right + cap(points[0], sides[0], True)


def main():
    # C: "M234 118 A56 56 0 1 0 234 202", stroke 32 — as in badge/make_icon.py
    r = 56.0
    cx = 234.0 - math.sqrt(r * r - 42.0 * 42.0) + OX
    a0 = math.atan2(118.0 - 160.0, 234.0 + OX - cx)
    sweep = 2 * math.pi - 2 * abs(a0)

    # j hook: stem 100,142 -> 100,205 then "Q100 230 74 230", stroke 30
    hook = [(100.0 + OX, 142.0), (100.0 + OX, 205.0)]
    for i in range(1, 13):
        t = i / 12.0
        hook.append(((1 - t) ** 2 * 100 + 2 * (1 - t) * t * 100 + t * t * 74 + OX,
                     (1 - t) ** 2 * 205 + 2 * (1 - t) * t * 230 + t * t * 230))

    contours = (
        norm(annulus(160, 160, 158, 148)),
        norm(stroked_arc(cx, 160.0, r, a0, sweep, 16.0)),
        norm(circle(100.0 + OX, 112.0, 19.0)),
        norm(stroked_polyline(hook, 15.0)),
    )
    print("_BADGEOS_ICON = (")
    for contour in contours:
        print("    " + repr(contour) + ",")
    print(")")


if __name__ == "__main__":
    main()
