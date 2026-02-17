#!/bin/bash
cd /opt/energy-manager
git fetch origin
git reset --hard origin/main                   # auto update from Git
source venv/bin/activate   # activate python env
python3 -u main.py     # run your script