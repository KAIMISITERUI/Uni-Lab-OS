#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能:
    覆盖合成工站全部任务列表的分页获取逻辑.
参数:
    无.
返回:
    无.
"""

import unittest
from unittest.mock import MagicMock

from eit_synthesis_station.controller.station_controller import SynthesisStationController
from eit_synthesis_station.driver.exceptions import ValidationError


class TestTaskListPagination(unittest.TestCase):
    """
    功能:
        验证 get_all_tasks 按 200 条批次分页获取并合并任务列表.
    参数:
        无.
    返回:
        无.
    """

    def _build_controller(self) -> SynthesisStationController:
        """
        功能:
            构造最小可用的控制器测试实例.
        参数:
            无.
        返回:
            SynthesisStationController, 测试控制器实例.
        """
        controller = SynthesisStationController.__new__(SynthesisStationController)
        controller._logger = MagicMock()
        return controller

    def _build_tasks(self, start: int, count: int) -> list[dict]:
        """
        功能:
            构造连续 task_id 的任务列表.
        参数:
            start: int, 起始任务 id.
            count: int, 任务数量.
        返回:
            list[dict], 任务列表.
        """
        return [{"task_id": start + index} for index in range(count)]

    def test_get_all_tasks_returns_empty_list_when_total_is_zero(self) -> None:
        """
        功能:
            验证任务总数为 0 时直接返回空任务列表.
        参数:
            无.
        返回:
            None.
        """
        controller = self._build_controller()
        controller.get_task_list = MagicMock(return_value={"task_sums": 0, "task_list": []})

        result = controller.get_all_tasks()

        self.assertEqual({"task_list": [], "task_sums": 0}, result)
        controller.get_task_list.assert_called_once_with(limit=1, offset=0, sort="desc")

    def test_get_all_tasks_fetches_multiple_batches(self) -> None:
        """
        功能:
            验证 450 条任务会按 200,200,50 三批分页获取.
        参数:
            无.
        返回:
            None.
        """
        controller = self._build_controller()

        def _fake_get_task_list(*, limit: int, offset: int, sort: str) -> dict:
            if limit == 1 and offset == 0:
                return {"task_sums": 450, "task_list": self._build_tasks(0, 1)}
            return {"task_sums": 450, "task_list": self._build_tasks(offset, limit)}

        controller.get_task_list = MagicMock(side_effect=_fake_get_task_list)

        result = controller.get_all_tasks()

        self.assertEqual(450, result["task_sums"])
        self.assertEqual(450, len(result["task_list"]))
        self.assertEqual({"task_id": 0}, result["task_list"][0])
        self.assertEqual({"task_id": 449}, result["task_list"][-1])
        self.assertEqual(
            [
                unittest.mock.call(limit=1, offset=0, sort="desc"),
                unittest.mock.call(limit=200, offset=0, sort="desc"),
                unittest.mock.call(limit=200, offset=200, sort="desc"),
                unittest.mock.call(limit=50, offset=400, sort="desc"),
            ],
            controller.get_task_list.call_args_list,
        )

    def test_get_all_tasks_fetches_single_full_batch(self) -> None:
        """
        功能:
            验证 200 条任务只触发一次 200 条分页请求.
        参数:
            无.
        返回:
            None.
        """
        controller = self._build_controller()

        def _fake_get_task_list(*, limit: int, offset: int, sort: str) -> dict:
            if limit == 1 and offset == 0:
                return {"task_sums": 200, "task_list": self._build_tasks(0, 1)}
            return {"task_sums": 200, "task_list": self._build_tasks(offset, limit)}

        controller.get_task_list = MagicMock(side_effect=_fake_get_task_list)

        result = controller.get_all_tasks()

        self.assertEqual(200, result["task_sums"])
        self.assertEqual(200, len(result["task_list"]))
        self.assertEqual(
            [
                unittest.mock.call(limit=1, offset=0, sort="desc"),
                unittest.mock.call(limit=200, offset=0, sort="desc"),
            ],
            controller.get_task_list.call_args_list,
        )

    def test_get_all_tasks_raises_when_batch_returns_empty_list(self) -> None:
        """
        功能:
            验证未获取完总数时遇到空批次会抛出异常.
        参数:
            无.
        返回:
            None.
        """
        controller = self._build_controller()

        def _fake_get_task_list(*, limit: int, offset: int, sort: str) -> dict:
            if limit == 1 and offset == 0:
                return {"task_sums": 250, "task_list": self._build_tasks(0, 1)}
            if offset == 0:
                return {"task_sums": 250, "task_list": self._build_tasks(0, 200)}
            return {"task_sums": 250, "task_list": []}

        controller.get_task_list = MagicMock(side_effect=_fake_get_task_list)

        with self.assertRaises(ValidationError):
            controller.get_all_tasks()


if __name__ == "__main__":
    unittest.main()
