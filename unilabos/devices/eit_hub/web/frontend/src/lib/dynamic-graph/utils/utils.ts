interface ErrorResponseData {
  message?: string;
  error?: string;
  data?: string;
}
interface ErrorResponse {
  data?: ErrorResponseData
}
export interface ErrorObject {
  response?: ErrorResponse;
  message?: string;
}

const getMessageFromError = (error: ErrorObject, preset: string = ''): string => {
  if (error && error.response && error.response.data && typeof error.response.data.message === 'string') {
    return error.response.data.message
  } else if (error && error.response && error.response.data && typeof error.response.data.error === 'string') {
    return error.response.data.error
  } else if (error && error.response && error.response.data && typeof error.response.data.data === 'string') {
    return error.response.data.data
  } else if (error && typeof error.message === 'string') {
    return error.message
  } else if (error && typeof error === 'string') {
    return error
  }
  return preset
}

const emailToName = (email: string): string => {
  return email && email.split('@')[0] ? email.split('@')[0] : ''
}

const delay = (time: number): Promise<void> => {
  return new Promise((resolve: (args: any) => void) => {
    setTimeout(() => {
      resolve(true)
    }, time)
  })
}

const insertProp = (obj: any, key: string, target: any): void => {
  if (obj) {
    obj[key] = target
  }
}

const getProp = <T = any>(obj: any, key: string): T => {
  return obj?.[key]
}

const matchRangeStr = (str: string, ruler: string): boolean => {
  const match = ruler.match(/(\d+)~(\d+)/)
  if (match) {
    const start = Number(match[1])
    const end = Number(match[2])
    if (end > start) {
      let flag = false
      for (let r = start; r <= end; ++r) {
        if (ruler.replace(/\d+~\d+/, `${r}`) === str) {
          flag = true
          break
        }
      }
      if (flag) {
        return true
      }
    }
  }
  return false
}

function randomRGB (): string {
  const r = Math.floor(Math.random() * 256)
  const g = Math.floor(Math.random() * 256)
  const b = Math.floor(Math.random() * 256)
  const rgb: string = `rgb(${r},${g},${b})`
  return rgb
}

export const getIndexArr = (l: number): number[] => new Array(l).fill(null).map((_: null, i: number) => i + 1)

export const getView = (): string => window.webb.store.get('params').$view

export const isFSY = (): boolean => window.webb.store.get('params').$view === 'FSY'

export const isCapV2 = (): boolean => window.webb.store.get('params').model.station?.[getView()].cap_version === 'v2'
export const getVesselConfig = (vesslResourceType: string): any => window.webb.store.get('params').model.vessel?.[vesslResourceType]
export const getSuppotCapResourceTypes = (vesselType: string): string [] => getVesselConfig(vesselType)?.suppot_cap_resource_type || []
export const getDefaultCapResourceType = (vesselType: string): string => getVesselConfig(vesselType)?.default_cap_resource_type || ''
export {
  getMessageFromError,
  emailToName,
  delay,
  insertProp,
  matchRangeStr,
  getProp,
  randomRGB
}
