// 判断给定的型号是不是一个孔板托盘
export const mathWellPlates = (model: string): null | { model: string, height: number | null, type: number | null } => {
  const m = model.match(/^(WP\d+H)(\d+_?\d+)?$/)
  const m2 = !m?.[2] ? [] : m[2].split('_')
  const height = m2.pop()
  const type = m2.pop()

  if (m) {
    return {
      type: !type ? null : Number(type),
      model: m[1],
      height: !height ? null : Number(height)
    }
  }
  return m
}
