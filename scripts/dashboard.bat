@echo off
REM پنل محلی ربات — حافظهٔ ربات را از گیت‌هاب می‌کشد، داشبورد را بالا می‌آورد و
REM مرورگر را باز می‌کند.
REM
REM چرا .bat و نه اپ دسکتاپ: داشبورد از قبل یک اپ Flask کامل با سه صفحه است.
REM یک wrapper دسکتاپ (Electron/pywebview) فقط وابستگی و داستان بسته‌بندی اضافه
REM می‌کند برای UIای که در مرورگر کار می‌کند. یک shortcut به همین فایل همان
REM «آیکون روی صفحه که پنل می‌آورد» است.
REM
REM ساختن آیکون: روی این فایل راست‌کلیک → Send to → Desktop (create shortcut).
REM بعد روی shortcut راست‌کلیک → Properties → Change Icon برای آیکون دلخواه.

setlocal
cd /d "%~dp0.."

echo.
echo   ربات ترید — پنل محلی
echo   ======================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo   [خطا] python در PATH پیدا نشد. از python.org نصبش کن.
    pause
    exit /b 1
)

echo   [1/3] بررسی وابستگی‌ها...
python -c "import flask" >nul 2>nul
if errorlevel 1 (
    echo         نصب وابستگی‌ها برای اولین بار...
    python -m pip install -q -r requirements.txt
)

echo   [2/3] دریافت آخرین حافظهٔ ربات از گیت‌هاب...
if not exist data mkdir data
git fetch --depth=1 origin paper-trading-state >nul 2>nul
if errorlevel 1 (
    echo         [هشدار] شاخهٔ paper-trading-state دریافت نشد — با دادهٔ محلی ادامه می‌دهیم.
) else (
    git archive FETCH_HEAD | tar -x -C data
    echo         حافظه به‌روز شد.
)

echo   [3/3] اجرای داشبورد روی http://127.0.0.1:5000
echo.
echo   مرورگر خودش باز می‌شود. برای بستن، این پنجره را Ctrl+C کن.
echo.

start "" http://127.0.0.1:5000
python scripts/run_dashboard.py --host 127.0.0.1 --port 5000

endlocal
