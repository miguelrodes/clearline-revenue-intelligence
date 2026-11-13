"""Restore the registered demo. Original data and rehearsal archives are preserved."""
from pathlib import Path
import os,sys
root=Path(__file__).resolve().parents[1]
python=root/'.venv/bin/python'
if not python.exists():raise SystemExit('Create the project virtual environment first.')
os.chdir(root)
os.execv(str(python),[str(python),'-m','clearline.demo','reset'])
