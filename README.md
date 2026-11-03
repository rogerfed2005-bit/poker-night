# Poker Night

Online poker for friends: Texas, 999, 1 3 5, Theenpathi and Omaha.
200 chips each, blinds 1/2, the small blind picks the game each hand.

## Run

```
py -m pip install -r requirements.txt
py server.py
```

Open http://localhost:8080, enter a name, **Host a new game**, and share the 5-letter code
(or click the code to copy an invite link). Friends enter the code and **Join**. The host presses **Start**.

## Letting friends connect

`localhost` only works on your machine. Options:

- **Same Wi-Fi:** friends open `http://<your-PC's-IP>:8080` (find it with `ipconfig`; allow Python through Windows Firewall).
- **Quick tunnel from your PC:** `cloudflared tunnel --url http://localhost:8080` (or `ngrok http 8080`) gives a public https link.
- **Always-on hosting:** deploy to Render / Railway / Fly as a Python web service,
  build `pip install -r requirements.txt`, start `python server.py` (it reads `PORT`).

Games live in server memory, so restarting the server ends them.

## Rules as implemented

- **Texas** – 2 hole cards, best 5 of 7.
- **999** – 5 hole cards. Click 3 for your 999 number (10/J/Q/K/A = 0, digits sorted high to low);
  the other 2 play Texas with the board (using 2, 1 or 0 of them). Half the pot to the best Texas hand,
  half to the highest number; ties split their half. Your pick is private and can change freely
  during the hand. At showdown (all 5 board cards out, even after an early all-in) everyone left
  gets 30 s to make a final pick and press Confirm; hands are revealed once all have confirmed.
  If time runs out you keep your current pick, or the 3 cards with the highest number.
- **1 3 5** – 5 hole cards; the hand must use exactly 1, 3 or 5 of them plus 4, 2 or 0 board cards.
- **Theenpathi** – like 999, but the 3 cards form a 3-card hand:
  Trail > Straight Flush > Straight > Flush > Pair > High Card (A-K-Q top straight, A-2-3 lowest).
- **Omaha** – 4 hole cards, exactly 2 of them + exactly 3 board cards.

No-limit betting, side pots for all-ins, odd chips go to the first winner left of the dealer.
Heads-up, the dealer posts the small blind. Max 8 players (5-card games need the deck).
Busted players can rebuy 200. Disconnected players are auto-checked/folded after 20 s
and can return by refreshing or rejoining with the same name.

## Tests

```
py test_game.py
```
