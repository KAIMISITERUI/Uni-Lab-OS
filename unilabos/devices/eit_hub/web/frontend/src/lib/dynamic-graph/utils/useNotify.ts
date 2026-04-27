import { useQuasar, QVueGlobals } from 'quasar'
import { format } from 'date-fns'
import { getMessageFromError, ErrorObject } from 'Utils/utils'

export enum NotifyType {
  Positive = 'positive',
  Negative = 'negative',
  Warning = 'warning',
  Info = 'info',
  Ongoing = 'ongoing'
}

interface UseNotify {
  notifyInfo (info: string, type?: NotifyType, groupKey?: string, timeout?: number, closeBtn?: boolean): void;
  notifyError (err: any, groupKey?: string, preset?: string, timeout?: number, closeBtn?: boolean): void;
  notifySuccess (info: string, groupKey?: string, timeout?: number, closeBtn?: boolean): void;
}

export default function useNotify (q?: QVueGlobals): UseNotify {
  const $q = q || window.$q || useQuasar()

  const notifyInfo = (
    info: string,
    type: NotifyType = NotifyType.Warning,
    groupKey: string = '',
    timeout: number = 5 * 60 * 1000,
    closeBtn: boolean = true
  ): void => {
    $q?.notify?.({
      type,
      group: groupKey,
      timeout,
      closeBtn,
      html: true,
      position: 'top',
      message: `<div style="max-width:300px;white-space:normal;word-break:break-word;overflow:hidden;">
        ${info}</div>
        <div style="font-size:12px;text-align:right;">${format(new Date(), 'yyyy-MM-dd HH:mm:ss')}</div>
      `
    })
  }

  const notifyError = (err: any, groupKey: string = '', preset: string = '', timeout: number = 5 * 60 * 1000, closeBtn: boolean = true): void => {
    const errInfo = getMessageFromError(err as ErrorObject, preset)
    notifyInfo(errInfo, NotifyType.Warning, groupKey, timeout, closeBtn)
  }

  const notifySuccess = (info: string, groupKey: string = '', timeout: number = 2 * 1000, closeBtn: boolean = false): void => {
    notifyInfo(info, NotifyType.Positive, groupKey, timeout, closeBtn)
  }

  return {
    notifyInfo,
    notifyError,
    notifySuccess
  }
}
