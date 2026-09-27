# Mallow

**Mallow** is a live win-probability model for *Command & Conquer: Generals Zero Hour*. A gradient boosting classifier reads the state of a running 1v1 match, and estimates the probability that each player wins, drawing it as a bar across the top of the screen:

![](/mallow/screen.jpg)

The shipped model scores **0.85 AUC** at match halftime on held-out games.

## How it works

Mallow is two halves that talk through two files in the game's document directory

```
  game  -->  state.csv        one row per player per second of game time, truncated at every match start
  python -->  GBM  -->  prediction.txt    "0.783 Player_A Player_B"
  game  <--  prediction.txt   read once a second, drawn as the winner bar
```

## Usage

1. **Build the game** from this repository (it carries the exporter and the overlay; see the
   [parent project's build instructions](https://github.com/TheSuperHackers/GeneralsGameCode#quick-start)),
   and install it over your Zero Hour.

2. **Install the Python dependencies:**

   ```bash
   pip install -r mallow/requirements.txt
   ```

3. **Start the predictor:**

   ```bash
   python mallow/mallow.py
   ```


4. **Launch the game and start a local 1v1 match or replay.** The bar appears at the top of the screen within a few seconds
   and updates as the match develops; it disappears when the match ends. This tool is not intended for online use.


## Licence and credits

EA has not endorsed and does not support this product. All trademarks are the property of their respective owners.

This project is licensed under the GPL-3.0 License, which allows you to freely modify and distribute the source code under the terms of this license. Please see LICENSE.md for details.

* Game source and the base engine: [TheSuperHackers/GeneralsGameCode](https://github.com/TheSuperHackers/GeneralsGameCode)
* Mallow — the win-probability model, the exporter and the overlay: [6emmes](https://github.com/6emmes/Mallow)
