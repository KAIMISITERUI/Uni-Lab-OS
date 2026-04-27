import * as Zrender from 'zrender'

function travelZ (node: Zrender.Element, startZ: number | number[], step: number): void {
  if (typeof startZ === 'number') {
    startZ = [startZ]
  }

  if (node instanceof Zrender.Group) {
    for (let idx = 0; idx < node.childCount(); idx++) {
      const son = node.childAt(idx)
      travelZ(son, startZ, step)
    }
  } else if (node instanceof Zrender.Displayable) {
    // eslint-disable-next-line
    node.z = startZ[0]
    startZ[0] += step
  }
}

function mathSlotTndir (layout_code: string, stationModel: string): string | undefined {
  const { model, $view } = window.webb.store.get('params')
  const config = model.slot.tndir[$view]
  const cfg = config[stationModel] || config
  return Object.keys(cfg).find((tndir: string) => {
    if (!Array.isArray(cfg[tndir])) return false
    return cfg[tndir]?.some((ruler: string) => layout_code.startsWith(ruler))
  })
}

export {
  travelZ,
  mathSlotTndir
}
