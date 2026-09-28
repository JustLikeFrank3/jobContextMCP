# Rendering the badge app without a badge

`render.mjs` runs `badge/jobcontext` inside Pimoroni's Badgeware web
simulator — the MicroPython build and graphics library the badge firmware is
built on, compiled to WebAssembly — and saves a PNG of every screen.

```sh
git clone --depth 1 https://github.com/pimoroni/badgeware-web-simulator /tmp/websim
SIM_DIR=/tmp/websim node badge/simulator/render.mjs            # → badge/simulator/out/
SIM_DIR=/tmp/websim node badge/simulator/render.mjs /tmp/shots # or anywhere
```

It needs Node and Playwright with a Chromium it can launch (set `PW_PATH` to
the Playwright package if it is installed globally). Nothing is fetched at
run time: the script serves the simulator clone itself, so it works offline
once cloned.

`scenes.py` is the program the simulator runs. It maps the 2026 pad
constants onto the stock Tufty buttons, fakes `wifi`, `requests` and
`secrets`, imports the real app, and forces each screen in turn; add a scene
there to render a new state.

## What it proves, and what it doesn't

It proves the drawing code against the real library: text measurement,
wrapping and ellipsis overflow, shapes, fonts, `HIRES` layout, and that the
app imports and runs under MicroPython rather than CPython.

It does not model GitHub's 2026 hardware — capacitive pads, IMU-driven
orientation, the radio, IR — so input feel and networking still need a real
badge.

Scene PNGs are written to `out/` by default, which is gitignored. The README's
`screens.png` is a hand-picked sheet of six of them.
