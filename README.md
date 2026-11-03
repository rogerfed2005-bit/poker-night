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

**Showdown (every variation):** once the board is complete (even after an early all-in) each player
still in clicks which of their own hole cards they are playing; the game completes the 5-card hand with
the best board cards and shows a preview. Nobody's cards are chosen for them: you get 60 s to press
Confirm, and a player who doesn't confirm mucks (if nobody in a pot confirms, best hands are used).
The showdown panel then shows, for each player, the hole cards used, the board cards that completed
the hand, the hand name and what they won.

- **Texas** – 2 hole cards; use 0, 1 or 2 of them.
- **999** – 5 hole cards. Pick 3 for your 999 number (10/J/Q/K/A = 0, digits sorted high to low) —
  privately, changeable during the hand, final at showdown; then choose which of the other 2 to use
  for Texas (0, 1 or 2). Half the pot to the best Texas hand, half to the highest number; ties split their half.
- **1 3 5** – 5 hole cards; use exactly 1, 3 or 5 of them (with 4, 2 or 0 board cards).
- **Theenpathi** – like 999, but the 3 cards form a 3-card hand:
  Trail > Straight Flush > Straight > Flush > Pair > High Card (A-K-Q top straight, A-2-3 lowest).
- **Omaha** – 4 hole cards, exactly 2 of them + exactly 3 board cards.

No-limit betting, side pots for all-ins, odd chips go to the first winner left of the dealer.
Heads-up, the dealer posts the small blind. Max 8 players (5-card games need the deck).
Anyone can buy in for another 200 at any time (during a hand the chips arrive when it ends);
the scoreboard shows each player's buy-ins, chips and profit/loss. Disconnected players are auto-checked/folded after 20 s
and can return by refreshing or rejoining with the same name.

## Tests

```
py test_game.py
```
