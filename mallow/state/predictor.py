import os
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import skops.io as sio

from . import features, paths

UPDATE_SEC = 3.0
STALE_SEC = 60.0

BAR_WIDTH = 30
TRUSTED_TYPES = (
    "sklearn.ensemble._hist_gradient_boosting.predictor.TreePredictor",
)


@dataclass
class Model:
    clf: object
    iso: object
    names: list[str]
    extended: bool


@dataclass
class Prediction:
    second: int
    probability: float
    name_a: str
    name_b: str


def load_model(path: Path = paths.MODEL) -> Model:
    bundle = sio.load(str(path), trusted=list(TRUSTED_TYPES))
    return Model(clf=bundle["model"],
                 iso=bundle["iso"],
                 names=bundle.get("features")
                 or features.snapshot_feature_names(),
                 extended=bool(bundle.get("extended")))


def sanitize(name: str) -> str:
    return (name or "?").replace(" ", "_")[:30]


def match_over(match: features.StateMatch, state_csv: Path,
               stale_sec: float = STALE_SEC) -> bool:
    if match.end_frame >= 0:
        return True
    try:
        return (time.time() - os.path.getmtime(state_csv)) > stale_sec
    except OSError:
        return True


def drop_overlay(prediction_txt: Path) -> None:
    try:
        os.remove(prediction_txt)
    except FileNotFoundError:
        pass


def write_overlay(prediction_txt: Path, pred: Prediction) -> None:
    tmp = prediction_txt.with_name(prediction_txt.name + ".tmp")
    with open(tmp, "w", encoding="ascii", errors="replace", newline="\n") as f:
        f.write(f"{pred.probability:.3f} {pred.name_a} {pred.name_b}\n")
    os.replace(tmp, prediction_txt)


def predict(match: features.StateMatch, model: Model) -> Prediction | None:
    players = features.main_players(match)
    if len(players) != 2:
        return None
    pa, pb = players
    
    rows_a, rows_b = match.players[pa]["rows"], match.players[pb]["rows"]
    ts = sorted(set(rows_a) & set(rows_b))
    if not ts:
        return None
    t = ts[-1]

    bases = features.base_centroids(match, pa, pb) if model.extended else None
    row = features.build_snapshot(match, pa, pb, t,
                                  extended=model.extended, bases=bases)
    if row is None:
        return None

    all_names = features.snapshot_feature_names(extended=model.extended)
    frame = pd.DataFrame([row], columns=all_names)[model.names]
    p_b = float(model.iso.predict(model.clf.predict_proba(frame)[:, 1])[0])
    return Prediction(second=t,
                      probability=1.0 - p_b,
                      name_a=sanitize(match.players[pa]["name"]),
                      name_b=sanitize(match.players[pb]["name"]))


def _format_status(pred: Prediction) -> str:
    filled = int(pred.probability * BAR_WIDTH)
    bar = "#" * filled + "-" * (BAR_WIDTH - filled)
    return (f"{pred.second // 60}:{pred.second % 60:02d} {pred.name_a} "
            f"{pred.probability * 100:5.1f}% [{bar}] {pred.name_b}")


class Sidecar:
    def __init__(self, model: Model,
                 state_csv: Path = paths.STATE_CSV,
                 prediction_txt: Path = paths.PREDICTION_TXT,
                 interval: float = UPDATE_SEC,
                 stale_sec: float = STALE_SEC):
        self.model = model
        self.state_csv = Path(state_csv)
        self.prediction_txt = Path(prediction_txt)
        self.interval = interval
        self.stale_sec = stale_sec
        self._start_ts = None
        self._last_second = -1 

    def step(self) -> Prediction | None:
        if not self.state_csv.exists():
            drop_overlay(self.prediction_txt)
            return None

        match = features.parse_state_csv(self.state_csv)
        if match_over(match, self.state_csv, self.stale_sec):
            drop_overlay(self.prediction_txt)
            return None

        if match.start_ts != self._start_ts:
            if self._start_ts is not None:
                print()
            self._start_ts = match.start_ts
            self._last_second = -1
            print(f"\nmatch: {match.map_name or '?'}")

        pred = predict(match, self.model)
        if pred is None or pred.second == self._last_second:
            return None
        self._last_second = pred.second
        write_overlay(self.prediction_txt, pred)
        print(f"\r{_format_status(pred)}", end="", flush=True)
        return pred

    def run(self) -> None:
        print(f"watching {self.state_csv}")
        try:
            while True:
                try:
                    self.step()
                except Exception as e:
                    print(f"\n[warn] {e}")
                time.sleep(self.interval)
        except KeyboardInterrupt:
            pass
        print()
        drop_overlay(self.prediction_txt)
