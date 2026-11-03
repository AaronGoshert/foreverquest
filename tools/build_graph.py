"""Analyse the new Forever quests against the existing guides.

Writes:
    data/analysis/new_quests_by_zone.md    every new quest grouped by zone, marked if a guide already covers it
    data/review/gather_candidates.md       collect quests that may be worth cutting (user reviews)
    data/review/decisions.json             created empty if missing; {"<qid>": "keep" | "cut"}

Usage: python tools/build_graph.py
"""
import glob
import json
import os
import re
from collections import defaultdict

import parse_guides as pg

ROOT = pg.ROOT
WH = os.path.join(ROOT, 'data', 'wowhead')
SLOW_WORDS = re.compile(r'drop rate|low drop|droprate|slow|annoying|forever to|took ages|rare drop|'
                        r'bad drop|tedious|long time|respawn', re.I)


def load_quests():
    return {q['id']: q for q in (json.load(open(f, encoding='utf-8'))
                                 for f in glob.glob(os.path.join(WH, 'quests', '*.json')))}


def covered_ids():
    """quest id -> list of guide names that accept or turn it in (Alliance guides only)."""
    cov = defaultdict(list)
    for g in pg.parse_all():
        if 'Horde' in (g['conds'] or '') + g['group']:
            continue
        q = pg.quest_ids(g)
        for qid in set(q['accept']) | set(q['turnin']):
            cov[qid].append(g['name'])
    return cov


def leads_on(q, quests):
    """True if another quest follows this one in its chain."""
    s = q.get('series') or []
    return q['id'] in s and s.index(q['id']) < len(s) - 1


def gather_score(q, quests):
    items = [o for o in q['objectives'] if o['type'] == 'item']
    kills = [o for o in q['objectives'] if o['type'] == 'npc']
    if not items or leads_on(q, quests):
        return 0, []
    reasons = []
    score = 0
    total = sum(o['count'] for o in items)
    if total >= 5:
        score += 2
        reasons.append(f'collect {total} items')
    sources = [p for p in q['points'] if p['point'] == 'sourcerequirement']
    if sources:
        score += 1
        reasons.append(f'{len(sources)} drop-source mob/object groups')
    if kills:
        score -= 1  # mixed kill/collect quests are usually done alongside other objectives
    slow = [c for c in q['comments'] if SLOW_WORDS.search(c['body'])]
    if slow:
        score += 2
        reasons.append(f'{len(slow)} comments mention slow/low drops')
    return score, reasons


def zone_name(q):
    for key in ('start', 'end'):
        if q.get(key) and q[key].get('zone'):
            return q[key]['zone']
    return f"zone {q.get('zoneId')}"


def main():
    quests = load_quests()
    new = {k: v for k, v in quests.items() if v.get('status') == 'new'}
    cov = covered_ids()
    os.makedirs(os.path.join(ROOT, 'data', 'analysis'), exist_ok=True)
    os.makedirs(os.path.join(ROOT, 'data', 'review'), exist_ok=True)

    by_zone = defaultdict(list)
    for q in new.values():
        by_zone[zone_name(q)].append(q)
    lines = ['# New Forever quests by zone', '',
             f'{len(new)} new quests parsed; {sum(1 for q in new.values() if q["id"] in cov)} '
             'already appear in an existing guide.', '']
    for zone, qs in sorted(by_zone.items(), key=lambda kv: min(q['level'] or 0 for q in kv[1])):
        lines.append(f'## {zone} ({len(qs)})')
        for q in sorted(qs, key=lambda q: (q['level'] or 0, q['id'])):
            mark = 'x' if q['id'] in cov else ' '
            chain = f" chain {q['series'].index(q['id']) + 1}/{len(q['series'])}" if q['id'] in q['series'] else ''
            where = f" — in {', '.join(sorted(set(cov[q['id']])))}" if q['id'] in cov else ''
            lines.append(f"- [{mark}] {q['id']} L{q['level']} {q['name']}{chain}{where}")
        lines.append('')
    open(os.path.join(ROOT, 'data', 'analysis', 'new_quests_by_zone.md'), 'w', encoding='utf-8').write(
        '\n'.join(lines))

    cands = sorted(((gather_score(q, quests), q) for q in new.values()), key=lambda t: -t[0][0])
    cands = [(s, q) for s, q in cands if s[0] >= 3]
    out = ['# Gather-quest review', '',
           'These new quests are collect quests that do not lead into a later quest.',
           'Tell Claude which to keep or cut (or edit decisions.json: {"<id>": "keep"|"cut"}).', '']
    for (score, reasons), q in cands:
        top = q['comments'][0]['body'][:160].replace('\n', ' ') if q['comments'] else ''
        out.append(f"- **{q['id']} {q['name']}** (L{q['level']}, {zone_name(q)}) score {score}: "
                   f"{'; '.join(reasons)}")
        if top:
            out.append(f'  - top comment: {top}')
    open(os.path.join(ROOT, 'data', 'review', 'gather_candidates.md'), 'w', encoding='utf-8').write(
        '\n'.join(out) + '\n')
    dec = os.path.join(ROOT, 'data', 'review', 'decisions.json')
    if not os.path.exists(dec):
        json.dump({}, open(dec, 'w'))
    print(f'{len(new)} new quests in {len(by_zone)} zones; {sum(1 for q in new if q in cov)} already covered; '
          f'{len(cands)} gather candidates')


if __name__ == '__main__':
    main()
