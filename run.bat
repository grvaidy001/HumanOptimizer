@echo off
echo Starting HumanOptimizer...
echo.
echo Starting Backend (FastAPI) on port 8000...
start "HumanOptimizer-Backend" cmd /c "cd /d %~dp0 && python -m uvicorn app.main:app --reload --port 8000"
echo.
echo Waiting for backend to start...
timeout /t 3 /nobreak >nul
echo.
echo Starting Frontend (Streamlit) on port 8501...
start "HumanOptimizer-Frontend" cmd /c "cd /d %~dp0 && python -m streamlit run frontend/app.py --server.port 8501"
echo.
echo ========================================
echo HumanOptimizer is running!
echo Backend:  http://localhost:8000/docs
echo Frontend: http://localhost:8501
echo ========================================
