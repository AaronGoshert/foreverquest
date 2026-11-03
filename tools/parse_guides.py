"""Parse RXP-format guide files into a structured form.

Usage:
    python tools/parse_guides.py [files...]        # summary of each guide
    python tools/parse_guides.py --json out.json   # dump everything

With no files, it parses every guide listed in ForeverQuest/Guides/GuideList-forever.xml.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON = os.path.join(ROOT, 'ForeverQuest')
PERSONAL = os.path.join(ROOT, 'ForeverQuest_Personal')

GUIDE_RE = re.compile(r'RegisterGuide\(\s*\[(=*)\[(.*?)\]\1\]', re.S)
QUEST_CMDS = {'accept', 'turnin', 'complete', 'collect', 'abandon'}


def guide_files():
    xml = open(os.path.join(ADDON, 'Guides', 'GuideList-forever.xml'), encoding='utf-8').read()
    xml = re.sub(r'<!--.*?-->', '', xml, flags=re.S)
    files = [os.path.join(ADDON, f) for f in re.findall(r'<Script file="([^"]+)"', xml)
             if not f.endswith('Import.lua')]
    # the user's private add-on (gitignored), loaded after ForeverQuest
    toc = os.path.join(PERSONAL, 'ForeverQuest_Personal.toc')
    if os.path.exists(toc):
        files += [os.path.join(PERSONAL, l.strip().replace('\\', '/')) for l in open(toc, encoding='utf-8')
                  if l.strip().endswith('.lua')]
    return files


def split_cond(line):
    """'.accept 12 >> text << Human' -> ('.accept 12 >> text', 'Human')"""
    if '<<' in line:
        body, cond = line.rsplit('<<', 1)
        return body.rstrip(), cond.strip()
    return line, None


def parse_text(text, file=None, line_offset=0):
    guide = {'file': file, 'header': {}, 'conds': None, 'steps': []}
    step = None
    for i, raw in enumerate(text.split('\n')):
        lineno = line_offset + i
        line = raw.strip()
        if not line or line.startswith('--'):
            continue
        if line == 'step' or line.startswith('step ') or line.startswith('step<<'):
            _, cond = split_cond(line)
            step = {'line': lineno, 'conds': cond, 'tags': {}, 'cmds': [], 'text': []}
            guide['steps'].append(step)
            continue
        if step is None:  # header
            if line.startswith('#'):
                key, _, val = line[1:].partition(' ')
                guide['header'].setdefault(key, []).append(val.strip())
            elif line.startswith('<<'):
                guide['conds'] = line[2:].strip()
            continue
        body, cond = split_cond(line)
        body = re.sub(r'\s--.*$', '', body)  # trailing comment
        if body.startswith('#'):
            key, _, val = body[1:].partition(' ')
            step['tags'][key] = val.strip()
        elif body.startswith('.'):
            m = re.match(r'\.(\w+)\s*([^>]*?)\s*(?:>>\s*(.*))?$', body)
            if not m:
                continue
            name, args, msg = m.groups()
            step['cmds'].append({'cmd': name, 'args': [a.strip() for a in args.split(',')] if args else [],
                                 'text': msg, 'conds': cond, 'line': lineno})
        elif body.startswith('>>') or body.startswith('+'):
            step['text'].append(body.lstrip('>+ '))
    return guide


def parse_file(path):
    src = open(path, encoding='utf-8').read()
    guides = []
    for m in GUIDE_RE.finditer(src):
        offset = src.count('\n', 0, m.start(2)) + 1
        g = parse_text(m.group(2), file=os.path.relpath(path, ROOT), line_offset=offset)
        g['name'] = (g['header'].get('name') or ['?'])[0]
        g['group'] = (g['header'].get('group') or [''])[0]
        guides.append(g)
    return guides


def quest_ids(guide):
    """{'accept': {qid: [line..]}, 'turnin': ..., 'complete': ...}"""
    out = {c: {} for c in QUEST_CMDS}
    for s in guide['steps']:
        for c in s['cmds']:
            if c['cmd'] in ('accept', 'turnin', 'complete', 'abandon') and c['args']:
                qid = c['args'][0]
                if qid.isdigit():
                    out[c['cmd']].setdefault(int(qid), []).append(c['line'])
            elif c['cmd'] == 'collect' and len(c['args']) >= 3 and c['args'][2].isdigit():
                out['collect'].setdefault(int(c['args'][2]), []).append(c['line'])
    return out


def parse_all(files=None):
    res = []
    for f in files or guide_files():
        res.extend(parse_file(f))
    return res


if __name__ == '__main__':
    args = sys.argv[1:]
    out = None
    if args[:1] == ['--json']:
        out, args = args[1], args[2:]
    guides = parse_all(args or None)
    if out:
        json.dump(guides, open(out, 'w', encoding='utf-8'), indent=1)
        print(f'wrote {len(guides)} guides to {out}')
    else:
        for g in guides:
            q = quest_ids(g)
            print(f"{g['file']}: {g['name']!r} [{g['group']}] steps={len(g['steps'])} "
                  f"accept={len(q['accept'])} turnin={len(q['turnin'])} conds={g['conds']}")
