/**
 * Unique ID Generator
 * TheoXiong
 */
interface NowObj {
  last?: number
}
interface NowFunc extends NowObj {
  (): number
}

const now: NowFunc = (): number => {
  const current: number = Date.now()
  const last: number = now.last || current
  now.last = current > last ? current : last + 1
  return now.last
}

const unique = (prefix: string = '', suffix: string = ''): string => prefix + now().toString(16) + suffix

export {
  unique
}
