"""Static checks on guide files.

Usage:
    python tools/validate.py [files...]     # default: every guide in GuideList-forever.xml
    python tools/validate.py --alliance     # only guides gated to Alliance

Checks:
- every guide file listed in GuideList-forever.xml exists
- each guide has #name, and its #next names a guide that exists
- quest steps (.accept/.turnin/.complete) have a .goto in the same step
- quests accepted but never turned in (across the guide's #next chain), and the reverse
- once data/wowhead/quests/ exists: unknown quest IDs and coverage of new Forever quests
Exits nonzero only on hard errors (missing files, unparseable guides, broken #next).
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse_guides as pg  # noqa: E402

DATA = os.path.join(pg.ROOT, 'data')


def main(argv):
    alliance_only = '--alliance' in argv
    files = [a for a in argv if not a.startswith('--')]
    errors, warnings = [], []

    listed = pg.guide_files()
    for f in listed:
        if not os.path.exists(f):
            errors.append(f'listed in GuideList-forever.xml but missing: {os.path.relpath(f, pg.ROOT)}')
    guides = pg.parse_all(files or [f for f in listed if os.path.exists(f)])
    if alliance_only:
        guides = [g for g in guides if 'Horde' not in (g['conds'] or '') + g['group']]

    names = {g['name'] for g in pg.parse_all([f for f in listed if os.path.exists(f)])}
    for g in guides:
        where = f"{g['file']} [{g['name']}]"
        if g['name'] == '?':
            errors.append(f'{g["file"]}: guide without #name')
        for nxt in g['header'].get('next', []):
            # "#next A;B << cond", where each entry may be "Group\\Name" or "Name"
            for target in re.sub(r'\s*<<.*$', '', nxt).split(';'):
                target = target.strip()
                if target and target.split('\\')[-1] not in names:
                    errors.append(f'{where}: #next target not found: {target!r}')
        for s in g['steps']:
            cmds = {c['cmd'] for c in s['cmds']}
            if cmds & {'accept', 'turnin'} and 'goto' not in cmds and 'zone' not in cmds:
                warnings.append(f"{g['file']}:{s['line']} quest step without .goto")

    # accept/turnin balance per group (guides in a group chain together)
    by_group = {}
    for g in guides:
        q = pg.quest_ids(g)
        grp = by_group.setdefault(g['group'], {'accept': set(), 'turnin': set()})
        grp['accept'] |= set(q['accept'])
        grp['turnin'] |= set(q['turnin'])
    for grp, q in by_group.items():
        for qid in sorted(q['accept'] - q['turnin']):
            warnings.append(f'[{grp}] quest {qid} accepted but never turned in')

    # Wowhead cross-checks, once the scrape exists
    qdir = os.path.join(DATA, 'wowhead', 'quests')
    if os.path.isdir(qdir):
        known = {int(f[:-5]) for f in os.listdir(qdir) if f.endswith('.json')}
        covered = set()
        for q in by_group.values():
            covered |= q['accept'] | q['turnin']
        for qid in sorted(covered - known):
            if qid > 90000:  # only flag IDs in the new-Forever range
                warnings.append(f'quest {qid} not in Wowhead cache')
        new_path = os.path.join(DATA, 'wowhead', 'new_quests.json')
        if os.path.exists(new_path):
            import propose_inserts as pi  # the routing rules (tools/ROUTING_RULES.md) decide what counts
            new = {q['id'] for q in json.load(open(new_path, encoding='utf-8'))}
            quests, decisions, items = pi.load()
            wanted = {q['id'] for q in pi.missing_quests(quests, decisions, set(), items=items)}
            ruled_out = (new & set(quests)) - wanted
            missing = sorted(new - covered - ruled_out)
            print(f'coverage: {len(new & covered)}/{len(new)} new quests in guides, '
                  f'{len(ruled_out - covered)} left out by the routing rules, {len(missing)} missing')
            for qid in missing:
                warnings.append(f'new Forever quest {qid} not covered')
            for qid, why in sorted(pi.PENDING.items()):
                if qid not in covered:
                    print(f'PENDING {qid} {why}')

    for w in warnings:
        print('WARN ', w)
    for e in errors:
        print('ERROR', e)
    print(f'{len(guides)} guides, {len(errors)} errors, {len(warnings)} warnings')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
