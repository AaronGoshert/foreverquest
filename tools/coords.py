"""Convert between guide world coordinates (`.goto <uiMapID>/<inst>,wx,wy`) and Wowhead zone
percentages, per zone, using NPCs that appear in both.

For each guide step with `.target <NPC>` and a world-coordinate `.goto`, and each Wowhead quest point
naming the same NPC with zone coordinates, we get one pair. Zone maps are axis-aligned, so per zone:
    zone_x% = a * wy + b      zone_y% = c * wx + d
fitted by least squares. The fits are cached in data/analysis/zone_transforms.json.

Usage: python tools/coords.py      # fit and print residuals per zone
"""
import glob
import json
import os
import re
from collections import defaultdict

import parse_guides as pg

ROOT = pg.ROOT
WH = os.path.join(ROOT, 'data', 'wowhead')
CACHE = os.path.join(ROOT, 'data', 'analysis', 'zone_transforms.json')


def map_names():
    """uiMapID -> zone name, from ForeverQuest/DB/forever/db.lua addon.mapId."""
    src = open(os.path.join(pg.ADDON, 'DB', 'forever', 'db.lua'), encoding='utf-8').read()
    block = src[src.find('addon.mapId = {'):]
    block = block[:block.find('\n}')]
    return {int(i): n for n, i in re.findall(r'\["([^"]+)"\]\s*=\s*(\d+)', block)}


def guide_pairs():
    """[(uiMapID, key, wx, wy)] from world-coordinate gotos. key is an NPC name (step `.target`) or
    ('accept'|'turnin', questId) for steps that accept/turn in a quest."""
    out = []
    for g in pg.parse_all():
        for s in g['steps']:
            gotos = [c['args'] for c in s['cmds'] if c['cmd'] == 'goto' and len(c['args']) >= 3]
            if not gotos:
                continue
            m = re.match(r'(\d+)/\d+$', gotos[-1][0])
            if not m:
                continue
            try:
                mid, wx, wy = int(m.group(1)), float(gotos[-1][1]), float(gotos[-1][2])
            except ValueError:
                continue
            targets = {c['args'][0] for c in s['cmds'] if c['cmd'] == 'target' and c['args']}
            if len(targets) == 1:
                out.append((mid, targets.pop(), wx, wy))
            for c in s['cmds']:
                if c['cmd'] in ('accept', 'turnin') and c['args'] and c['args'][0].isdigit():
                    out.append((mid, (c['cmd'], int(c['args'][0])), wx, wy))
    return out


def wowhead_points():
    """key -> {(zone name, x%, y%)}: NPC names, plus ('accept'|'turnin', questId) giver locations."""
    pts = defaultdict(set)
    for f in glob.glob(os.path.join(WH, 'quests', '*.json')):
        q = json.load(open(f, encoding='utf-8'))
        for p in q['points']:
            if p.get('type') == 1 and p.get('name') and len(p.get('coord') or []) == 2:
                pts[p['name']].add((p['zone'], p['coord'][0], p['coord'][1]))
        for key, cmd in (('start', 'accept'), ('end', 'turnin')):
            ent = q.get(key) or {}
            for c in ent.get('coords') or []:
                if len(c) == 2:
                    pts[(cmd, q['id'])].add((ent.get('zone'), c[0], c[1]))
    return pts


def robust_fit(ps, tol=1.5):
    """RANSAC over point pairs: the model with the most inliers, refitted on them."""
    best, best_in = None, []
    for i in range(len(ps)):
        for j in range(i + 1, len(ps)):
            p, q = ps[i], ps[j]
            if abs(p[1] - q[1]) < 1 or abs(p[0] - q[0]) < 1:
                continue
            ax = (p[2] - q[2]) / (p[1] - q[1])
            cy = (p[3] - q[3]) / (p[0] - q[0])
            bx, dy = p[2] - ax * p[1], p[3] - cy * p[0]
            inl = [r for r in ps if abs(ax * r[1] + bx - r[2]) + abs(cy * r[0] + dy - r[3]) < tol]
            if len(inl) > len(best_in):
                best, best_in = (ax, bx, cy, dy), inl
        if len(ps) > 60 and i > 40:  # plenty of samples for big zones
            break
    if not best or len(best_in) < 3:
        return None, []
    fx = fit([r[1] for r in best_in], [r[2] for r in best_in])
    fy = fit([r[0] for r in best_in], [r[3] for r in best_in])
    return (fx[0], fx[1], fy[0], fy[1]) if fx and fy else best, best_in


def fit(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    a = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return a, my - a * mx


def build():
    names = map_names()
    wh = wowhead_points()
    pairs = defaultdict(list)
    for mid, npc, wx, wy in guide_pairs():
        zone = names.get(mid)
        for z, x, y in wh.get(npc, ()):
            if z == zone:
                pairs[mid].append((wx, wy, x, y))
    out = {}
    for mid, ps in pairs.items():
        ps = list(set(ps))
        model, good = robust_fit(ps)
        if not model:
            continue
        ax, bx, cy, dy = model
        resid = max(abs(ax * p[1] + bx - p[2]) + abs(cy * p[0] + dy - p[3]) for p in good)
        out[str(mid)] = {'zone': names.get(mid), 'ax': ax, 'bx': bx, 'cy': cy, 'dy': dy,
                         'n': len(good), 'of': len(ps), 'maxResid': round(resid, 2)}
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    json.dump(out, open(CACHE, 'w'), indent=1)
    return out


_T = None


def transforms():
    global _T
    if _T is None:
        _T = json.load(open(CACHE)) if os.path.exists(CACHE) else build()
    return _T


def world_to_zone(mid, wx, wy):
    t = transforms().get(str(mid))
    if not t:
        return None
    return t['zone'], round(t['ax'] * wy + t['bx'], 1), round(t['cy'] * wx + t['dy'], 1)


def zone_to_world(zone, x, y):
    for mid, t in transforms().items():
        if t['zone'] == zone:
            return int(mid), round((y - t['dy']) / t['cy'], 2), round((x - t['bx']) / t['ax'], 2)
    return None


if __name__ == '__main__':
    for mid, t in sorted(build().items(), key=lambda kv: kv[1]['zone'] or ''):
        print(f"{mid} {t['zone']:<24} inliers={t['n']}/{t['of']:<5} max residual={t['maxResid']}%")
