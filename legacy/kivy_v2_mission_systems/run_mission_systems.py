"""Run from the project directory: python run_mission_systems.py"""
import uvicorn
from mission_systems.api import create_app

if __name__ == '__main__':
    print('AETHER Mission Systems: http://127.0.0.1:8000/docs')
    uvicorn.run(create_app(), host='127.0.0.1', port=8000)
