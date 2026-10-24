# Architecture diagrams

These checked-in, inert SVG images are served by `/architecture`. Removing the
runtime Mermaid renderer eliminates the public page's external executable
dependency and runtime-injected CSS. Diagrams work offline and under a restrictive
CSP. The labels, groups, message ordering, arrow directions and design-token
colors preserve the original architecture diagrams.

`capability-layer.dot` is the maintained overview source. Regenerate with
Graphviz (a developer tool, not an application dependency):

```sh
python scripts/render_architecture_diagrams.py
```

`webmcp-bridge.svg` is directly maintained vector source with fixed coordinates,
accessible title/description and no generation step. Review both images after
editing; do not introduce scripts, external resources, links or event handlers.
The helper strips Graphviz's unneeded remote DTD and validates both assets.
