"""Propose (and optionally apply) guide steps for new Forever quests the guides don't cover yet.

Follows tools/ROUTING_RULES.md. For each missing new quest:
  - pick the guide (by zone and level) and the step nearest the quest giver,
  - draft accept -> objective(s) -> turn-in steps, each anchored after the guide step nearest to it,
  - merge into an existing step that already talks to the same NPC,
  - gate dungeon quests (.dungeon TAG, dungeon route only), class quests (<< Class) and profession
    quests (.train spell,3); add a zone-wide heads-up for worthwhile item-started quests.

Usage:
    python tools/propose_inserts.py                 # write data/review/inserts/*.md previews + plan.json
    python tools/propose_inserts.py --zone Westfall # only quests whose giver is in that zone
    python tools/propose_inserts.py --apply         # insert the planned steps into the guide files
    python tools/propose_inserts.py --apply --maxlevel 19   # only guides starting at level <= 19
Inserted blocks are tagged `--FQ <qid>` so they can be found, reviewed and removed.
"""
import glob
import json
import math
import os
import re
import sys
from collections import defaultdict

import coords
import parse_guides as pg

ROOT = pg.ROOT
WH = os.path.join(ROOT, 'data', 'wowhead')
OUT = os.path.join(ROOT, 'data', 'review', 'inserts')

GROUP_NORMAL = 'RestedXP Forever Guide (A)'
GROUP_DUNGEON = 'RestedXP Forever Dungeon Guide (A)'
DUNGEON_CATEGORY = {16919: 'HOT', 1581: 'DM', 16611: 'ROL', 16732: 'ES', 16544: 'COD', 16550: 'TDC',
                    491: 'RFK', 796: 'SM', 719: 'BFD', 717: 'STOCKS', 209: 'SFK', 133: 'GNOMER',
                    1337: 'ULDA', 2100: 'MARA', 978: 'ZF', 1417: 'ST', 1584: 'BRD'}
CLASS_BITS = {1: 'Warrior', 2: 'Paladin', 4: 'Hunter', 8: 'Rogue', 16: 'Priest', 64: 'Shaman',
              128: 'Mage', 256: 'Warlock', 1024: 'Druid'}
PROFESSION_SPELL = {'Alchemy': 2259, 'Blacksmithing': 2018, 'Enchanting': 7411, 'Engineering': 4036,
                    'Herbalism': 2366, 'Leatherworking': 2108, 'Mining': 2575, 'Skinning': 8613,
                    'Tailoring': 3908, 'First Aid': 3273, 'Fishing': 7620, 'Cooking': 2550}
EXCLUDED_CATEGORIES = {16941}  # Craftsman's Writs
REP_RE = re.compile(r'buying friendship|a donation of|economic warfare', re.I)
ACA_FACTIONS = {2586, 2587}  # Azeroth Commerce Authority (Alliance/Horde): user wants none of these
# Desolace: the Alliance route takes the Gelkis side (1382 Strange Alliance), which locks out the Magram chain
MAGRAM_RE = re.compile(r'reputation with the Magram', re.I)
MAGRAM_CHAIN_START = 1385  # Brutal Politics
SKIP = {  # reviewed by hand: not reachable on the Alliance route, or not a leveling quest
    96339: 'Legacy Reward (account reward, no XP)', 96383: 'Legacy Reward (account reward, no XP)',
    98372: 'toy from a wandering NPC, no XP', 99267: 'toy from a wandering NPC, no XP',
    98895: 'Darkspear Islands battleground', 98896: 'Darkspear Islands battleground',
    98903: 'Darkspear Islands battleground',
    97005: 'Ratchet elite cave; the Alliance route never visits the Barrens',
}
SKIP.update({
    98287: 'second copy of Camping 101: Engineering 1 with no giver; Humans get 97918, one per character',
    97253: 'Barrens L14: the route only gets there at 21+, when it is grey',
    98155: 'Feralas L29: the route only gets there at 44+, when it is grey',
    98156: 'Feralas L31: follow-up of 98155',
})
# Wowhead has no quest giver (and mostly no turn-in spot) yet. Re-scrape these pages before placing them
PENDING = {
    97420: 'Reduce, Reuse, Reconcile (STV, Lake Nazferiti drums) - giver and Knaz Blunderflame not on Wowhead',
    92872: 'Dutiful Steps (Stromgarde crypt) - Caretaker Alaric not on Wowhead',
    95786: 'An Acquaintance in Southshore - start of the Savage Coast Report Bundle unknown; ends at Loremaster Dibbs',
    95787: 'Take Two With Water (Drowned City dungeon) - no giver on Wowhead',
    95788: 'Magics of the Drowned City (Drowned City dungeon) - no giver on Wowhead',
    98471: 'Message from the Supreme Magister (Skyborne only, L30) - item source and Elaadrin Evengale in Alterac unknown',
}
TALK = '|Tinterface/worldmap/chatbubble_64grey.blp:20|t'


# ---------------------------------------------------------------- data

def load():
    quests = {q['id']: q for q in (json.load(open(f, encoding='utf-8'))
                                   for f in glob.glob(os.path.join(WH, 'quests', '*.json')))}
    dec_path = os.path.join(ROOT, 'data', 'review', 'decisions.json')
    decisions = json.load(open(dec_path)) if os.path.exists(dec_path) else {}
    item_path = os.path.join(ROOT, 'data', 'analysis', 'item_starts.json')
    items = {r['quest']: r for r in json.load(open(item_path, encoding='utf-8'))['quests']} \
        if os.path.exists(item_path) else {}
    for q in json.load(open(os.path.join(WH, 'quest_list.json'), encoding='utf-8')):
        if q['id'] in quests and any(f in ACA_FACTIONS for f, _ in q.get('reprewards') or []):
            quests[q['id']]['aca'] = True
    # Wowhead shows only one branch of a branching chain per page, so collect predecessors from
    # every page's series; a quest's own series wins
    for q in quests.values():
        s = q.get('series') or []
        for a, b in zip(s, s[1:]):
            PREV.setdefault(b, a)
    for q in quests.values():
        s = q.get('series') or []
        if q['id'] in s[1:]:
            PREV[q['id']] = s[s.index(q['id']) - 1]
    return quests, decisions, items


def excluded(q):
    """Quests kept out of every route: class quests (for now), Azeroth Commerce Authority, the Magram
    chain, and the hand-reviewed SKIP list."""
    if q.get('aca') or q['id'] in SKIP or q['id'] in PENDING:
        return True
    if MAGRAM_CHAIN_START in (q.get('series') or []) or MAGRAM_RE.search(q['objectiveText'] or ''):
        return True
    return bool(q.get('reqclass')) and not (q['name'] or '').startswith('Camping 101')


def zone_ids():
    ids = {name: mid for mid, name in coords.map_names().items()}
    ids.setdefault('Zephras Isle', 2521)
    return ids


ZONE_IDS = zone_ids()
MAP_NAMES = {v: k for k, v in ZONE_IDS.items()}


def step_location(step):
    """(zone, x%, y%) of a step's last goto, in Wowhead zone percentages."""
    for c in reversed(step['cmds']):
        if c['cmd'] != 'goto' or len(c['args']) < 3:
            continue
        z, x, y = c['args'][:3]
        try:
            x, y = float(x), float(y)
        except ValueError:
            return None
        m = re.match(r'(\d+)/\d+$', z)
        if m:
            return coords.world_to_zone(int(m.group(1)), x, y)
        if z.isdigit():
            return MAP_NAMES.get(int(z)), x, y
        return z, x, y
    return None


def guide_levels(name):
    m = re.match(r'(\d+)-(\d+)', name)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 60)


CLASSES = ('Warrior', 'Paladin', 'Hunter', 'Rogue', 'Priest', 'Shaman', 'Mage', 'Warlock', 'Druid')
RACES = ('Human', 'Dwarf', 'Gnome', 'NightElf', 'Skyborne')
EVERYONE = frozenset((c, r) for c in CLASSES for r in RACES)


def audience(conds):
    """Players a guide applies to, from its header conditions ("Alliance !Hunter", "Alliance Warlock")."""
    out = set(EVERYONE)
    for tok in (conds or '').split():
        neg, alts = tok.startswith('!'), tok.lstrip('!').split('/')
        if not all(a in CLASSES or a in RACES for a in alts):
            continue  # Alliance, skip, ...
        match = {p for p in EVERYONE if p[0] in alts or p[1] in alts}
        out = out - match if neg else out & match
    return frozenset(out)


def grey_at(quest_level, player_level):
    """Classic grey-quest rule: no XP worth having once the player is this far above the quest."""
    p = player_level
    return quest_level <= p - (5 if p <= 5 else 5 + p // 10 if p <= 39 else 1 + p // 5)


def gkey(g):
    """A guide's identity. Normal and dungeon routes reuse section names inside one file."""
    return g['file'], re.sub(r'\s*<<.*$', '', g['group']), g['name']


def pkey(p):
    return p['file'], p['group'], p['guide']


def target_guides(dungeon):
    out = []
    for g in pg.parse_all():
        if 'Horde' in (g['conds'] or ''):
            continue
        g['group'] = re.sub(r'\s*<<.*$', '', g['group'])  # "Group << Alliance"
        if g['group'] == GROUP_DUNGEON or (g['group'] == GROUP_NORMAL and not dungeon):
            g['locs'] = [None if 'Horde' in (s['conds'] or '') else step_location(s) for s in g['steps']]
            g['levels'] = guide_levels(g['name'])
            g['aud'] = audience(g['conds'])
            out.append(g)
    return out


# ---------------------------------------------------------------- planning

def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def nearest_step(guide, zone, xy, after=-1):
    """Index of the step (after `after`) in `zone` closest to xy, and the distance."""
    best = (None, 1e9)
    for i, loc in enumerate(guide['locs']):
        if i <= after or not loc or loc[0] != zone:
            continue
        d = dist(loc[1:], xy)
        if d < best[1]:
            best = (i, d)
    return best


def choose_guide(guides, zone, xy, level, group, within=EVERYONE, strict=False):
    """(guide, step index) best placed for a quest at zone/xy. Only guides whose audience overlaps
    `within` (all of it inside `within` when strict); strict picks must also be close and on level."""
    best, best_score = None, 1e9
    for g in guides:
        if g['group'] != group or not g['aud'] & within or (strict and not g['aud'] <= within):
            continue
        idx, d = nearest_step(g, zone, xy)
        if idx is None:
            continue
        lo, hi = g['levels']
        gap = max(0, lo - level, level - hi)
        if strict and (gap > 3 or d > 20):
            continue
        score = d + 15 * gap
        if score < best_score:
            best, best_score = (g, idx), score
    return best


def locate(guide, guides, zone, xy, after):
    """Step to anchor a later block (objective, turn-in) at: in this guide after `after`, else in the
    earliest later guide for the same players that visits the zone. None if no guide goes there."""
    idx, _ = nearest_step(guide, zone, xy, after=after)
    if idx is not None:
        return guide, idx
    best, best_key = None, None
    for g in guides:
        if g is guide or g['group'] != guide['group'] or not g['aud'] & guide['aud'] \
                or g['levels'][0] < guide['levels'][0]:
            continue
        idx, d = nearest_step(g, zone, xy)
        if idx is not None and (best_key is None or (g['levels'][0], d) < best_key):
            best, best_key = (g, idx), (g['levels'][0], d)
    return best


def objective_points(q):
    pts = [p for p in q['points'] if p['point'] in ('requirement', 'sourcerequirement')
           and len(p.get('coord') or []) == 2]
    return pts


def comment_waypoints(q, zone):
    """Coordinates players posted for objectives ("77, 82", "/way 74.3 76.3")."""
    out = []
    for c in q['comments'][:5]:
        if c['rating'] < 0:
            continue
        for x, y in re.findall(r'(?<![\d.])(\d{1,2}(?:\.\d)?)\s*,?\s+(\d{1,2}(?:\.\d)?)(?![\d.])',
                               c['body'].replace('/way', ' ')):
            x, y = float(x), float(y)
            if 1 < x < 99 and 1 < y < 99 and (x, y) not in out:
                out.append((x, y))
    return out[:4]


def goto(zone, x, y, radius=None):
    mid = ZONE_IDS.get(zone)
    if not mid:
        return None
    return f'    .goto {mid},{x:.1f},{y:.1f}' + (f',{radius},0' if radius else '')


def gating_lines(q, dungeon_tag):
    lines, cond = [], None
    if dungeon_tag:
        lines.append(f'    .dungeon {dungeon_tag}')
    if q.get('reqclass'):
        classes = [n for bit, n in CLASS_BITS.items() if q['reqclass'] & bit]
        cond = '/'.join(classes)
    m = re.match(r'Camping 101: (.+)', q['name'] or '')
    if m and m.group(1) in PROFESSION_SPELL:
        lines.append(f'    .train {PROFESSION_SPELL[m.group(1)]},3 -- {m.group(1)} trained')
    return lines, cond


def objective_text(row, q):
    name = re.sub(r' (slain|destroyed|killed)$', '', row['text'])
    if row['type'] == 'npc' and re.search(r'slain|destroyed|killed', row['text']):
        return f'>>Kill |cRXP_ENEMY_{name}|r'
    if row['type'] == 'item':
        return f'>>Collect |cRXP_LOOT_{name}|r'
    if row['type'] == 'object':
        return f'>>Click |cRXP_PICK_{name}|r'
    return f'>>{name}'


def source_text(q):
    """One line naming where collect objectives come from (mobs in red, objects in yellow)."""
    srcs = {}
    for p in q['points']:
        if p['point'] == 'sourcerequirement' and p.get('name'):
            srcs[p['name']] = 'RXP_PICK' if p.get('type') == 2 else 'RXP_ENEMY'
    if not srcs:
        return None
    parts = [f'|c{c}_{n}|r' for n, c in sorted(srcs.items())[:4]]
    return '    >>Loot them from ' + ', '.join(parts)


# lead-ins whose turn-in is only reachable on the way to a dungeon the questing route never visits
DUNGEON_LEADIN = {92432: 'COD'}  # An Alarming Request ends in Silverpine, opens the City of Dalaran chain


def dungeon_of(q):
    if q['id'] in DUNGEON_LEADIN:
        return DUNGEON_LEADIN[q['id']]
    if q['zoneId'] in DUNGEON_CATEGORY:
        return DUNGEON_CATEGORY[q['zoneId']]
    for p in q['points']:  # given outside, done inside (e.g. Westfall -> Deadmines)
        if p['point'] in ('requirement', 'sourcerequirement') and p['zoneId'] in DUNGEON_CATEGORY:
            return DUNGEON_CATEGORY[p['zoneId']]
    return None


def included_ranges(all_guides):
    """{normal guide key: [(first step, last step)]} for the parts that dungeon guides `#include`
    ("Group\\Name" or "Group\\Name@StartLabel-EndLabel"). Steps there show up in both routes."""
    by_name = {(re.sub(r'\s*<<.*$', '', g['group']), g['name'].strip()): g for g in all_guides}
    out = defaultdict(list)
    for g in all_guides:
        for s in g['steps']:
            inc = s['tags'].get('include')
            if not inc or '\\' not in inc:
                continue
            ref, _, rng = inc.partition('@')
            grp, name = ref.split('\\', 1)
            tgt = by_name.get((grp.strip(), name.strip()))
            if not tgt:
                continue
            first, last = 0, len(tgt['steps']) - 1
            if rng and '-' in rng:
                a, b = rng.split('-', 1)
                labels = {st['tags'].get('label'): i for i, st in enumerate(tgt['steps']) if st['tags'].get('label')}
                first, last = labels.get(a, first), labels.get(b, last)
            out[gkey(tgt)].append((first, last))
    return out


def covered_by_group(all_guides, ranges):
    """Quests each route already accepts or turns in, counting included normal-route steps."""
    out = defaultdict(set)
    by_key = {gkey(g): g for g in all_guides}
    for g in all_guides:
        grp = gkey(g)[1]
        ids = pg.quest_ids(g)
        out[grp] |= set(ids['accept']) | set(ids['turnin'])
    for key, rngs in ranges.items():
        g = by_key[key]
        for first, last in rngs:
            for s in g['steps'][first:last + 1]:
                for c in s['cmds']:
                    if c['cmd'] in ('accept', 'turnin') and c['args'] and c['args'][0].isdigit():
                        out[GROUP_DUNGEON].add(int(c['args'][0]))
    return out


def plan_quest(q, guides, items, notes, within=EVERYONE, strict=False, forced=None):
    """Plan one quest for the players in `within`. `forced` = (guide, step) to accept after: the
    previous quest of its chain is turned in there. Returns (plans, audience of the guide it starts
    in), with one plan per guide the quest's steps land in, or None."""
    dungeon_tag = dungeon_of(q)
    group = guides[0]['group'] if guides else GROUP_NORMAL  # the route being filled
    gate, cond = gating_lines(q, dungeon_tag)
    start, end = q.get('start') or {}, q.get('end') or {}
    if not end.get('coords') and start.get('name') and f"to {start['name']}" in (q['objectiveText'] or ''):
        end = start  # "Bring X to <giver>": Wowhead just didn't record the ender
    item = items.get(q['id'])
    blocks = []

    if start.get('coords'):
        zone, xy = start['zone'], tuple(start['coords'][0])
    elif item and item['worth'] and not forced:
        zone, xy = None, None
    else:
        notes.append(f"{q['id']} {q['name']}: no quest giver or confirmed starting item — place by hand")
        return None

    if zone:
        pick = forced or choose_guide(guides, zone, xy, q['level'], group, within, strict)
        if not pick:
            if not strict:
                notes.append(f"{q['id']} {q['name']}: no {group} guide passes through {zone}")
            return None
        guide, at = pick
        lines = gate + [goto(zone, *xy),
                        f"    >>{TALK}Talk to |cRXP_FRIENDLY_{start['name']}|r",
                        f"    .accept {q['id']} >> Accept {q['name']}",
                        f"    .target {start['name']}"]
        blocks.append({'g': guide, 'after': at, 'kind': 'accept', 'npc': start['name'],
                       'chain': bool(forced), 'lines': lines})
    else:
        # item-started: heads-up at the first step of the zone where the item drops
        drops = item['droppedBy']
        zone = next((z for z in item['zones'] if z in ZONE_IDS), None)
        mob = max(drops, key=lambda d: d['chance'] or 0) if drops else None
        pick = choose_guide(guides, zone, (50, 50), q['level'], group, within, strict) if zone else None
        if not (pick and mob):
            if not strict:
                notes.append(f"{q['id']} {q['name']}: item start, but no guide in the drop zone")
            return None
        guide, _ = pick
        first = next(i for i, loc in enumerate(guide['locs']) if loc and loc[0] == zone)
        elite = ' |cRXP_WARN_(elite)|r' if mob['classification'] in (1, 2) else ''
        blocks.append({'g': guide, 'after': first - 1, 'kind': 'headsup', 'lines': gate + [
            '    #completewith FQend' + str(q['id']),
            f"    >>Keep an eye out for |cRXP_ENEMY_{mob['name']}|r{elite} while in {zone}. "
            f"Loot the |cRXP_LOOT_{item['itemName']}|r - it starts |cRXP_WARN_{q['name']}|r",
            f"    .collect {item['item']},1,{q['id']},1",
            f"    .mob {mob['name']}"]})
        at = first
        blocks.append({'g': guide, 'after': first, 'kind': 'accept', 'lines': gate + [
            f"    >>Use the |cRXP_LOOT_{item['itemName']}|r to start the quest",
            f"    .accept {q['id']} >> Accept {q['name']}",
            f"    .use {item['item']}",
            f"    .itemcount {item['item']},1"]})

    if grey_at(q['level'] or 0, guide['levels'][0]):
        if not strict:
            notes.append(f"{q['id']} {q['name']} (L{q['level']}): the route only reaches {zone} in "
                         f"'{guide['name']}', when it's grey — skipped")
        return None

    # objectives, grouped into one step at the cluster nearest the previous anchor
    rows = q.get('objectiveRows') or []
    pts = objective_points(q)
    if rows:
        ozone = pts[0]['zone'] if pts else zone
        cluster = [tuple(p['coord']) for p in pts if p['zone'] == ozone]
        if not cluster and not comment_waypoints(q, ozone):
            # nothing to walk to (skill-ups, emotes...): a background step until the turn-in
            lines = gate + [f'    #completewith FQend{q["id"]}']
            lines += [f'    {objective_text(r, q)}' for r in rows]
            lines += [f"    .complete {q['id']},{i} --{r['text']} ({r['count']})" for i, r in enumerate(rows, 1)]
            blocks.append({'g': guide, 'after': at, 'kind': 'objective', 'lines': lines})
            rows = []
    if rows:
        if cluster:
            cx = sum(p[0] for p in cluster) / len(cluster)
            cy = sum(p[1] for p in cluster) / len(cluster)
        else:
            wps = comment_waypoints(q, ozone)
            cx, cy = sum(p[0] for p in wps) / len(wps), sum(p[1] for p in wps) / len(wps)
        spot = locate(guide, guides, ozone, (cx, cy), at)
        if spot:
            guide, at = spot
        else:
            notes.append(f"{q['id']} {q['name']}: no guide visits {ozone} for the objective — check by hand")
        wlines = [goto(ozone, x, y, 20) for x, y in comment_waypoints(q, ozone)]
        lines = gate + [l for l in wlines if l] + [goto(ozone, cx, cy)]
        for i, row in enumerate(rows, 1):
            lines.append(f'    {objective_text(row, q)}')
        if any(r['type'] == 'item' for r in rows):
            lines.append(source_text(q))
        for i, row in enumerate(rows, 1):
            lines.append(f"    .complete {q['id']},{i} --{row['text']} ({row['count']})")
        mobs = {re.sub(r' (slain|destroyed|killed)$', '', r['text']) for r in rows if r['type'] == 'npc'}
        lines += [f'    .mob {m}' for m in sorted(mobs)]
        blocks.append({'g': guide, 'after': at, 'kind': 'objective', 'lines': lines})

    if end.get('coords'):
        spot = locate(guide, guides, end['zone'], tuple(end['coords'][0]), at)
        if spot:
            guide, at = spot
            blocks.append({'g': guide, 'after': at, 'kind': 'turnin', 'npc': end['name'], 'lines': gate + [
                goto(end['zone'], *end['coords'][0]),
                f"    >>{TALK}Talk to |cRXP_FRIENDLY_{end['name']}|r",
                f"    .turnin {q['id']} >> Turn in {q['name']}",
                f"    .target {end['name']}"]})
        else:
            notes.append(f"{q['id']} {q['name']}: no later guide visits {end['zone']} for the turn-in — check by hand")
    else:
        notes.append(f"{q['id']} {q['name']}: no turn-in location — check by hand")

    # labels only resolve inside one guide: a background step whose turn-in landed in another guide
    # stays pinned until its objective is done instead
    tguide = next((b['g'] for b in blocks if b['kind'] == 'turnin'), None)
    for b in blocks:
        if b['g'] is not tguide:
            b['lines'] = [l.replace(f"#completewith FQend{q['id']}", '#sticky') if b['kind'] == 'objective' else l
                          for l in b['lines']]
    plans = {}
    for b in blocks:
        b['lines'] = [l for l in b['lines'] if l]
        g = b.pop('g')
        p = plans.setdefault(gkey(g), {
            'quest': q['id'], 'name': q['name'], 'level': q['level'], 'guide': g['name'],
            'file': g['file'], 'group': g['group'], 'cond': cond, 'blocks': []})
        p['blocks'].append(b)
    return list(plans.values()), pick[0]['aud']


def missing_quests(quests, decisions, covered, zone_filter=None, items=None):
    out = []
    for q in quests.values():
        if q.get('status') != 'new' or q['id'] in covered or q['zoneId'] in EXCLUDED_CATEGORIES:
            continue
        if excluded(q) or decisions.get(str(q['id'])) == 'cut' or REP_RE.search((q['objectiveText'] or '') + ' ' + (q['name'] or '')):
            continue
        if items is not None and not (q.get('start') or {}).get('coords') and q['id'] in items                 and not items[q['id']]['worth']:
            continue  # item start below the rule-5 bar (item_starts.py)
        if zone_filter and ((q.get('start') or {}).get('zone') != zone_filter):
            continue
        out.append(q)
    # by level, but always after the previous quest of the chain
    out.sort(key=lambda q: (q['level'] or 0, q['id']))
    todo, ordered, done = {q['id']: q for q in out}, [], set()

    def emit(q):
        if q['id'] in done:
            return
        done.add(q['id'])
        prev = predecessor(q)
        if prev in todo:
            emit(todo[prev])
        ordered.append(q)
    for q in out:
        emit(q)
    return ordered


PREV = {}  # qid -> previous quest in its chain, set by load()


def predecessor(q):
    return PREV.get(q['id'])


def turnin_steps(guides, qid):
    """(guide, step index, npc) for every existing guide step that turns in qid."""
    out = []
    for g in guides:
        for i, s in enumerate(g['steps']):
            if any(c['cmd'] == 'turnin' and c['args'][:1] == [str(qid)] for c in s['cmds']):
                npc = next((c['args'][0] for c in s['cmds'] if c['cmd'] == 'target' and c['args']), None)
                out.append((g, i, npc))
    return out


# ---------------------------------------------------------------- output

def render(plan, guide_steps):
    out = [f"### {plan['quest']} {plan['name']} (L{plan['level']}) -> {plan['guide']}", '']
    for b in plan['blocks']:
        anchor = guide_steps[b['after']] if 0 <= b['after'] < len(guide_steps) else None
        where = f"after step at line {anchor['line']}" if anchor else 'at guide start'
        out.append(f"{b['kind']} ({where}):")
        out.append('```')
        out.append('step' + (f" << {plan['cond']}" if plan['cond'] else ''))
        out += b['lines']
        out.append('```')
    return '\n'.join(out)


def merge_same_npc(plans):
    """Accepts/turn-ins at the same NPC after the same anchor step become one step. Accepts merge with
    accepts and turn-ins with turn-ins, except a chain follow-up's accept, which joins the turn-in of
    the quest before it. A quest's own steps never merge with each other."""
    seen = {}
    for p in plans:
        keep = []
        for b in p['blocks']:
            phase = 'turnin' if b['kind'] == 'turnin' or b.get('chain') else b['kind']
            key = (pkey(p), b['after'], b.get('npc'), p['cond'], phase,
                   tuple(l for l in b['lines'] if l.startswith('    .dungeon') or l.startswith('    .train')))
            if b['kind'] in ('accept', 'turnin') and b.get('npc') and key in seen \
                    and seen[key]['hostQuest'] != p['quest'] \
                    and not (b['kind'] == 'turnin' and seen[key]['kind'] == 'accept'):
                host = seen[key]
                action = next(l for l in b['lines'] if l.startswith(f"    .{b['kind']} "))
                pos = next(i for i, l in enumerate(host['lines']) if l.startswith('    .target'))
                host['lines'].insert(pos, action)
                host.setdefault('quests', []).append(p['quest'])
                if b['kind'] == 'turnin':  # this quest's background steps wait on the shared step
                    for ob in p['blocks']:
                        ob['lines'] = [l.replace(f"FQend{p['quest']}", f"FQend{host['hostQuest']}")
                                       for l in ob['lines']]
                continue
            b['hostQuest'] = p['quest']
            if b['kind'] in ('accept', 'turnin') and b.get('npc'):
                seen[key] = b
            keep.append(b)
        p['blocks'] = keep
    return plans


def apply(plans):
    """Insert blocks after their anchor steps. Works bottom-up per file so line numbers stay valid."""
    by_file = defaultdict(list)
    guides = {gkey(g): g for g in pg.parse_all()}
    for p in plans:
        g = guides[pkey(p)]
        for b in p['blocks']:
            steps = g['steps']
            if 0 <= b['after'] < len(steps) - 1:
                line = steps[b['after'] + 1]['line'] - 1  # insert before the next step
            elif b['after'] < 0:
                line = steps[0]['line'] - 1
            else:  # after the last step: before the closing ]]
                line = steps[-1]['line'] + len(steps[-1]['cmds']) + len(steps[-1]['text'])
            text = ['step' + (f" << {p['cond']}" if p['cond'] else '') + f" --FQ {p['quest']} {b['kind']}"] + b['lines']
            if b['kind'] == 'turnin':
                text.insert(1, f"    #label FQend{p['quest']}")
            by_file[p['file']].append((line, len(by_file[p['file']]), text))
    for rel, inserts in by_file.items():
        path = os.path.join(ROOT, rel)
        lines = open(path, encoding='utf-8').read().split('\n')
        # bottom-up; blocks sharing an anchor go in last-first so they end up in plan order
        for line, _, text in sorted(inserts, key=lambda t: (-t[0], -t[1])):
            lines[line:line] = text
        open(path, 'w', encoding='utf-8', newline='').write('\n'.join(lines))
        print(f'{rel}: inserted {len(inserts)} steps')


def main(argv):
    zone_filter = argv[argv.index('--zone') + 1] if '--zone' in argv else None
    quests, decisions, items = load()
    all_guides = pg.parse_all()
    ranges = included_ranges(all_guides)
    cov = covered_by_group(all_guides, ranges)
    # done = in every route it belongs to (dungeon quests only belong to the dungeon route)
    covered = {qid for qid in cov[GROUP_DUNGEON]
               if qid in cov[GROUP_NORMAL] or (qid in quests and dungeon_of(quests[qid]))}
    todo = missing_quests(quests, decisions, covered, zone_filter, items)
    guides_n = target_guides(dungeon=False)
    guides_d = target_guides(dungeon=True)
    plans, notes = [], []
    planned_turnins = defaultdict(list)  # qid -> [(guide, step index, npc)] from this run
    for q in todo:
        dungeon = dungeon_of(q) is not None
        groups = [GROUP_DUNGEON] if dungeon else [GROUP_NORMAL, GROUP_DUNGEON]
        for grp in groups:
            if q['id'] in cov[grp]:
                continue
            gl = [g for g in (guides_d if grp == GROUP_DUNGEON else guides_n) if g['group'] == grp]
            by_key = {gkey(g): g for g in gl}
            note_sink = notes if grp == groups[0] else []
            remaining = EVERYONE
            # chain follow-up: accept right after the previous quest's turn-in, wherever that is
            prev = predecessor(q)
            starts = []
            if prev:
                starts = [t for t in planned_turnins[prev] if t[0]['group'] == grp] + turnin_steps(gl, prev)
            st = q.get('start') or {}
            tries = [dict(forced=(g, i)) for g, i, npc in starts
                     if npc == st.get('name') or (st.get('coords') and g['locs'][i] and g['locs'][i][0] == st['zone']
                                                  and dist(g['locs'][i][1:], st['coords'][0]) < 10)]
            tries.append(dict())  # then the best guide by location, for whoever is left
            for kw in tries:
                while remaining:
                    first = remaining == EVERYONE and not kw.get('forced')
                    if kw.get('forced') and not kw['forced'][0]['aud'] & remaining:
                        break
                    r = plan_quest(q, gl, items, note_sink if first else [], within=remaining,
                                   strict=not first, **kw)
                    if not r:
                        break
                    ps, aud = r
                    plans += ps
                    for p in ps:  # landed in a stretch the dungeon route includes: it has it too
                        if any(lo <= b['after'] < hi for b in p['blocks'] if b['kind'] == 'accept'
                               for lo, hi in ranges.get(pkey(p), [])):
                            cov[GROUP_DUNGEON].add(q['id'])
                    remaining -= aud
                    for p in ps:
                        for b in p['blocks']:
                            if b['kind'] == 'turnin':
                                planned_turnins[q['id']].append((by_key[pkey(p)], b['after'], b['npc']))
                    if kw.get('forced'):
                        break

    plans = [p for p in merge_same_npc(plans) if p['blocks']]
    os.makedirs(OUT, exist_ok=True)
    for old in glob.glob(os.path.join(OUT, '*.md')):  # previews from earlier runs
        os.remove(old)
    json.dump(plans, open(os.path.join(OUT, 'plan.json'), 'w', encoding='utf-8'), indent=1)
    steps_by_guide = {gkey(g): g['steps'] for g in pg.parse_all()}
    by_guide = defaultdict(list)
    for p in plans:
        key = pkey(p)
        label = ('D_' if p['group'] == GROUP_DUNGEON else '') + p['guide']
        by_guide[label].append(render(p, steps_by_guide[key]))
    for gname, parts in by_guide.items():
        fn = re.sub(r'[^\w-]+', '_', gname) + '.md'
        open(os.path.join(OUT, fn), 'w', encoding='utf-8').write(f'# Inserts for {gname}\n\n' + '\n\n'.join(parts) + '\n')
    open(os.path.join(OUT, 'NOTES.md'), 'w', encoding='utf-8').write('# Needs a manual decision\n\n' +
                                                                   '\n'.join(f'- {n}' for n in notes) + '\n')
    print(f'{len(todo)} missing quests -> {len(plans)} guide plans in {len(by_guide)} guides; '
          f'{len(notes)} need manual placement (see {os.path.relpath(OUT, ROOT)})')
    if '--apply' in argv:
        if '--maxlevel' in argv:  # only guides whose range starts at or below this level
            cap = int(argv[argv.index('--maxlevel') + 1])
            plans = [p for p in plans if guide_levels(p['guide'])[0] <= cap]
        apply(plans)


if __name__ == '__main__':
    main(sys.argv[1:])
