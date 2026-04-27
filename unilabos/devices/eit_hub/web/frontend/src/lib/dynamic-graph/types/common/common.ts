export interface CommonParams {
  hostname: string;
  [propName: string]: any;
}

export type CommonFunction = (...args: any[]) => any

export interface Timestamp {
  nanos: number,
  seconds: number
}

export interface CallbackFunc {
  (err?: unknown): void;
}
