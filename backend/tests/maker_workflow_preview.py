"""Isolated browser acceptance: real cloud AI, synthetic camera, no Pi actions.

python -m tests.maker_workflow_preview; localhost:18762 has separate browser
storage from the user's main workspace. Never import into production.
"""
import uvicorn
from fastapi import HTTPException
from fastapi.routing import APIRoute
from tests.wiring_guide_preview import app


async def no_pi_action(path: str):
    raise HTTPException(403, 'Isolated workflow test: Pi actions are disabled')


app.router.routes.insert(0, APIRoute('/api/pi/{path:path}', no_pi_action, methods=['POST']))

if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=18762, timeout_graceful_shutdown=1)
