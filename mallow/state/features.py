from __future__ import annotations

import csv
import functools
import math
from dataclasses import dataclass, field
from pathlib import Path

from . import paths

FPS = 30

STATE_FIELDS = [
    "money", "moneyEarned", "moneySpent",
    "unitsBuilt", "unitsLost", "unitsDestroyed",
    "bldgsBuilt", "bldgsLost", "bldgsDestroyed",
    "techCaptured", "factionCaptured",
    "energyProd", "energyCons",
    "unitCount", "unitValue", "structCount", "structValue",
]
EXT_FIELDS = ["heroicCount", "swCount", "swMaxReady",
              "queueCount", "queueValue", "cmdCount"]
N_BASE = len(STATE_FIELDS)
N_EXT = len(EXT_FIELDS)

GRID_DIM = 8

COMP_BUCKETS = ["tank", "light", "artillery", "antiair", "infantry",
                "hero", "air", "eco", "defense", "superweapon"]

SECTOR_FIELDS = ["sec_behind", "sec_own", "sec_mid", "sec_enemy", "sec_flank"]

TEMPLATE_TO_FACTION = {
    "FactionAmerica": "USA",
    "FactionAmericaSuperWeaponGeneral": "SWG",
    "FactionAmericaLaserGeneral": "LASER",
    "FactionAmericaAirForceGeneral": "AIR",
    "FactionChina": "CHINA",
    "FactionChinaTankGeneral": "TANK",
    "FactionChinaInfantryGeneral": "INF",
    "FactionChinaNukeGeneral": "NUKE",
    "FactionGLA": "GLA",
    "FactionGLAToxinGeneral": "TOX",
    "FactionGLADemolitionGeneral": "DEMO",
    "FactionGLAStealthGeneral": "STEALTH",
}
FACTIONS = sorted(set(TEMPLATE_TO_FACTION.values()))

SIDE_MAP = {
    "USA": "usa", "SWG": "usa", "LASER": "usa", "AIR": "usa",
    "CHINA": "china", "TANK": "china", "INF": "china", "NUKE": "china",
    "GLA": "gla", "TOX": "gla", "DEMO": "gla", "STEALTH": "gla",
}
SIDES = sorted(set(SIDE_MAP.values()))  # ["china", "gla", "usa"]

RATE_FIELDS = ["moneyEarned", "moneySpent", "unitsDestroyed", "unitsLost",
               "unitValue", "structValue"]
EXT_RATE_FIELDS = ["cmdCount"]      # 60s delta
RATE_WINDOW_SEC = 60


@functools.cache
def load_unit_classes() -> dict[int, str]:
    classes: dict[int, str] = {}
    with open(paths.UNIT_CLASSES, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            classes[int(row["template_id"])] = row["bucket"]
    return classes


def parse_sparse(s: str) -> dict[int, int]:
    if not s or s == "-":
        return {}
    out = {}
    for pair in s.split(";"):
        k, _, v = pair.partition(":")
        try:
            out[int(k)] = int(v)
        except ValueError:
            continue
    return out


@dataclass
class StateMatch:
    map_name: str = ""
    replay_name: str = ""
    start_ts: int = 0
    players: dict = field(default_factory=dict)
    end_frame: int = -1
    last_frame: int = 0
    has_ext: bool = False


def parse_state_csv(path: str | Path) -> StateMatch:
    m = StateMatch()
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            tag = parts[0]
            if tag == "META" and len(parts) >= 4:
                m.map_name = parts[1]
                m.replay_name = parts[2]
                try:
                    m.start_ts = int(parts[3])
                except ValueError:
                    pass
            elif tag == "STATE" and len(parts) >= 5 + N_BASE:
                try:
                    frame = int(parts[1])
                    pidx = int(parts[2])
                    vals = [float(x) for x in parts[5:5 + N_BASE]]
                except ValueError:
                    continue
                ext_at = 5 + N_BASE
                sparse = ({}, {}, {})
                if len(parts) >= ext_at + N_EXT + 3:
                    try:
                        vals += [float(x) for x in
                                 parts[ext_at:ext_at + N_EXT]]
                        sparse = (parse_sparse(parts[ext_at + N_EXT]),
                                  parse_sparse(parts[ext_at + N_EXT + 1]),
                                  parse_sparse(parts[ext_at + N_EXT + 2]))
                        m.has_ext = True
                    except ValueError:
                        vals = vals[:N_BASE] + [0.0] * N_EXT
                else:
                    vals += [0.0] * N_EXT
                p = m.players.setdefault(pidx, {"name": parts[3],
                                                "side": parts[4],
                                                "rows": {}, "sparse": {}})
                t = frame // FPS
                p["rows"][t] = vals
                p["sparse"][t] = sparse
                m.last_frame = max(m.last_frame, frame)
            elif tag == "END" and len(parts) >= 2:
                try:
                    m.end_frame = int(parts[1])
                except ValueError:
                    pass
    return m


def faction_code(side: str) -> str:
    return TEMPLATE_TO_FACTION.get(side, "")


def main_players(m: StateMatch) -> list[int]:
    return sorted(m.players.keys())


# --------------------------------------------------------------------------
# helpers

def _cell_xy(cell: int) -> tuple[float, float]:
    return ((cell % GRID_DIM + 0.5) / GRID_DIM,
            (cell // GRID_DIM + 0.5) / GRID_DIM)


def _grid_centroid(grid: dict[int, int]) -> tuple[float, float] | None:
    total = sum(grid.values())
    if total <= 0:
        return None
    cx = cy = 0.0
    for cell, v in grid.items():
        x, y = _cell_xy(cell)
        cx += x * v
        cy += y * v
    return cx / total, cy / total


def base_centroids(m: StateMatch, pa: int, pb: int):
    ts = sorted(set(m.players[pa]["sparse"]) & set(m.players[pb]["sparse"]))
    for t in ts:
        ca = _grid_centroid(m.players[pa]["sparse"][t][2])
        cb = _grid_centroid(m.players[pb]["sparse"][t][2])
        if ca is not None and cb is not None:
            return ca, cb
    return None, None


def sector_values(ugrid: dict[int, int], own, enemy) -> list[float]:
    behind = own_v = mid = enemy_v = flank = 0.0
    if own is None or enemy is None:
        return [behind, own_v, mid, enemy_v, flank]
    ax, ay = own
    dx, dy = enemy[0] - ax, enemy[1] - ay
    d2 = dx * dx + dy * dy
    if d2 < 1e-6:
        return [behind, own_v, mid, enemy_v, flank]
    d = math.sqrt(d2)
    for cell, v in ugrid.items():
        x, y = _cell_xy(cell)
        px, py = x - ax, y - ay
        s = (px * dx + py * dy) / d2
        lat = abs(px * dy - py * dx) / d2
        if s < 0.0:
            behind += v
        elif s < 1.0 / 3.0:
            own_v += v
        elif s < 2.0 / 3.0:
            mid += v
        else:
            enemy_v += v
        if lat > 1.0 / 3.0 and s > 0.0:
            flank += v
    return [behind, own_v, mid, enemy_v, flank]


def comp_values(comp: dict[int, int]) -> list[float]:
    classes = load_unit_classes()
    out = {b: 0.0 for b in COMP_BUCKETS}
    for tid, v in comp.items():
        b = classes.get(tid)
        if b in out:
            out[b] += v
    return [out[b] for b in COMP_BUCKETS]


# ---------------------------------------------------------------------------
# feature construction

def snapshot_feature_names(extended: bool = False) -> list[str]:
    fields = STATE_FIELDS + (EXT_FIELDS if extended else [])
    rate_fields = RATE_FIELDS + (EXT_RATE_FIELDS if extended else [])
    per_side = list(fields)
    if extended:
        per_side += [f"comp_{b}" for b in COMP_BUCKETS]
        per_side += SECTOR_FIELDS
    names = ["t"]
    for side in ("a", "b"):
        names += [f"{side}_{f}" for f in per_side]
        names += [f"{side}_{f}_rate" for f in rate_fields]
    names += [f"d_{f}" for f in per_side]
    names += [f"d_{f}_rate" for f in rate_fields]
    names += [f"fa_{f}" for f in FACTIONS]
    names += [f"fb_{f}" for f in FACTIONS]
    if extended:
        names += [f"fa_side_{s}" for s in SIDES]
        names += [f"fb_side_{s}" for s in SIDES]
        names += [f"d_side_{s}" for s in SIDES]
    return names


def build_snapshot(m: StateMatch, pa: int, pb: int, t: int,
                   extended: bool = False, bases=None):
    ra = m.players[pa]["rows"].get(t)
    rb = m.players[pb]["rows"].get(t)
    if ra is None or rb is None:
        return None
    n_fields = N_BASE + N_EXT if extended else N_BASE
    t_prev = t - RATE_WINDOW_SEC
    ra_prev = m.players[pa]["rows"].get(t_prev) if t_prev > 0 else None
    rb_prev = m.players[pb]["rows"].get(t_prev) if t_prev > 0 else None

    rate_fields = RATE_FIELDS + (EXT_RATE_FIELDS if extended else [])
    all_fields = STATE_FIELDS + EXT_FIELDS

    if extended and bases is None:
        bases = base_centroids(m, pa, pb)

    out = [float(t)]
    side_vec = {}
    rates = {}
    for side, pidx, row, prev in (("a", pa, ra, ra_prev),
                                  ("b", pb, rb, rb_prev)):
        vec = list(row[:n_fields])
        if extended:
            comp, ugrid, _ = m.players[pidx]["sparse"].get(t, ({}, {}, {}))
            vec += comp_values(comp)
            own, en = (bases[0], bases[1]) if pidx == pa else (bases[1], bases[0])
            vec += sector_values(ugrid, own, en)
        side_vec[side] = vec
        srates = []
        for fname in rate_fields:
            i = all_fields.index(fname)
            old = prev[i] if prev is not None else 0.0
            srates.append(float(row[i] - old))
        rates[side] = srates
        out.extend(vec)
        out.extend(srates)
    out.extend(x - y for x, y in zip(side_vec["a"], side_vec["b"]))
    out.extend(x - y for x, y in zip(rates["a"], rates["b"]))
    fa = faction_code(m.players[pa]["side"])
    fb = faction_code(m.players[pb]["side"])
    out.extend(1.0 if f == fa else 0.0 for f in FACTIONS)
    out.extend(1.0 if f == fb else 0.0 for f in FACTIONS)
    if extended:
        fa_side = SIDE_MAP.get(fa, "")
        fb_side = SIDE_MAP.get(fb, "")
        a_sv = [1.0 if s == fa_side else 0.0 for s in SIDES]
        b_sv = [1.0 if s == fb_side else 0.0 for s in SIDES]
        out.extend(a_sv)
        out.extend(b_sv)
        out.extend(x - y for x, y in zip(a_sv, b_sv))
    return out
