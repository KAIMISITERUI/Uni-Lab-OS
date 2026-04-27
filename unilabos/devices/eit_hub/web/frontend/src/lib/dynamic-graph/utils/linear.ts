import Color from 'color'

export function handleLinear (svg_dom: Document): void {
  const defsDoms = svg_dom.getElementsByTagName('defs')

  for (let i = 0; i < defsDoms.length; i++) {
    const defsDom = defsDoms[i]
    if (defsDom?.childNodes?.length > 0) {
      for (let j = 0; j < defsDom.childNodes.length; j++) {
        const linearDom = defsDom.childNodes[j] as HTMLElement
        const _xlink = linearDom?.getAttribute?.('xlink:href')
        if (_xlink?.startsWith('#')) {
          const targetLinearDom = defsDom.querySelector(_xlink)
          if (Number(targetLinearDom?.childNodes?.length) > 0) {
            targetLinearDom?.childNodes.forEach((n: ChildNode) => {
              const el = n as HTMLElement
              if (el?.style?.stopOpacity && el?.style?.stopColor && Number(el?.style?.stopOpacity) !== 1) {
                el.style.stopColor = Color(el.style.stopColor).alpha(Number(el.style.stopOpacity)).string()
              }
              linearDom.appendChild(n.cloneNode(true))
            })
          }
        }
      }
    }
  }
}
