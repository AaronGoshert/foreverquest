"""Parse raw Wowhead quest pages (data/wowhead/raw/<id>.json) into data/wowhead/quests/<id>.json.

Each output file holds: id, name, level, reqlevel, side, zone, start and end (NPC, object or item,
plus zone and coordinates), objective text, objectives (item/npc/object IDs with counts),
mapper points, series (ordered quest IDs of the chain), and comments (text, rating, replies).

Usage: python tools/parse_quest_pages.py [ids...]     (default: every raw page)
"""
import glob
import html
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WH = os.path.join(ROOT, 'data', 'wowhead')


def js_value(src, start):
    """Return the JSON object/array that begins at src[start] (bracket matched, string aware)."""
    depth, in_str, esc = 0, False, False
    for i in range(start, len(src)):
        c = src[i]
        if in_str:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c in '[{':
            depth += 1
        elif c in ']}':
            depth -= 1
            if depth == 0:
                return json.loads(src[start:i + 1])
    return None


def strip_tags(s):
    return html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', s))).strip()


def parse_infobox(h):
    m = re.search(r'WH\.markup\.printHtml\("(\[ul\].*?)", "infobox-contents', h)
    if not m:
        return {}
    box = m.group(1).replace('\\/', '/').replace('\\"', '"')
    out = {}
    for key in ('Start', 'End'):
        mm = re.search(key + r': \[url=/forever/(npc|object|item)=(\d+)[^\]]*\]([^\[]+)\[/url\]', box)
        if mm:
            out[key.lower()] = {'type': mm.group(1), 'id': int(mm.group(2)), 'name': mm.group(3)}
    mm = re.search(r'Added in patch \[acronym="([^"]+)"', box)
    if mm:
        out['patch'] = mm.group(1)
    out['sharable'] = '[li]Sharable[/li]' in box
    return out


def parse_mapper(h):
    m = re.search(r'new Mapper\(', h)
    if not m:
        return {}
    data = js_value(h, m.end())
    points = []
    for zid, z in (data or {}).get('objectives', {}).items():
        for level in z.get('levels', []):
            for p in level:
                points.append({'zoneId': int(zid), 'zone': z.get('zone'), 'point': p.get('point'),
                               'type': p.get('type'), 'id': p.get('id'), 'name': p.get('name'),
                               'coord': p.get('coord'), 'coords': p.get('coords')})
    return {'points': points, 'missing': (data or {}).get('missing')}


def parse_objectives(h):
    """Objective sentence and item/npc/object requirements between the <h1> and the mapper."""
    a = h.find('<h1')
    b = h.find('new Mapper(', a)
    if a < 0:
        return '', []
    if b > 0:
        b = h.rfind('<script', a, b)
    block = h[a:b if b > 0 else a + 20000]
    block = re.sub(r'<script.*?</script>', '', block, flags=re.S)
    text = strip_tags(block.split('</h1>', 1)[-1])
    text = re.split(r' (?:Provided item|Suggested players|Rewards|Description)\b', text)[0]
    reqs = []
    for t, i, name, rest in re.findall(
            r'href="/forever/(item|npc|object)=(\d+)[^"]*"[^>]*>([^<]+)</a>(.{0,120})', block, re.S):
        cnt = re.match(r'[^(<]{0,40}\(\s*(\d+)\s*\)', strip_tags(rest))
        count = int(cnt.group(1)) if cnt else 1
        same = next((r for r in reqs if (r['type'], r['id']) == (t, int(i))), None)
        if same:  # the summary sentence and the requirement list link the same thing
            same['count'] = max(same['count'], count)
        else:
            reqs.append({'type': t, 'id': int(i), 'name': html.unescape(name), 'count': count,
                         'provided': strip_tags(rest).startswith('(Provided)')})
        if same and strip_tags(rest).startswith('(Provided)'):
            same['provided'] = True
    text = text.replace('�', '')
    for r in reqs:
        # kill objectives aren't linked in the list: "Slay 8 Pesky Cirrusflies" / "Cirrusfly slain ( 8 )"
        stem = re.escape(r['name'][:6])
        m = (re.search(r'\b(\d+)\s+' + stem, text) or
             re.search(stem + r"[\w' -]{0,40}?\(\s*(\d+)\s*\)", text))
        if r['count'] == 1 and m:
            r['count'] = int(m.group(1))
    return text[:600], reqs


def parse_objective_rows(h):
    """Objectives in game order (index = position + 1, as used by `.complete qid,index`).
    Provided items and reputation requirements are not objectives."""
    a = h.find('<h1')
    m = re.compile(r'<table class="icon-list">(.*?)</table>', re.S).search(h, a)
    if not m:
        return []
    rows = []
    for r in re.findall(r'<tr[^>]*>(.*?)</tr>', m.group(1), re.S):
        text = strip_tags(r).replace('\xa0', ' ').strip()
        if '(Provided)' in text:
            continue
        cnt = re.search(r'\(\s*(\d+)\s*\)\s*$', text)
        if not cnt:
            continue  # "( Honored )" style reputation gates
        link = re.search(r'href="/forever/(item|npc|object)=(\d+)', r)
        rows.append({'text': re.sub(r'\s*\(\s*\d+\s*\)\s*$', '', text), 'count': int(cnt.group(1)),
                     'type': link.group(1) if link else 'event', 'id': int(link.group(2)) if link else None})
    return rows


def parse_series(h):
    m = re.search(r'<table class="series">(.*?)</table>', h, re.S)
    if not m:
        return []
    out = []
    for row in re.findall(r'<tr>(.*?)</tr>', m.group(1), re.S):
        # a row can list Horde and Alliance versions; prefer the bold (current) or alliance one
        ids = re.findall(r'quest=(\d+)', row)
        cur = re.search(r'icon-alliance[^>]*><b>', row)
        if cur or not ids:
            out.append(None if not ids else int(ids[-1]) if not cur else 'self')
        else:
            out.append(int(ids[-1]) if 'icon-alliance' in row else int(ids[0]))
    return out


def parse_comments(h):
    m = re.search(r'var lv_comments0 = ', h)
    if not m:
        return []
    out = []
    for c in js_value(h, m.end()) or []:
        if c.get('deleted') or c.get('outofdate'):
            continue
        out.append({'rating': c.get('rating', 0), 'date': c.get('date'), 'body': c.get('body', ''),
                    'replies': [r.get('body', '') for r in c.get('replies', [])]})
    return sorted(out, key=lambda c: -c['rating'])


def parse(qid, listing):
    h = json.load(open(os.path.join(WH, 'raw', f'{qid}.json'), encoding='utf-8'))['html']
    row = listing.get(qid, {})
    info = parse_infobox(h)
    mapper = parse_mapper(h)
    text, reqs = parse_objectives(h)
    series = [qid if s == 'self' else s for s in parse_series(h)]
    if series and qid not in series:
        # the current quest's row is bold without a link
        series = [s if s is not None else qid for s in series]
    q = {
        'id': qid, 'name': row.get('name'), 'level': row.get('level'), 'reqlevel': row.get('reqlevel'),
        'side': row.get('side'), 'zoneId': row.get('category'), 'reqclass': row.get('reqclass'),
        'status': (row.get('envChange') or {}).get('status'), 'xp': row.get('xp'),
        'start': info.get('start'), 'end': info.get('end'), 'patch': info.get('patch'),
        'objectiveText': text, 'objectives': reqs, 'objectiveRows': parse_objective_rows(h),
        'series': series,
        'points': mapper.get('points', []), 'missingPoints': mapper.get('missing'),
        'comments': parse_comments(h),
    }
    # attach coordinates to start/end from the mapper
    for key in ('start', 'end'):
        for p in q['points']:
            if p['point'] == key and q[key] and p['id'] == q[key]['id']:
                q[key].update(zone=p['zone'], zoneId=p['zoneId'], coords=p['coords'])
                break
    return q


def main(ids):
    listing = {q['id']: q for q in json.load(open(os.path.join(WH, 'quest_list.json'), encoding='utf-8'))}
    if not ids:
        ids = [int(os.path.basename(f)[:-5]) for f in glob.glob(os.path.join(WH, 'raw', '*.json'))]
    os.makedirs(os.path.join(WH, 'quests'), exist_ok=True)
    nocoord = []
    for qid in ids:
        q = parse(qid, listing)
        if not (q['start'] and q['start'].get('coords')):
            nocoord.append(qid)
        json.dump(q, open(os.path.join(WH, 'quests', f'{qid}.json'), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
    print(f'parsed {len(ids)} quests; {len(nocoord)} without start coordinates: {nocoord[:30]}')


if __name__ == '__main__':
    main([int(a) for a in sys.argv[1:]])
