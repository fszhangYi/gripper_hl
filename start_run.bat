@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title gripper_hl run :7021
call "%~dp0..\scripts\env_python.bat" || goto :fail

if not exist "%~dp0sensors" (
  echo [gripper-hl] creating junction sensors -^> ..\sensors
  mklink /J "%~dp0sensors" "%~dp0..\sensors" >nul
)

REM Live Modbus COM — set endpoint in configs\sensors_gripper.yaml first
echo [gripper-hl] run --no-dry-run  http://127.0.0.1:7021/
gripper-hl web -c configs\default.yaml --no-dry-run
set "ERR=%ERRORLEVEL%"
goto :end

:fail
set "ERR=1"
:end
echo.
echo Exit code %ERR%. Press any key to close.
pause >nul
exit /b %ERR%
