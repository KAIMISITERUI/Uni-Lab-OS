/**
 * 功能:
 *   托盘 SVG 资源注册表. 仅保留 NTU 站点用到的托盘型号(201000502/503/512/600/711/712/726/727/728/730/731/220000023).
 *   原文件含全部站点 (近 1700 行), 此处裁剪后仅保留 NTU.
 * 主要导出:
 *   TraySvgMap: 托盘型号 -> { tray_front, tray_right } SVG 字符串映射, 供 BaseTray.extendModel 消费.
 */

import _201000502_front from 'Models/NTU/201000502_front.svg'
import _201000502_right from 'Models/NTU/201000502_right.svg'

import _201000503_front from 'Models/NTU/201000503_front.svg'
import _201000503_right from 'Models/NTU/201000503_right.svg'

import _201000512_front from 'Models/NTU/201000512_front.svg'
import _201000512_right from 'Models/NTU/201000512_right.svg'

import _201000600_front from 'Models/NTU/201000600_front.svg'
import _201000600_right from 'Models/NTU/201000600_right.svg'

import _201000711_front from 'Models/NTU/201000711_front.svg'
import _201000711_right from 'Models/NTU/201000711_right.svg'

import _201000712_front from 'Models/NTU/201000712_front.svg'
import _201000712_right from 'Models/NTU/201000712_right.svg'

import _201000726_front from 'Models/NTU/201000726_front.svg'
import _201000726_right from 'Models/NTU/201000726_right.svg'

import _201000727_front from 'Models/NTU/201000727_front.svg'
import _201000727_right from 'Models/NTU/201000727_right.svg'

import _201000728_front from 'Models/NTU/201000728_front.svg'
import _201000728_right from 'Models/NTU/201000728_right.svg'

import _201000730_front from 'Models/NTU/201000730_front.svg'
import _201000730_right from 'Models/NTU/201000730_right.svg'

import _201000731_front from 'Models/NTU/201000731_front.svg'
import _201000731_right from 'Models/NTU/201000731_right.svg'

import _220000023_front from 'Models/NTU/220000023_front.svg'
import _220000023_right from 'Models/NTU/220000023_right.svg'

export interface TraySvgItem {
  tray_front: any;
  tray_right: any;
  tray_back?: any;
  tray_left?: any;
  tray_front_2d?: any;
  tray_right_2d?: any;
  tray_left_2d?: any;
  tray_back_2d?: any;
  [propName: string]: any;
}
export interface TraySvgType extends Record<string, TraySvgItem> {}

export const NTU: TraySvgType = {
  201000502: { tray_front: _201000502_front, tray_right: _201000502_right },
  201000503: { tray_front: _201000503_front, tray_right: _201000503_right },
  201000512: { tray_front: _201000512_front, tray_right: _201000512_right },
  201000600: { tray_front: _201000600_front, tray_right: _201000600_right },
  201000711: { tray_front: _201000711_front, tray_right: _201000711_right },
  201000712: { tray_front: _201000712_front, tray_right: _201000712_right },
  201000726: { tray_front: _201000726_front, tray_right: _201000726_right },
  201000727: { tray_front: _201000727_front, tray_right: _201000727_right },
  201000728: { tray_front: _201000728_front, tray_right: _201000728_right },
  201000730: { tray_front: _201000730_front, tray_right: _201000730_right },
  201000731: { tray_front: _201000731_front, tray_right: _201000731_right },
  220000023: { tray_front: _220000023_front, tray_right: _220000023_right }
}

export const TraySvgMap: TraySvgType = {
  ...NTU
}
