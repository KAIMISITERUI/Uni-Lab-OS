import * as Zrender from 'zrender'

export const HIGHT_COLOR: Zrender.LinearGradient = new Zrender.LinearGradient(0, 0, 1, 0, [
  {
    offset: 0,
    color: '#0A8F58'
  },
  {
    offset: 1,
    color: '#40F2A8'
  }
])

export const HIGHT_COLOR_SELECTED = new Zrender.LinearGradient(0, 0, 1, 0, [
  {
    offset: 0,
    color: '#1239FF'
  },
  {
    offset: 1,
    color: '#41B6F1'
  }
])

export enum M01StationId {
  SS_1='SS_1',
  SS_2='SS_2',
  AGV_1='AGV_1',
  SAS_1='SAS_1',
  SF_1='SF_1',
  SF_2='SF_2',
  BM_1='BM_1',
  TPS_1='TPS_1',
  TTS_1='TTS_1'
}

export enum M01GFZStationId {
  SS_1 = 'SS_1',
  SS_2 = 'SS_2',
  SS_3 = 'SS_3',
  SS_4 = 'SS_4',
  PS_1 = 'PS_1',
  AGV_1='AGV_1'
}

export enum HZSFStationId {
  CHS='CHS'
}

export enum LiangZhuStationId {
  SYN_1 = 'SYN_1',
  PST_1 = 'PST_1',
  DO_1 = 'DO_1',
  ANA_1 = 'ANA_1',
  AGV_1 = 'AGV_1',
  HYD_1 = 'HYD_1',
  SS_1 = 'SS_1',
  SS_2 = 'SS_2'
}
