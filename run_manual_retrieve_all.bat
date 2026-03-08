@echo off
setlocal
chcp 65001 >nul

REM =========================
REM Manual retrieve test runner
REM ASCII-only batch file to avoid cmd encoding issues
REM =========================
set "KB_ID=kb_e0607e15056e4718"
set "QUERY=RAG\u7cfb\u7edf\u662f\u4ec0\u4e48"

echo.
echo ==========================================
echo RAG Retrieve Manual Test
echo KB_ID  = %KB_ID%
echo QUERY  = %QUERY%
echo ==========================================
echo.

call :run json_basic
call :run json_no_reranker
call :run json_no_context
call :run json_with_rewrite
call :run json_with_rewrite_debug
call :run json_strict_threshold
call :run sse_basic
call :run sse_with_rewrite
call :run sse_with_rewrite_debug

echo.
echo ==========================================
echo All scenarios finished
echo ==========================================
echo.
pause
exit /b 0

:run
set "SCENARIO=%~1"
echo.
echo ------------------------------------------
echo Running scenario: %SCENARIO%
echo ------------------------------------------
python manual_retrieve_test.py --kb "%KB_ID%" --query "%QUERY%" --scenario %SCENARIO%
if errorlevel 1 (
  echo [WARN] Scenario failed: %SCENARIO%
)
echo.
exit /b 0
