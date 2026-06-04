@echo off
title BeBetter Coaching App
cd /d "%~dp0"

echo ============================================
echo   BeBetter Coaching App opstarten...
echo ============================================
echo.

REM Controleer of ANTHROPIC_API_KEY is ingesteld
if "%ANTHROPIC_API_KEY%"=="" (
    echo FOUT: ANTHROPIC_API_KEY is niet ingesteld.
    echo.
    echo Stel de API key in via:
    echo   Systeeminstellingen ^> Geavanceerd ^> Omgevingsvariabelen
    echo   Naam: ANTHROPIC_API_KEY
    echo   Waarde: sk-ant-...
    echo.
    pause
    exit /b 1
)

REM Start de Streamlit app
python -m streamlit run main.py --server.headless false

pause
