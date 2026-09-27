@echo off
chcp 65001 > nul
title Discord Role Code Bot

echo ===================================================
echo     Запуск Discord бота (Генератор кодов и ролей)
echo ===================================================
echo.

where py >nul 2>nul
if %ERRORLEVEL% equ 0 (
    py bot.py
) else (
    where python >nul 2>nul
    if %ERRORLEVEL% equ 0 (
        python bot.py
    ) else (
        echo [ОШИБКА] Python не найден в системе!
        echo Пожалуйста, установите Python с сайта python.org
        pause
        exit /b 1
    )
)

pause
