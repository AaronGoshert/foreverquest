"""Merge data/wowhead/list/*.json (Wowhead listview pages) into:
    data/wowhead/quest_list.json   every Alliance/Both quest, deduped by id
    data/wowhead/new_quests.json   only those Wowhead marks as new in Forever
"""
import glob
import json
import os
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WH = os.path.join(ROOT, 'data', 'wowhead')

quests = {}
for f in sorted(glob.glob(os.path.join(WH, 'list', '*.json'))):
    for q in json.load(open(f, encoding='utf-8')):
        quests[q['id']] = q

rows = sorted(quests.values(), key=lambda q: (q['level'], q['id']))
status = Counter((q.get('envChange') or {}).get('status', 'none') for q in rows)
new = [q for q in rows if (q.get('envChange') or {}).get('status') == 'new']
json.dump(rows, open(os.path.join(WH, 'quest_list.json'), 'w', encoding='utf-8'), indent=1)
json.dump(new, open(os.path.join(WH, 'new_quests.json'), 'w', encoding='utf-8'), indent=1)
print(f'{len(rows)} quests ({dict(status)}); {len(new)} new')
print('new by level band:', dict(sorted(Counter((q['level'] - 1) // 10 * 10 + 1 for q in new).items())))
