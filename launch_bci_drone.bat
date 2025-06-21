@echo off
REM launch_bci_drone.bat - Launcher for Dual Model BCI Drone Control

echo ============================================================
echo DUAL MODEL BCI DRONE CONTROL LAUNCHER
echo ============================================================
echo.
echo Models:
echo   3-Class: Left/Right Fist - Rotate Control
echo   8-Class: Push - Takeoff/Land
echo.

REM Check if we should run in live mode
echo Select mode:
echo 1. TEST mode (drone won't fly)
echo 2. LIVE mode (drone WILL fly!)
echo.
set /p mode="Enter 1 or 2: "

if "%mode%"=="2" (
    echo.
    echo WARNING: LIVE MODE - Drone will actually fly!
    set /p confirm="Are you sure? (yes/no): "
    if /i not "!confirm!"=="yes" (
        echo Aborted.
        pause
        exit /b
    )
    set DRONE_MODE=--live
) else (
    set DRONE_MODE=--live
)

echo.
echo Starting components...
echo ------------------------------------------------------------

REM Start drone controller in new window
echo.
echo 1. Starting Drone Controller (Python 2.7)...
start "Drone Controller" cmd /k "conda activate tello_py27 && python C:\Users\silve\Tello-Python\neurosity_tello\neurosity_tello_fourth_draft\drone_controller.py %DRONE_MODE%"

REM Wait a bit
timeout /t 3 /nobreak > nul

REM Start BCI bridge in new window
echo 2. Starting Dual Model BCI Bridge (Python 3)...
start "BCI Bridge" cmd /k "F:\huggingface_transformers_course\transformers_env\python.exe C:\Users\silve\Tello-Python\neurosity_tello\neurosity_tello_fourth_draft\neurosity_bci_bridge.py"

REM Wait for server to start
echo 3. Waiting for web server...
timeout /t 5 /nobreak > nul

REM Open dashboard
echo 4. Opening dashboard in browser...
start http://127.0.0.1:5001/

echo.
echo ============================================================
echo SYSTEM RUNNING!
echo ============================================================
echo.
echo Dashboard: http://127.0.0.1:5001/
echo.
echo Active BCI Controls:
echo   3-Class Model:
echo     - Left Fist (1.5s)  = Rotate Left 45°
echo     - Right Fist (1.5s) = Rotate Right 45°
echo   8-Class Model:
echo     - Push (2s) = Takeoff/Land (toggle)
echo.
echo Future Commands (disabled):
echo   Pull=Back, Lift=Up, Drop=Down, Tongue=Forward
echo.
echo Close this window to stop all components
echo ============================================================
echo.

REM Keep this window open
echo Press Ctrl+C to stop all components...
pause > nul

REM When user closes, kill the other windows
echo.
echo Shutting down...
taskkill /FI "WindowTitle eq Drone Controller*" /T /F 2>nul
taskkill /FI "WindowTitle eq BCI Bridge*" /T /F 2>nul
echo Done.
timeout /t 2 /nobreak > nul
