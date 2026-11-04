# Poker Night

Online poker for friends: Texas, 999, 1 3 5, Theenpathi and Omaha.
200 chips each, blinds 1/2, the small blind picks the game each hand.

## Run

```
py -m pip install -r requirements.txt
py server.py
```

Open http://localhost:8080, enter a nickname, **Start a new game**, and share the 5-letter code
(tap CODE at the top right to copy an invite link). Everyone joins as a watcher and taps an empty
**SIT** seat; the host accepts seat requests (approval can be switched off). The host presses **Start game**.

## The table

Dark room with a green oval table and 8 seats. Each seat plate shows the name, stack, hands won (green 🏆)
and rebuys (red ↻); the player to act turns white with a timer bar. Action bubbles and bet chips sit in
front of each seat, the pot is above the board, and the dealer button moves round the table.
Bottom left: **Log / Ledger** and chat with reactions. Bottom right: FOLD / CHECK·CALL / RAISE
(raise panel with MIN, ½ POT, ¾ POT, POT, ALL IN, slider, − / + and a typed amount), and pre-actions
(CHECK / FOLD, CHECK, CALL ANY) while you wait. Keyboard: F fold, C check/call, R raise.

**Options** (top left): buy in, away / I'm back, leave seat, show cards, log/ledger, rules, invite link,
preferences (sounds, four-colour deck, amounts in big blinds). Host: start, pause / resume, game settings
(blinds, ante, buy-in, turn time, showdown time, seat approval — mid-hand changes apply next hand),
and a player list to accept/decline seats, make someone host or remove a player.

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
Seated players can buy in for another stack at any time **except during a hand they were dealt into**.
**Leave seat** cashes out your stack (recorded as a buy-out; mid-hand it happens when the hand ends)
and makes you a watcher; sitting down again buys back in.
The **Ledger** button shows buy-in, buy-out, stack and net per player (sortable, with a timed history
under Details) and downloads it as a CSV. When the turn timer (30 s default) runs out you check or fold; disconnected players likewise
and can return by refreshing or rejoining with the same name.

## Tests

```
py test_game.py
```
