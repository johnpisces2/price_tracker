@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"
set "ROOT_DIR=%CD%\.."
for %%I in ("%ROOT_DIR%") do set "ROOT_DIR=%%~fI"
set "VENV_DIR=%ROOT_DIR%\.build-venv"
set "DIST_DIR=%ROOT_DIR%\dist"
set "BUILD_DIR=%ROOT_DIR%\build"
set "SCRIPTS_BUILD_DIR=%~dp0build"
set "SCRIPTS_DIST_DIR=%~dp0dist"
set "BOOTSTRAP_PYTHON="

set "MODE=exe"
set "VERSION="

:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="exe" (
  set "MODE=exe"
  shift
  goto parse_args
)
if /i "%~1"=="app" (
  set "MODE=exe"
  shift
  goto parse_args
)
if /i "%~1"=="clean" (
  set "MODE=clean"
  shift
  goto parse_args
)
if /i "%~1"=="-v" (
  if "%~2"=="" (
    echo [ERROR] Missing value for -v
    goto usage
  )
  set "VERSION=%~2"
  shift
  shift
  goto parse_args
)
if /i "%~1"=="--version" (
  if "%~2"=="" (
    echo [ERROR] Missing value for --version
    goto usage
  )
  set "VERSION=%~2"
  shift
  shift
  goto parse_args
)
if /i "%~1"=="-h" goto usage
if /i "%~1"=="--help" goto usage
if /i "%~1"=="help" goto usage

echo [ERROR] Unknown argument: %~1
goto usage

:args_done
if /i "%MODE%"=="clean" goto do_clean

set "APP_NAME=PriceTracker"
set "APP_BASENAME=%APP_NAME%"
if not "%VERSION%"=="" set "APP_BASENAME=%APP_NAME%-%VERSION%"
set "SPEC_FILE=%~dp0PriceTracker.win.spec"
if not exist "%SPEC_FILE%" (
  echo [ERROR] Spec file not found: "%SPEC_FILE%"
  exit /b 1
)

if not exist "%VENV_DIR%" (
  call :resolve_bootstrap_python
  if errorlevel 1 exit /b 1

  if "!BOOTSTRAP_PYTHON!"=="" (
    echo [ERROR] Bootstrap CPython path is empty.
    echo [HINT] Set PRICE_TRACKER_CPYTHON to a valid python.exe path.
    exit /b 1
  )

  echo [INFO] Creating build venv with "!BOOTSTRAP_PYTHON!"
  "!BOOTSTRAP_PYTHON!" -m venv "%VENV_DIR%"
  if errorlevel 1 (
    echo [ERROR] Failed to create venv at "%VENV_DIR%"
    exit /b 1
  )
)

set "PYTHON=%VENV_DIR%\Scripts\python.exe"
set "PIP=%VENV_DIR%\Scripts\pip.exe"

set "PY_HOME="
for /f "usebackq tokens=1,* delims==" %%A in ("%VENV_DIR%\pyvenv.cfg") do (
  if /i "%%A"=="home " set "PY_HOME=%%B"
)
if defined PY_HOME if "%PY_HOME:~0,1%"==" " set "PY_HOME=%PY_HOME:~1%"
if defined PY_HOME (
  if /i not "%PY_HOME:conda=%"=="%PY_HOME%" (
    echo [ERROR] .build-venv was created from Conda Python: "%PY_HOME%"
    echo [ERROR] Please run "scripts\build_windows.bat clean" first.
    echo [ERROR] Then rebuild with CPython from python.org.
    echo [HINT] Or set PRICE_TRACKER_CPYTHON to a CPython python.exe path.
    exit /b 1
  )
)

"%PYTHON%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 exit /b 1
"%PIP%" install -r "%ROOT_DIR%\requirements.txt" pyinstaller
if errorlevel 1 exit /b 1

if defined PY_HOME (
  set "PATH=%VENV_DIR%\Scripts;%PY_HOME%;%PY_HOME%\DLLs;%PY_HOME%\Library\bin;%SystemRoot%\System32;%SystemRoot%"
) else (
  set "PATH=%VENV_DIR%\Scripts;%SystemRoot%\System32;%SystemRoot%;%PATH%"
)

set "PRICE_TRACKER_APP_NAME=%APP_BASENAME%"
pushd "%ROOT_DIR%"
"%PYTHON%" -m PyInstaller --noconfirm --clean "%SPEC_FILE%"
if errorlevel 1 (
  popd
  exit /b 1
)
popd

set "APP_DIR=%DIST_DIR%\%APP_BASENAME%"
if exist "%APP_DIR%\settings.json" del /f /q "%APP_DIR%\settings.json"
for %%F in ("%APP_DIR%\settings.*.json") do (
  if exist "%%~fF" del /f /q "%%~fF"
)
if exist "%DIST_DIR%\settings.json" del /f /q "%DIST_DIR%\settings.json"
for %%F in ("%DIST_DIR%\settings.*.json") do (
  if exist "%%~fF" del /f /q "%%~fF"
)

endlocal
exit /b 0

:resolve_bootstrap_python
set "BOOTSTRAP_PYTHON="
set "MANUAL_PY=%PRICE_TRACKER_CPYTHON%"
if defined MANUAL_PY set "MANUAL_PY=%MANUAL_PY:"=%"
if defined MANUAL_PY if not "%MANUAL_PY%"=="" (
  for %%I in ("%MANUAL_PY%") do set "MANUAL_PY=%%~fI"
  if exist "%MANUAL_PY%" (
    set "BOOTSTRAP_PYTHON=%MANUAL_PY%"
    exit /b 0
  )
  echo [ERROR] PRICE_TRACKER_CPYTHON does not exist: "%MANUAL_PY%"
  exit /b 1
)

for %%I in (
  "%LocalAppData%\Programs\Python\Python313\python.exe"
  "%LocalAppData%\Programs\Python\Python312\python.exe"
  "%LocalAppData%\Programs\Python\Python311\python.exe"
  "%ProgramFiles%\Python313\python.exe"
  "%ProgramFiles%\Python312\python.exe"
  "%ProgramFiles%\Python311\python.exe"
  "%ProgramFiles(x86)%\Python313\python.exe"
  "%ProgramFiles(x86)%\Python312\python.exe"
  "%ProgramFiles(x86)%\Python311\python.exe"
) do (
  if exist "%%~I" (
    set "BOOTSTRAP_PYTHON=%%~fI"
    exit /b 0
  )
)

echo [ERROR] CPython (python.org) not found.
echo [HINT] Install CPython 3.11+ or set PRICE_TRACKER_CPYTHON to python.exe path.
exit /b 1

:do_clean
echo [INFO] Cleaning build artifacts...
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"
if exist "%VENV_DIR%" rmdir /s /q "%VENV_DIR%"
if exist "%SCRIPTS_BUILD_DIR%" rmdir /s /q "%SCRIPTS_BUILD_DIR%"
if exist "%SCRIPTS_DIST_DIR%" rmdir /s /q "%SCRIPTS_DIST_DIR%"
echo [OK] Clean complete
endlocal
exit /b 0

:usage
echo Usage: %~nx0 [exe^|clean] [-v VERSION]
echo.
echo Modes:
echo   exe                Build Windows exe (default)
echo   clean              Remove build artifacts (.build-venv, build/dist, scripts/build/dist)
echo.
echo Options:
echo   -v, --version VER  Append version to artifact name (PriceTracker-VER.exe)
endlocal
exit /b 1
