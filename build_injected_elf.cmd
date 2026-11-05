@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul
if errorlevel 1 (
    py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul
    if errorlevel 1 (
        echo Python 3.8 or newer is required. Install Python and enable its PATH option.
        set "usm_build_status=1"
        goto build_finished
    )
    py -3 "%~dp0build_injected_elf.py" %*
) else (
    python "%~dp0build_injected_elf.py" %*
)
set "usm_build_status=%errorlevel%"
:build_finished
if not "%usm_build_status%"=="0" echo Build failed. See the error above.
if "%~1"=="" pause
popd
exit /b %usm_build_status%
