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

from game import Game, STREETS, HOST_GRACE

MAX_MEMBERS = 30         # players + watchers in one game
NEXT_HAND_DELAY = 9      # seconds the showdown stays on screen
DISCONNECT_GRACE = 20    # seconds before a disconnected player is auto-checked/folded

PUBLIC = Path(__file__).parent / 'public'


class Room:
    def __init__(self, code):
        self.game = Game(code)
        self.sockets = {}     # player id -> websocket
        self.timer = None
        self.host_timer = None
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


async def send_and_close(ws, msg):
    await send(ws, msg)
    await ws.close()


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
    loop = asyncio.get_running_loop()
    if room.host_timer:
        room.host_timer.cancel()
        room.host_timer = None
    host = g.find(g.host_id)
    if host and not host.connected:   # pass hosting on if the host doesn't come back in time
        wait = max(0, host.left_at + HOST_GRACE - time.time()) + 0.5
        room.host_timer = loop.call_later(wait, lambda: asyncio.ensure_future(broadcast(room)))
    if g.paused:
        return
    if g.phase == 'handover' and g.can_start_hand():
        room.timer = loop.call_later(NEXT_HAND_DELAY, fire, room, 'next', None)
    elif g.phase == 'declare':
        delay = max(0, g.declare_deadline - time.time())
        room.timer = loop.call_later(delay, fire, room, 'declare', g.hand_no)
    elif g.phase in STREETS + ['choosing'] and g.to_act >= 0:
        delays = []
        if g.turn_deadline:
            delays.append(max(0, g.turn_deadline - time.time()))
        if not g.players[g.to_act].connected:
            delays.append(DISCONNECT_GRACE)
        if delays:
            key = (g.hand_no, g.phase, g.to_act, g.turn_deadline)
            room.timer = loop.call_later(min(delays) + 0.1, fire, room, 'auto', key)


def fire(room, kind, key):
    room.timer = None
    g = room.game
    if g.paused:
        pass
    elif kind == 'next' and g.phase == 'handover':
        g.start_hand()
    elif kind == 'auto' and key == (g.hand_no, g.phase, g.to_act, g.turn_deadline):
        p = g.players[g.to_act]
        if g.phase == 'choosing' or p.connected:
            g.note(f'{p.name} ran out of time')
        g.auto_act()
    elif kind == 'declare' and key == g.hand_no:
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
            player.left_at = time.time()
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
        return room, room.game.add_member(name)
    code = str(data.get('code', '')).strip().upper()
    room = rooms.get(code)
    if room is None:
        raise ValueError(f'No game with code {code}')
    g = room.game
    if data['type'] == 'resume':
        p = next((p for p in g.members if p.token == data.get('token')), None)
        if p is None:
            raise ValueError('Your seat is no longer available')
        if p.kicked:
            raise ValueError('The host removed you from this game')
        if p.id in room.sockets:  # an older tab is still open: take over
            asyncio.ensure_future(room.sockets[p.id].close())
        g.note(f'{p.name} reconnected')
        return room, p
    if not name:
        raise ValueError('Enter your name')
    same = next((p for p in g.members if p.name.lower() == name.lower()), None)
    if same and same.kicked:
        raise ValueError('The host removed you from this game')
    if same and not same.connected:  # lost their tab: rejoining with the same name takes the seat back
        g.note(f'{same.name} reconnected')
        return room, same
    if same:
        raise ValueError('That name is taken at this table')
    if sum(1 for p in g.members if not p.kicked) >= MAX_MEMBERS:
        raise ValueError('This game is full')
    return room, g.add_member(name)


def handle(room, p, t, data):
    g = room.game
    if p.kicked:
        raise ValueError('The host removed you from this game')
    if t == 'start':
        if p.id != g.host_id:
            raise ValueError('Only the host can start the game')
        if g.started:
            raise ValueError('Game already started')
        if not g.start_hand():
            raise ValueError('Need at least 2 seated players with chips' if not g.paused else 'The game is paused')
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
    elif t == 'sit':
        g.request_seat(p, data['seat'])
    elif t == 'unsit':
        g.cancel_request(p)
    elif t == 'answer':
        g.answer_request(p, g.find(data.get('id')), bool(data.get('accept')))
    elif t == 'settings':
        g.update_settings(p, data.get('settings') or {})
    elif t == 'pause':
        g.set_paused(p, bool(data.get('value')))
    elif t == 'makehost':
        g.make_host(p, g.find(data.get('id')))
    elif t == 'show':
        g.show_cards(p, data.get('value', True) is not False)
    elif t == 'emote':
        g.emote_at(p, data.get('e'))
    elif t == 'rebuy':
        g.rebuy(p)
    elif t == 'cashout':
        g.cash_out(p)
    elif t == 'kick':
        target = g.find(data.get('id'))
        g.kick(p, target)
        ws = room.sockets.pop(target.id, None)
        if ws is not None:
            asyncio.ensure_future(send_and_close(ws, {'type': 'kicked', 'message': 'The host removed you from this game'}))
    elif t == 'sitout':
        g.set_sitout(p, data.get('value'))
    elif t == 'chat':
        text = str(data.get('text', '')).strip()[:200]
        if text:
            room.chat.append({'name': p.name, 'id': p.id, 'text': text, 't': time.time()})
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
