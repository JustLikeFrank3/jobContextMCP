import { createContext, useContext, useLayoutEffect } from 'react'

/* Toolbar slot — lets a screen project content (primary action button, the
   import step indicator) into the shell's sticky toolbar, per the desktop
   design's content-toolbar spec. The shell provides setNode; screens use
   useToolbarSlot(node, deps) and the slot clears itself on unmount. */

export const ToolbarSlotContext = createContext({ node: null, setNode: () => {} })

export function useToolbarSlot(node, deps = []) {
  const { setNode } = useContext(ToolbarSlotContext)
  useLayoutEffect(() => {
    setNode(node)
    return () => setNode(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
}
