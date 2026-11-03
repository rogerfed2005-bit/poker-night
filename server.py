"""Poker night server: serves the web client and runs games over websockets.

Run:  py server.py          (then open http://localhost:8080)
"""
import asyncio
import json
import os
import random
import string
import time
from pathlib import Path

from aiohttp import web, WSMsgType

from game import Game, STREETS

MAX_PLAYERS = 8          # 5-card variants need 5 cards each + board + burns from one deck
NEXT_HAND_DELAY = 8      # seconds the showdown stays on screen
DISCONNECT_GRACE = 20    # seconds before a disconnected player is auto-checked/folded

PUBLIC = Path(__file__).parent / 'public'


class Room:
    def __init__(self, code):
        self.game = Game(code)
        self.sockets = {}     # player id -> websocket
        self.timer = None
        self.chat = []


rooms = {}


def new_code():
    while True:
        code = ''.join(random.choices(string.ascii_uppercase.replace('O', '').replace('I', ''), k=5))
        if code not in rooms:
            return code


async def send(ws, msg):
    if ws is not None and not ws.closed:
        try:
            await ws.send_str(json.dumps(msg))
        except ConnectionError:
            pass


async def broadcast(room):
    g = room.game
    g.ensure_host()
    for pid, ws in list(room.sockets.items()):
        await send(ws, {'type': 'state', 'state': g.view(pid), 'chat': room.chat[-30:]})
    schedule(room)


def schedule(room):
    """Arm the single per-room timer: next hand after a showdown, or auto-act for a disconnected player."""
    if room.timer:
        room.timer.cancel()
        room.timer = None
    g = room.game
    if g.phase == 'handover' and g.can_start_hand():
        room.timer = asyncio.get_running_loop().call_later(NEXT_HAND_DELAY, fire, room, 'next')
    elif g.phase == 'declare':
        delay = max(0, g.declare_deadline - time.time())
        room.timer = asyncio.get_running_loop().call_later(delay, fire, room, 'declare')
    elif g.phase in STREETS + ['choosing'] and g.to_act >= 0 and not g.players[g.to_act].connected:
        room.timer = asyncio.get_running_loop().call_later(DISCONNECT_GRACE, fire, room, 'auto')


def fire(room, kind):
    room.timer = None
    g = room.game
    if kind == 'next' and g.phase == 'handover':
        g.start_hand()
    elif kind == 'auto' and g.to_act >= 0 and not g.players[g.to_act].connected:
        g.auto_act()
    elif kind == 'declare':
        g.finish_declare()
    asyncio.ensure_future(broadcast(room))


async def ws_handler(request):
    ws = web.WebSocketResponse(heartbeat=25)
    await ws.prepare(request)
    room = player = None
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
                t = data.get('type')
                if t in ('create', 'join', 'resume'):
                    room, player = attach(data, ws)
                    room.sockets[player.id] = ws
                    player.connected = True
                    await send(ws, {'type': 'joined', 'code': room.game.code,
                                    'id': player.id, 'token': player.token})
                elif room is None:
                    raise ValueError('Join a game first')
                else:
                    handle(room, player, t, data)
                await broadcast(room)
            except (ValueError, KeyError, TypeError) as e:
                await send(ws, {'type': 'error', 'message': str(e)})
    finally:
        if room and player and room.sockets.get(player.id) is ws:
            del room.sockets[player.id]
            player.connected = False
            room.game.note(f'{player.name} disconnected')
            await broadcast(room)
    return ws


def attach(data, ws):
    name = str(data.get('name', '')).strip()[:16]
    if data['type'] == 'create':
        if not name:
            raise ValueError('Enter your name')
        code = new_code()
        room = rooms[code] = Room(code)
        return room, room.game.add_player(name)
    code = str(data.get('code', '')).strip().upper()
    room = rooms.get(code)
    if room is None:
        raise ValueError(f'No game with code {code}')
    g = room.game
    if data['type'] == 'resume':
        p = next((p for p in g.players if p.token == data.get('token')), None)
        if p is None:
            raise ValueError('Your seat is no longer available')
        if p.id in room.sockets:  # an older tab is still open: take over
            asyncio.ensure_future(room.sockets[p.id].close())
        g.note(f'{p.name} reconnected')
        return room, p
    if not name:
        raise ValueError('Enter your name')
    same = next((p for p in g.players if p.name.lower() == name.lower()), None)
    if same and not same.connected:  # lost their tab: rejoining with the same name takes the seat back
        g.note(f'{same.name} reconnected')
        return room, same
    if same:
        raise ValueError('That name is taken at this table')
    if len(g.players) >= MAX_PLAYERS:
        raise ValueError(f'Table is full ({MAX_PLAYERS} players max)')
    return room, g.add_player(name)


def handle(room, p, t, data):
    g = room.game
    if t == 'start':
        if p.id != g.host_id:
            raise ValueError('Only the host can start the game')
        if g.started:
            raise ValueError('Game already started')
        if not g.start_hand():
            raise ValueError('Need at least 2 players')
    elif t == 'choose':
        g.choose_variant(p, data['variant'])
    elif t == 'act':
        g.act(p, data['action'], data.get('amount', 0))
    elif t == 'split':
        g.set_split(p, data['idx'])
    elif t == 'use':
        g.set_use(p, data['idx'])
    elif t == 'declare':
        g.declare(p, data['use'], data.get('side'))
    elif t == 'rebuy':
        g.rebuy(p)
    elif t == 'sitout':
        p.sitting_out = bool(data.get('value'))
        g.note(f'{p.name} is {"sitting out" if p.sitting_out else "back"}')
    elif t == 'chat':
        text = str(data.get('text', '')).strip()[:200]
        if text:
            room.chat.append({'name': p.name, 'text': text})
            room.chat = room.chat[-50:]
    else:
        raise ValueError('Unknown message')


async def index(request):
    return web.FileResponse(PUBLIC / 'index.html')


async def no_stale_files(request, response):
    # browsers re-check the page and scripts so everyone gets updates right after a deploy
    if not request.path.startswith('/ws'):
        response.headers['Cache-Control'] = 'no-cache'


def make_app():
    app = web.Application()
    app.on_response_prepare.append(no_stale_files)
    app.router.add_get('/', index)
    app.router.add_get('/ws', ws_handler)
    app.router.add_static('/static', PUBLIC)
    return app


if __name__ == '__main__':
    web.run_app(make_app(), port=int(os.environ.get('PORT', 8080)))
