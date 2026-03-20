#!/bin/bash
echo "Starting HumanOptimizer..."

# Start backend
echo "Starting Backend (FastAPI) on port 8000..."
python -m uvicorn app.main:app --reload --port 8000 &
BACKEND_PID=$!

sleep 2

# Start frontend
echo "Starting Frontend (Streamlit) on port 8501..."
python -m streamlit run frontend/app.py --server.port 8501 &
FRONTEND_PID=$!

echo ""
echo "========================================"
echo "HumanOptimizer is running!"
echo "Backend:  http://localhost:8000/docs"
echo "Frontend: http://localhost:8501"
echo "========================================"
echo ""
echo "Press Ctrl+C to stop both servers."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT
wait
