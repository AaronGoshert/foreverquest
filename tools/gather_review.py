"""Decide which new gather (collect) quests to add, by learning from the gather quests RestedXP
already includes and the ones it leaves out.

Included examples come from the guides' `.collect <item>,<n>,<qid>` steps; skipped examples are old
Alliance quests the guides don't use (pages in data/wowhead/raw, parsed to data/wowhead/quests).
Features per collect quest:
    overlap  its drop-source mobs are mobs the guides already send you to kill
    chain    another quest follows it
    xpRatio  XP vs the median for its level
    count    items to collect
    slow     comments complain about drop rates / respawns
The rule is fitted from the include rate of each feature combination, then applied to the new
quests. Writes data/review/gather_candidates.md and seeds data/review/decisions.json.

Usage: python tools/gather_review.py
"""
import glob
import json
import os
import re
from collections import defaultdict

import parse_guides as pg
from build_graph import SLOW_WORDS
from item_starts import median_xp_by_level, quest_list

ROOT = pg.ROOT
WH = os.path.join(ROOT, 'data', 'wowhead')
REVIEW = os.path.join(ROOT, 'data', 'review')
MOB_RE = re.compile(r'\|cRXP_ENEMY_([^|]+)\|r')


def norm_mob(name):
    return re.sub(r's$', '', name.strip().lower())  # "Murlocs" ~ "Murloc"


def guide_side():
    """Quests the guides use, which mobs each quest's steps send you to (None = grind/other steps),
    and which quests are turned in at a step that also accepts the next quest (chained)."""
    covered, mobs_by_quest, chained = set(), defaultdict(set), set()
    for g in pg.parse_all():
        if 'Horde' in (g['conds'] or '') + g['group']:
            continue
        q = pg.quest_ids(g)
        covered |= set(q['accept']) | set(q['turnin'])
        for s in g['steps']:
            mobs = {norm_mob(m) for t in s['text'] for m in MOB_RE.findall(t)}
            qids = set()
            for c in s['cmds']:
                if c['cmd'] == 'mob' and c['args']:
                    mobs.add(norm_mob(c['args'][0]))
                if c['text']:
                    mobs |= {norm_mob(m) for m in MOB_RE.findall(c['text'])}
                a = c['args']
                if c['cmd'] == 'complete' and a and a[0].isdigit():
                    qids.add(int(a[0]))
                if c['cmd'] == 'collect' and len(a) >= 3 and a[2].isdigit():
                    qids.add(int(a[2]))
            for qid in qids or {None}:
                mobs_by_quest[qid] |= mobs
            if any(c['cmd'] == 'accept' for c in s['cmds']):
                chained |= {int(c['args'][0]) for c in s['cmds']
                            if c['cmd'] == 'turnin' and c['args'] and c['args'][0].isdigit()}
    return covered, mobs_by_quest, chained


_mob_counts = None


def other_mobs(mobs_by_quest, qid):
    """Mobs that some step other than this quest's own sends you to."""
    global _mob_counts
    if _mob_counts is None:
        _mob_counts = defaultdict(int)
        for mobs in mobs_by_quest.values():
            for m in mobs:
                _mob_counts[m] += 1
    own = mobs_by_quest.get(qid, set())
    return {m for m, n in _mob_counts.items() if n - (m in own) > 0}


def features(q, med, mobs_by_quest, chained_ids):
    guide_mobs = other_mobs(mobs_by_quest, q['id'])
    items = [o for o in q['objectives'] if o['type'] == 'item' and not o.get('provided')]
    if not items:
        return None
    sources = {norm_mob(p['name']) for p in q['points'] if p['point'] == 'sourcerequirement' and p.get('name')}
    series = q.get('series') or []
    return {
        'id': q['id'], 'name': q['name'], 'level': q['level'],
        'zone': (q.get('start') or {}).get('zone'),
        'count': sum(o['count'] for o in items),
        'overlap': bool(sources & guide_mobs),
        'chain': (q['id'] in series and series.index(q['id']) < len(series) - 1) or q['id'] in chained_ids,
        'xpRatio': round(q['xp'] / med[q['level']], 2) if q.get('xp') and med.get(q['level']) else 0,
        'slow': sum(1 for c in q['comments'] if SLOW_WORDS.search(c['body'])),
        'sources': sorted(sources)[:4],
        'topComment': (q['comments'][0]['body'][:160].replace('\n', ' ') if q['comments'] else ''),
    }


def bucket(f):
    return (f['overlap'], f['chain'], f['xpRatio'] >= 1.0, f['slow'] > 0)


def main():
    lst = quest_list()
    med = median_xp_by_level(lst)
    covered, mobs_by_quest, chained = guide_side()
    quests = {q['id']: q for q in (json.load(open(f, encoding='utf-8'))
                                   for f in glob.glob(os.path.join(WH, 'quests', '*.json')))}

    # training set: old collect quests with a parsed page, labelled by whether a guide uses them
    train = []
    # plus new quests RestedXP already added (its own judgement on Forever content)
    for q in quests.values():
        if (q['level'] or 0) < 60 and (q.get('status') != 'new' or q['id'] in covered):
            f = features(q, med, mobs_by_quest, chained)
            if f and f['count'] >= 3:
                train.append((f, q['id'] in covered))

    stats = defaultdict(lambda: [0, 0])
    for f, inc in train:
        stats[bucket(f)][0 if inc else 1] += 1
    n_inc = sum(1 for _, i in train if i)
    n_skip = len(train) - n_inc

    def include_rate(f):
        i, s = stats.get(bucket(f), (0, 0))
        # rates normalised by class size so the larger "included" set doesn't dominate
        pi, ps = i / max(1, n_inc), s / max(1, n_skip)
        return pi / (pi + ps) if pi + ps else 0.5

    new = []
    for q in quests.values():
        if q.get('status') == 'new' and q['zoneId'] != 16941 and q['id'] not in covered:
            f = features(q, med, mobs_by_quest, chained)
            if f and f['count'] >= 3:
                f['rate'] = round(include_rate(f), 2)
                f['verdict'] = 'keep' if f['rate'] >= 0.5 else 'cut'
                if 'maintain your reputation' in q['objectiveText'].lower():
                    f['verdict'] = 'cut'  # reputation turn-ins stay out (ROUTING_RULES.md rule 4)
                    f['topComment'] = '(cut: reputation turn-in) ' + f['topComment']
                new.append(f)
    new.sort(key=lambda f: (f['verdict'], f['level']))

    lines = ['# Gather-quest review', '',
             f'Learned from {n_inc} collect quests RestedXP includes and {n_skip} it leaves out.', '',
             '| overlap | chain | XP >= median | slow comments | included | skipped |',
             '|---|---|---|---|---|---|']
    for b, (i, s) in sorted(stats.items(), key=lambda kv: -kv[1][0]):
        lines.append(f'| {"yes" if b[0] else "no"} | {"yes" if b[1] else "no"} | {"yes" if b[2] else "no"} '
                     f'| {"yes" if b[3] else "no"} | {i} | {s} |')
    lines += ['', '## New gather quests', '',
              'Verdict = keep if quests with the same features are more often included than skipped.', '']
    for f in new:
        lines.append(f"- **{f['verdict'].upper()}** {f['id']} {f['name']} (L{f['level']}, {f['zone']}): "
                     f"collect {f['count']}, overlap {'yes' if f['overlap'] else 'no'}, "
                     f"chain {'yes' if f['chain'] else 'no'}, XP {f['xpRatio']}x, "
                     f"{f['slow']} slow-drop comments, include rate {f['rate']}")
        if f['topComment']:
            lines.append(f"  - top comment: {f['topComment']}")
    os.makedirs(REVIEW, exist_ok=True)
    open(os.path.join(REVIEW, 'gather_candidates.md'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    dec_path = os.path.join(REVIEW, 'decisions.json')
    dec = json.load(open(dec_path)) if os.path.exists(dec_path) else {}
    for f in new:
        dec.setdefault(str(f['id']), f['verdict'])
    json.dump(dec, open(dec_path, 'w'), indent=1, sort_keys=True)
    print(f'trained on {n_inc} included / {n_skip} skipped; {len(new)} new gather quests: '
          f'{sum(f["verdict"] == "keep" for f in new)} keep, {sum(f["verdict"] == "cut" for f in new)} cut')


if __name__ == '__main__':
    main()
