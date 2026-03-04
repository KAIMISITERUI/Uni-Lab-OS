#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    提前构建 index.json 链路已移除.
    该测试文件仅保留兼容入口.
参数:
    无.
返回:
    无.
"""

import unittest


class TestNistStructureIndexBuilderDeprecated(unittest.TestCase):
    """
    功能:
        标记提前索引链路已废弃.
    参数:
        无.
    返回:
        无.
    """

    @unittest.skip("提前构建 index.json 功能已移除")
    def test_index_builder_removed(self) -> None:
        """
        功能:
            占位测试, 表示该链路已移除.
        参数:
            无.
        返回:
            无.
        """
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
