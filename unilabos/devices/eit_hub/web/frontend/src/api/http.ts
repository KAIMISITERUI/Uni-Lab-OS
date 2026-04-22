import axios, { type AxiosInstance } from 'axios'

const http: AxiosInstance = axios.create({
  baseURL: '',
  timeout: 60000,
})

export function getErrorMessage(error: unknown): string {
  const responseDetail = (error as { response?: { data?: { detail?: string } } })?.response?.data
    ?.detail
  if (typeof responseDetail === 'string' && responseDetail !== '') {
    return responseDetail
  }
  const message = (error as Error)?.message
  if (typeof message === 'string' && message !== '') {
    return message
  }
  return '请求失败'
}

export default http

