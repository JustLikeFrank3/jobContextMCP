/* The about:blank preview inherits the dashboard's strict CSP. Load a
 * same-origin script instead of inline code or an onclick attribute. Use a
 * function scope because document.write can render a loading shell followed
 * by the final document in the same window. */
;(function () {
  const button = document.getElementById('print-preview')
  if (!button) return
  button.addEventListener('click', function () {
    const frame = document.getElementById('pv')
    try {
      if (frame && frame.contentWindow) {
        frame.contentWindow.focus()
        frame.contentWindow.print()
      } else {
        window.print()
      }
    } catch {
      window.print()
    }
  })
})()
