@echo off
title AGV 自动充电监控
echo ============================================
echo  AGV 自动充电监控
echo ============================================
echo.
echo  说明: 本程序持续监控AGV电量状态
echo        AGV在CP6充电站时自动执行充电检查
echo        AGV执行任务时自动等待并稍后重试
echo.
echo  参数: --interval-hours  在CP6完成检查后的等待时间(小时), 默认1
echo        --retry-minutes   不在CP6时的重试间隔(分钟), 默认5
echo.
echo  按 Ctrl+C 停止监控
echo ============================================
echo.

:: 激活 conda base 环境
call conda activate base
if errorlevel 1 (
    echo [错误] conda base 环境激活失败, 请检查conda是否已安装并初始化
    pause
    exit /b 1
)

:: 切换到模块根目录(eit_agv的父目录)
cd /d d:\Uni-Lab-OS\unilabos\devices

:: 以模块方式运行, 确保相对导入正常工作
:: %* 透传所有命令行参数, 例如: start_auto_charge.bat --interval-hours 2
python -m eit_agv.controller.auto_charge_monitor %*

echo.
echo ============================================
echo  充电监控已退出
echo ============================================
pause
