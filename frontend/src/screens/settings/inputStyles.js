/* Shared text-input styles for the Settings sections. Two variants only
   because the flex rows (Cloud sync, PAT connect) size inputs with flex:1
   while the stacked AI-provider grid uses full-width block inputs. */

export const INPUT_STYLE = {
  width: '100%', padding: '8px 12px', boxSizing: 'border-box',
  background: 'var(--surface)', border: '1px solid var(--surface-chip)',
  borderRadius: 'var(--radius-md)', color: 'var(--text-strong)',
  fontSize: 'var(--fs-sm)', fontFamily: 'inherit', outline: 'none',
}

export const INPUT_STYLE_FLEX = {
  flex: 1, padding: '9px 13px', background: 'var(--surface)',
  border: '1px solid var(--surface-chip)', borderRadius: 'var(--radius-md)',
  color: 'var(--text-strong)', fontSize: 'var(--fs-sm)', outline: 'none',
}
