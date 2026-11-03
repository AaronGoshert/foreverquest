"""Item-started quests: learn from the existing guides, then score the new Forever ones.

1. Examples: find every quest the Alliance guides start from a looted item (a step with
   `.collect <item>,1,<qid>` or `.use/.itemcount <item>` next to `.accept <qid>`), and measure how they
   compare to normal quests of the same level: XP ratio and whether turning them in leads to another .accept.
2. New quests: for each new Forever quest with no quest giver, confirm the starting item on its
   Wowhead item page (data/wowhead/raw_items/<id>.json: "starts" and "dropped-by" lists), find the
   dropping mob, its zone and drop chance, and score it with the thresholds learned in step 1.

Writes data/analysis/item_starts.json and data/analysis/item_starts.md.
Usage: python tools/item_starts.py
"""
import glob
import json
import os
import re
import statistics
from collections import defaultdict

import parse_guides as pg
from parse_quest_pages import js_value

ROOT = pg.ROOT
WH = os.path.join(ROOT, 'data', 'wowhead')
OUT = os.path.join(ROOT, 'data', 'analysis')


def quest_list():
    return {q['id']: q for q in json.load(open(os.path.join(WH, 'quest_list.json'), encoding='utf-8'))}


def median_xp_by_level(lst):
    by = defaultdict(list)
    for q in lst.values():
        if q['xp'] and q['level'] > 0:
            by[q['level']].append(q['xp'])
    return {lvl: statistics.median(v) for lvl, v in by.items()}


def guide_examples(lst, med):
    """Item-started quests the guides already include, with XP ratio and chain flag."""
    examples = {}
    for g in pg.parse_all():
        if 'Horde' in (g['conds'] or '') + g['group']:
            continue
        steps = g['steps']
        turnin_steps = defaultdict(list)
        for i, s in enumerate(steps):
            for c in s['cmds']:
                if c['cmd'] == 'turnin' and c['args'] and c['args'][0].isdigit():
                    turnin_steps[int(c['args'][0])].append(i)
        for i, s in enumerate(steps):
            item_for = {}
            for c in s['cmds']:
                a = c['args']
                if c['cmd'] == 'collect' and len(a) >= 3 and a[1] == '1' and a[2].isdigit():
                    item_for[int(a[2])] = int(a[0])
                if c['cmd'] in ('use', 'itemcount') and a and a[0].isdigit():
                    item_for.setdefault('any', int(a[0]))
            for c in s['cmds']:
                if c['cmd'] != 'accept' or not c['args'] or not c['args'][0].isdigit():
                    continue
                qid = int(c['args'][0])
                item = item_for.get(qid) or item_for.get('any')
                if not item or qid not in lst or qid in examples:
                    continue
                q = lst[qid]
                # chain: the step that turns it in also accepts something
                chain = any(cc['cmd'] == 'accept' for j in turnin_steps.get(qid, []) for cc in steps[j]['cmds'])
                examples[qid] = {'id': qid, 'name': q['name'], 'level': q['level'], 'item': item,
                                 'xpRatio': round(q['xp'] / med.get(q['level'], q['xp'] or 1), 2) if q['xp'] else 0,
                                 'chain': chain, 'guide': g['name']}
    return examples


def zone_names():
    names = {}
    for f in glob.glob(os.path.join(WH, 'quests', '*.json')):
        for p in json.load(open(f, encoding='utf-8'))['points']:
            if p.get('zone'):
                names[p['zoneId']] = p['zone']
    return names


def listview(h, lv_id):
    m = re.search(r"new Listview\(\{[^{}]*?id: '" + lv_id + r"'", h)
    if not m:
        return []
    d = h.find('data:', m.start())
    return js_value(h, h.find('[', d)) or []


def item_info(item_id):
    path = os.path.join(WH, 'raw_items', f'{item_id}.json')
    if not os.path.exists(path):
        return None
    h = json.load(open(path, encoding='utf-8'))['html']
    name = re.search(r'<h1[^>]*>([^<]+)</h1>', h)
    starts = [q['id'] for q in listview(h, 'starts')]
    drops = []
    for n in listview(h, 'dropped-by'):
        count, outof = n.get('count', 0), n.get('outof', 0)
        override = next((m.get('percentOverride') for m in (n.get('modes') or {}).values()
                         if isinstance(m, dict) and m.get('percentOverride')), None)
        chance = round(100 * count / outof, 1) if count > 0 and outof else override
        drops.append({'npc': n['id'], 'name': n.get('name'), 'level': n.get('minlevel'),
                      'classification': n.get('classification', 0), 'zones': n.get('location', []),
                      'chance': chance})
    objects = [{'object': o['id'], 'name': o.get('name'), 'zones': o.get('location', [])}
               for o in listview(h, 'contained-in-object')]
    return {'id': item_id, 'name': name.group(1) if name else None, 'starts': starts,
            'droppedBy': drops, 'containedIn': objects}


def main():
    lst = quest_list()
    med = median_xp_by_level(lst)
    ex = guide_examples(lst, med)
    ratios = sorted(e['xpRatio'] for e in ex.values())
    chain_rate = sum(e['chain'] for e in ex.values()) / max(1, len(ex))
    # threshold: include if XP is at least the 25th percentile of what the guides already include
    xp_floor = ratios[len(ratios) // 4] if ratios else 1.0

    quests = {q['id']: q for q in (json.load(open(f, encoding='utf-8'))
                                   for f in glob.glob(os.path.join(WH, 'quests', '*.json')))}
    cands = json.load(open(os.path.join(WH, 'start_item_candidates.json')))
    zn = zone_names()
    results = []
    for item_id, qids in cands.items():
        info = item_info(int(item_id))
        if not info:
            continue
        for qid in qids:
            if qid not in info['starts']:
                continue  # this item is an objective of the quest, not its starter
            q = quests[qid]
            series = q.get('series') or []
            follow = series[series.index(qid) + 1:] if qid in series else []
            new_follow = [s for s in follow if s in quests and quests[s].get('status') == 'new']
            ratio = round(q['xp'] / med.get(q['level'], q['xp'] or 1), 2) if q['xp'] else 0
            best = max(info['droppedBy'], key=lambda d: d['chance'] or 0, default=None)
            zones = sorted({zn.get(z, f'zone {z}') for d in info['droppedBy'] for z in d['zones']} |
                           {zn.get(z, f'zone {z}') for o in info['containedIn'] for z in o['zones']})
            reasons, worth = [], False
            if ratio >= xp_floor:
                reasons.append(f'XP {ratio}x level median (guides include from {xp_floor}x)')
                worth = True
            if follow:
                reasons.append(f'starts a chain of {len(follow) + 1}' + (f' ({len(new_follow)} new)' if new_follow else ''))
                worth = True
            if best and best['chance'] is not None and best['chance'] < 5 and not follow:
                reasons.append(f"low drop chance {best['chance']}%")
                worth = ratio >= 2 * xp_floor
            if best and best['classification'] in (1, 2, 4):  # elite / rare elite / rare
                reasons.append(f"{best['name']} is elite/rare")
            results.append({'quest': qid, 'name': q['name'], 'level': q['level'], 'item': info['id'],
                            'itemName': info['name'], 'zones': zones, 'droppedBy': info['droppedBy'][:5],
                            'containedIn': info['containedIn'][:3], 'xpRatio': ratio, 'chain': follow,
                            'worth': worth, 'reasons': reasons})
    results.sort(key=lambda r: (r['level'], r['quest']))
    # new quests with no quest giver and no confirmed starting item: placed by hand from comments
    found = {r['quest'] for r in results}
    unresolved = [q for q in quests.values()
                  if q.get('status') == 'new' and q['zoneId'] != 16941 and q['id'] not in found
                  and not (q['start'] and q['start'].get('coords'))]
    os.makedirs(OUT, exist_ok=True)
    json.dump({'examples': list(ex.values()), 'xpFloor': xp_floor, 'chainRate': chain_rate,
               'quests': results}, open(os.path.join(OUT, 'item_starts.json'), 'w', encoding='utf-8'), indent=1)

    md = ['# Item-started new quests', '',
          f'Learned from {len(ex)} item-started quests already in the guides: median XP ratio '
          f'{statistics.median(ratios) if ratios else 0}x, {round(100 * chain_rate)}% lead into a chain. '
          f'Inclusion floor: {xp_floor}x level-median XP, or starts a chain.', '']
    for r in results:
        src = ', '.join(f"{d['name']} ({d['chance']}%)" for d in r['droppedBy'][:3]) or \
            ', '.join(o['name'] for o in r['containedIn'][:3]) or 'unknown source'
        md.append(f"- [{'x' if r['worth'] else ' '}] **{r['quest']} {r['name']}** L{r['level']} — "
                  f"{r['itemName']} from {src} in {', '.join(r['zones']) or '?'}. {'; '.join(r['reasons'])}")
    md += ['', '## Unresolved starts (no quest giver or starting item on Wowhead)', '']
    for q in sorted(unresolved, key=lambda q: (q['level'], q['id'])):
        top = q['comments'][0]['body'][:200].replace('\n', ' ') if q['comments'] else 'no comments'
        md.append(f"- {q['id']} {q['name']} L{q['level']} (class {q['reqclass']}) — {q['objectiveText'][:90]} "
                  f"| top comment: {top}")
    open(os.path.join(OUT, 'item_starts.md'), 'w', encoding='utf-8').write('\n'.join(md) + '\n')
    print(f'{len(ex)} guide examples, xp floor {xp_floor}, chain rate {chain_rate:.0%}; '
          f'{len(results)} new item-started quests, {sum(r["worth"] for r in results)} worth doing')


if __name__ == '__main__':
    main()
