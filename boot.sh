#!/bin/bash

# Activate virtual environment if it exists
if [ -f "venv/bin/activate" ]; then
    source "venv/bin/activate"
fi

# Run the engine
python3 "body/kid.py" "$@"
