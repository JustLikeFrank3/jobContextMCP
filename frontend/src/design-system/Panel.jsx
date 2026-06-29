/* Panel — surface container primitive (card / section wrapper).

   Props:
     raised   bool    — use the raised surface + shadow
     pad      string  — CSS padding (default '20px 22px')
     radius   string  — CSS var or value (default var(--radius-lg))
     style    object  — extra style overrides
     children
*/
export default function Panel({
  raised = false,
  pad = '20px 22px',
  radius = 'var(--radius-lg)',
  style = {},
  children,
  ...rest
}) {
  return (
    <div
      style={{
        background: raised ? 'var(--surface-raised)' : 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: radius,
        padding: pad,
        boxShadow: raised ? 'var(--shadow-md)' : 'none',
        ...style,
      }}
      {...rest}
    >
      {children}
    </div>
  )
}
