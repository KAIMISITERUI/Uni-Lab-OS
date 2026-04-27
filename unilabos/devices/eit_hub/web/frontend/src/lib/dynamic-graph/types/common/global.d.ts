declare module '@/*' {}
declare module 'Views/*' {}
declare module 'Libs/*' {}
declare module 'Components/*' {}
declare module 'Models/*' {}
declare module 'Resources/*' {}
declare module 'Config/*' {}
declare module 'Tray/*' {}
declare module 'Station/*' {}
declare module 'Api/*' {}
declare module 'Utils/*' {}
declare module 'Assets/*' {}
declare module 'lodash'
declare module 'color'

interface WebbEvent {
  emit(eventName: string, ...args: Array<unknown>): void;
  on(eventName: string, listener: unknown): void;
  once(eventName: string, listener: unknown): void;
  removeListener(eventName: string, listener: unknown): void;
  removeAllListeners(eventName: string): void;
}
interface WebbMethod {
  call <T>(name: string, fnName: string, ...args: Array<unknown>): T;
}

interface Webb {
  getUrl: () => UrlOptions;
  event: WebbEvent;
  method: WebbMethod;
  store: any;
  utils: {
    [key: unknown]: unknown;
    lodash: {[key: string]: any};
    axios: any;
  }
}

interface Window {
  webb: Webb;
}
