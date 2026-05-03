@echo off
setlocal

:: Activate virtual environment if it exists
if exist "venv\Scripts\activate.bat" (
    call "venv\Scripts\activate.bat"
)

:: Run the engine
python "body\kid.py" %*
