"""Build the speed-leveling route: the original RestedXP route plus only the new Forever quests that
pay for the time they take. New quests are preferred: the bar is set lower than for an old quest.

Each FQ-inserted quest gets an estimated time in minutes:
    TALK_MIN (accept + turn in) + detour * RUN_MIN + kills * KILL_MIN + drops * ITEM_MIN
where detour is how far (zone %) its steps pull the player off the original route, summed over its
steps, and a step in a zone neither neighbouring route step is in counts as LEAVE_ZONE. Its rate is
XP per minute against the route's typical rate (the level's median quest XP per QUEST_MIN minutes).
A quest stays when its rate is at least KEEP_RATIO, or when its chain from here on clears the bar. Cutting a quest cuts every
later quest of its chain. Profession quests and slow gather quests are always cut.

Hand overrides: data/review/speed_decisions.json, {"<qid>": "keep" | "cut"}.

Output:
    ForeverQuest/Guides/forever/speed/*.lua              groups "ForeverQuest Speed (A)" and
                                                         "ForeverQuest Speed Dungeon (A)"
    ForeverQuest_Personal/Guides/Speed-Skyborne_01.lua   the same for the private 21-60 guide
    data/review/speed_review.md                          every new quest, kept or cut, and why

Usage: python tools/build_speed.py [--report]       # --report: write the review only
"""
import json
import os
import re
import sys
from collections import defaultdict

import parse_guides as pg
import propose_inserts as pi
import remove_inserts as ri
from item_starts import median_xp_by_level, quest_list

ROOT = pg.ROOT
REVIEW = os.path.join(ROOT, 'data', 'review')
SPEED_NORMAL = 'ForeverQuest Speed (A)'
SPEED_DUNGEON = 'ForeverQuest Speed Dungeon (A)'
RENAME = {pi.GROUP_NORMAL: SPEED_NORMAL, pi.GROUP_DUNGEON: SPEED_DUNGEON}

KEEP_RATIO = 0.6    # of the route's typical XP/min; below 1 because new quests are preferred
QUEST_MIN = 4.0     # minutes a typical route quest takes, all in
TALK_MIN = 0.5      # accept + turn in at NPCs the route already stands next to
RUN_MIN = 0.035     # minutes per zone % of extra running (a zone is ~3.5 min across on foot)
LEAVE_ZONE = 60.0   # detour charged for a step in a zone neither neighbouring route step is in
BACKGROUND = 0.4    # #completewith/#sticky steps happen while doing other things
KILL_MIN = 0.25     # per mob to kill
ITEM_MIN = 0.35     # per drop to collect
BREADCRUMB = 0.15   # value of a quest Wowhead shows no XP for (breadcrumbs, mostly)
SLOW_DROP = 15.0    # item-started quests from rarer drops than this % are cut

FQ_HEAD = re.compile(r'^step\b.*--FQ (\d+)')


def fq_steps(path):
    """{line number: FQ host qid} for the FQ step headers in a file."""
    out = {}
    for i, l in enumerate(open(path, encoding='utf-8').read().split('\n')):
        m = FQ_HEAD.match(l)
        if m:
            out[i + 1] = int(m.group(1))
    return out


def step_qids(step):
    ids = set()
    for c in step['cmds']:
        if c['cmd'] in ('accept', 'turnin', 'complete') and c['args'] and c['args'][0].lstrip('-').isdigit():
            ids.add(int(c['args'][0].lstrip('-')))
        elif c['cmd'] == 'collect' and len(c['args']) >= 3 and c['args'][2].isdigit():
            ids.add(int(c['args'][2]))
    return ids


def leg(a, b):
    if not a or not b:
        return 0.0
    if a[0] != b[0]:
        return LEAVE_ZONE
    return pi.dist(a[1:], b[1:])


def detours(guides):
    """qid -> zone % of extra running its FQ steps add, worst route branch."""
    by_file = {}
    out = defaultdict(float)
    for g in guides:
        if g['file'] not in by_file:
            by_file[g['file']] = fq_steps(os.path.join(ROOT, g['file']))
        heads = by_file[g['file']]
        steps = g['steps']
        locs = [pi.step_location(s) for s in steps]
        fq = [heads.get(s['line']) is not None for s in steps]
        per_guide = defaultdict(float)
        for i, s in enumerate(steps):
            if not fq[i] or not locs[i]:
                continue
            prev = next((locs[j] for j in range(i - 1, -1, -1) if not fq[j] and locs[j]), None)
            nxt = next((locs[j] for j in range(i + 1, len(steps)) if not fq[j] and locs[j]), None)
            here = locs[i]
            if prev and nxt and here[0] not in (prev[0], nxt[0]):
                extra = LEAVE_ZONE
            elif prev and nxt:
                extra = max(0.0, leg(prev, here) + leg(here, nxt) - leg(prev, nxt))
            else:
                extra = leg(prev or nxt, here)
            if 'completewith' in s['tags'] or 'sticky' in s['tags']:
                extra *= BACKGROUND
            ids = step_qids(s) or {heads[s['line']]}
            for q in ids:
                per_guide[q] += extra / len(ids)
        for q, d in per_guide.items():
            out[q] = max(out[q], d)
    return out


def objective_cost(q):
    cost = 0.0
    for r in q.get('objectiveRows') or []:
        if r['type'] == 'npc':
            cost += KILL_MIN * min(r['count'], 20)
        elif r['type'] == 'item':
            cost += ITEM_MIN * min(r['count'], 20)
    return cost


def upstream_accepts(guides):
    """Quests an original (non-FQ) step accepts: their FQ steps must stay or the quest dangles."""
    heads, out = {}, set()
    for g in guides:
        if g['file'] not in heads:
            heads[g['file']] = fq_steps(os.path.join(ROOT, g['file']))
        for st in g['steps']:
            if st['line'] not in heads[g['file']]:
                out |= {int(c['args'][0]) for c in st['cmds'] if c['cmd'] == 'accept' and c['args']
                        and c['args'][0].isdigit()}
    return out


def score(quests, items, decisions, guides, all_text):
    lst = quest_list()
    med = median_xp_by_level(lst)
    fq_ids = {int(m) for m in re.findall(r'--FQ (\d+)', all_text)}
    det = detours(guides)
    upstream = upstream_accepts(guides)
    rows = {}
    for qid in fq_ids:
        q = quests.get(qid)
        if not q:
            continue
        level = q['level'] if q['level'] and q['level'] > 0 else (q.get('reqlevel') or 1)
        # value in "typical route quests"; cost in typical-quest durations, so value/cost = rate vs route
        value = (q['xp'] / med.get(level, med.get(level - 1, 1000) or 1000)) if q['xp'] else BREADCRUMB
        cost = (TALK_MIN + det.get(qid, 0.0) * RUN_MIN + objective_cost(q)) / QUEST_MIN
        why = []
        hard = None
        if q['name'].startswith('Camping 101') or re.search(
                rf'step --FQ {qid} accept\n\s*\.skill \w+,<1,1', all_text):
            hard = 'profession quest'
        it = items.get(qid)
        if it and not (q.get('start') or {}).get('coords'):
            best = max([d['chance'] for d in it['droppedBy']] or [100.0])
            if it['droppedBy'] and best < SLOW_DROP:
                hard = f'starts from a {best}% drop'
        if decisions.get(str(qid)) == 'keep' and any(r['type'] == 'item' for r in q.get('objectiveRows') or []):
            why.append('gather quest kept in review')
        if qid in upstream:
            hard = 'keep: the original route already accepts it'
        rows[qid] = {'id': qid, 'name': q['name'], 'level': level, 'xp': q['xp'], 'value': round(value, 2),
                     'detour': round(det.get(qid, 0.0), 1), 'cost': round(cost, 2),
                     'ratio': round(value / cost, 2), 'hard': hard, 'why': why}
    return rows


def ancestors(qid, rows, quests):
    """Scored quests that qid needs first: the closest scored quest up its Wowhead series, plus any
    scored quest whose turn-in NPC gives qid (Wowhead leaves the series empty for some chains)."""
    out = set()
    p, seen = pi.PREV.get(qid), set()
    while p is not None and p not in rows and p not in seen:
        seen.add(p)
        p = pi.PREV.get(p)
    if p in rows:
        out.add(p)
    start = (quests[qid].get('start') or {}).get('id')
    if start:
        for a in rows:
            end = (quests[a].get('end') or {}).get('id')
            if a != qid and end == start and (rows[a]['level'], a) < (rows[qid]['level'], qid)                     and rows[qid]['level'] - rows[a]['level'] <= 1 and not pi.PREV.get(qid):
                out.add(a)
    return out


def chains(rows, deps):
    nxt = defaultdict(list)
    for qid, ps in deps.items():
        for p in ps:
            nxt[p].append(qid)
    return nxt


def decide(rows, overrides, quests):
    deps = {qid: ancestors(qid, rows, quests) for qid in rows}
    nxt = chains(rows, deps)

    def tail(qid, seen=()):
        """(value, cost) of qid plus its whole chain onward."""
        v, c = rows[qid]['value'], rows[qid]['cost']
        for n in nxt.get(qid, []):
            if n not in seen:
                tv, tc = tail(n, seen + (qid,))
                v, c = v + tv, c + tc
        return v, c

    keep = {}
    for qid, r in rows.items():
        o = overrides.get(str(qid))
        if o:
            keep[qid], r['reason'] = o == 'keep', f'hand {o}'
        elif r['hard']:
            keep[qid], r['reason'] = r['hard'].startswith('keep:'), r['hard']
        elif r['ratio'] >= KEEP_RATIO:
            keep[qid], r['reason'] = True, f'{r["ratio"]} value per cost'
        else:
            v, c = tail(qid)
            ok = nxt.get(qid) and v / c >= KEEP_RATIO
            keep[qid] = bool(ok)
            r['reason'] = (f'leads into a chain worth {round(v / c, 2)}' if ok
                           else f'{r["ratio"]} value per cost (bar {KEEP_RATIO})')
    # a cut quest takes its whole chain onward with it, unless a hand override says otherwise
    changed = True
    while changed:
        changed = False
        for qid, r in rows.items():
            cut_p = [p for p in deps[qid] if not keep[p]]
            if keep.get(qid) and cut_p and overrides.get(str(qid)) != 'keep' and not (r['hard'] or '').startswith('keep:'):
                p = cut_p[0]
                keep[qid], r['reason'] = False, f'needs {p} {rows[p]["name"]}, which is cut'
                changed = True
    return keep


# ---------------------------------------------------------------- output

def split_guides(src):
    """(preamble, [guide text], tail) of a file of RegisterGuide([[...]]) calls."""
    parts, pos, pre = [], 0, None
    for m in pg.GUIDE_RE.finditer(src):
        if pre is None:
            pre = src[:m.start()]
            if pre.endswith('RXPGuides.'):
                pre = pre[:-len('RXPGuides.')]
        parts.append(m.group(2))
        pos = src.index(')', m.end()) + 1
    return pre or '', parts, src[pos:]


def speed_guide(text):
    """The guide's text for the speed groups, or None when it belongs to no Alliance route group."""
    lines, groups = [], 0
    for l in text.split('\n'):
        s = l.strip()
        if s.startswith('#group '):
            g = s[7:].split('<<')[0].strip()
            if g not in RENAME:
                continue
            groups += 1
            l = l.replace(g, RENAME[g])
        elif s.startswith('#defaultfor'):
            continue  # the completionist route stays the default
        elif s.startswith('#include') or s.startswith('#next'):
            for old, new in RENAME.items():
                l = l.replace(old + '\\', new + '\\')
        lines.append(l)
    return '\n'.join(lines) if groups else None


def write_speed(src_path, dst_path, cut):
    src = open(src_path, encoding='utf-8').read()
    pre, guides, tail = split_guides(src)
    kept = [t for t in (speed_guide(g) for g in guides) if t is not None]
    if not kept:
        return 0
    body = '\n'.join(f'RXPGuides.RegisterGuide([[{t}]])\n' for t in kept)
    out, removed = ri.prune(pre + body + tail, cut)
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    open(dst_path, 'w', encoding='utf-8', newline='').write(out)
    return removed


def register(xml_path, rel_paths):
    xml = open(xml_path, encoding='utf-8').read()
    add = [p for p in rel_paths if f'"{p}"' not in xml]
    if add:
        block = ''.join(f'    <Script file="{p}"/>\n' for p in add)
        xml = xml.replace('</Ui>', '\n    <!-- ForeverQuest speed route (tools/build_speed.py) -->\n' + block + '</Ui>')
        open(xml_path, 'w', encoding='utf-8', newline='').write(xml)


def main(argv):
    quests, decisions, items = pi.load()
    files = [f for f in pg.guide_files() if '/speed/' not in f.replace('\\', '/')
             and not os.path.basename(f).startswith('Speed-')]
    guides = [g for g in pg.parse_all(files) if any(
        x.split('<<')[0].strip() in RENAME for x in g['header'].get('group', []))]
    all_text = '\n'.join(open(f, encoding='utf-8').read() for f in files)
    ov_path = os.path.join(REVIEW, 'speed_decisions.json')
    overrides = json.load(open(ov_path)) if os.path.exists(ov_path) else {}
    rows = score(quests, items, decisions, guides, all_text)
    keep = decide(rows, overrides, quests)
    cut = {q for q, k in keep.items() if not k}

    lines = ['# Speed route review', '',
             f'{len(keep) - len(cut)} of {len(keep)} new Forever quests in the completionist route stay in the speed route. '
             f'Bar: {KEEP_RATIO} of the route typical XP per minute (value = XP / level-median quest XP; '
             f'cost = estimated minutes / {QUEST_MIN:g}). '
             'Override in data/review/speed_decisions.json and rerun tools/build_speed.py.', '',
             '| | quest | L | XP | value | detour % | cost | reason |', '|---|---|---|---|---|---|---|---|']
    for r in sorted(rows.values(), key=lambda r: (r['level'], r['id'])):
        lines.append(f"| {'keep' if keep[r['id']] else 'CUT'} | {r['id']} {r['name']} | {r['level']} | {r['xp']} | "
                     f"{r['value']} | {r['detour']} | {r['cost']} | {r['reason']} |")
    open(os.path.join(REVIEW, 'speed_review.md'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    print(f'speed route keeps {len(keep) - len(cut)}/{len(keep)} new quests; review in data/review/speed_review.md')
    if '--report' in argv:
        return 0

    made, removed = [], 0
    for f in files:
        rel = os.path.relpath(f, ROOT).replace('\\', '/')
        if rel.startswith('ForeverQuest_Personal/'):
            dst = os.path.join(pg.PERSONAL, 'Guides', 'Speed-' + os.path.basename(f))
        elif rel.startswith('ForeverQuest/Guides/forever/'):
            sub = rel[len('ForeverQuest/Guides/forever/'):]
            dst = os.path.join(pg.ADDON, 'Guides', 'forever', 'speed', sub)
        else:
            continue
        n = write_speed(f, dst, cut)
        if os.path.exists(dst):
            made.append(dst)
            removed += n
    register(os.path.join(pg.ADDON, 'Guides', 'GuideList-forever.xml'),
             [os.path.relpath(p, pg.ADDON).replace('\\', '/') for p in made if p.startswith(pg.ADDON + os.sep)])
    toc = os.path.join(pg.PERSONAL, 'ForeverQuest_Personal.toc')
    if os.path.exists(toc):
        t = open(toc, encoding='utf-8').read()
        for p in made:
            if p.startswith(pg.PERSONAL + os.sep):
                entry = os.path.relpath(p, pg.PERSONAL)
                if entry not in t:
                    t = t.rstrip('\n') + '\n' + entry + '\n'
        open(toc, 'w', encoding='utf-8', newline='').write(t)
    for p in made:
        print('wrote', os.path.relpath(p, ROOT))
    print(f'{removed} FQ steps left out of the speed copies')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
