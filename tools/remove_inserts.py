"""Remove steps that propose_inserts.py added (tagged `--FQ <qid>`) for the given quests, or for every
quest propose_inserts.excluded() now rejects. Upstream RXP steps are never touched.

A removed quest's lines are also dropped from merged FQ steps hosted by another quest, and
`#completewith FQend<qid>` background steps go with it.

Usage: python tools/remove_inserts.py [qid ...]     # no ids = everything excluded() rejects
"""
import glob
import os
import re
import sys

import parse_guides as pg
import propose_inserts as pi

ROOT = pg.ROOT
QUEST_LINE = re.compile(r'^\s*\.(accept|turnin|complete|collect)\s+(\d+)(?:,\d+)*(?:,(\d+))?')


def line_qid(line):
    m = QUEST_LINE.match(line)
    if not m:
        return None
    if m.group(1) == 'collect':  # .collect item,n,qid,obj
        args = line.strip().split()[1].split(',')
        return int(args[2]) if len(args) >= 3 and args[2].isdigit() else None
    return int(m.group(2))


def split_steps(lines):
    """[(header_index, [lines])] where a block runs from a 'step' line to the next unindented line."""
    blocks, cur = [], None
    for l in lines:
        if l.startswith('step'):
            cur = [l]
            blocks.append(cur)
        elif cur is not None and (l.startswith((' ', '\t')) or not l.strip()):
            cur.append(l)
        else:
            cur = None
            blocks.append([l])
    return blocks


def prune(src, qids):
    out, removed = [], 0
    for block in split_steps(src.split('\n')):
        head = block[0]
        if not head.startswith('step') or '--FQ ' not in head:
            out += block
            continue
        host = int(head.split('--FQ ')[1].split()[0])
        body = block[1:]
        if host in qids or any(f'#completewith FQend{q}' in l for q in qids for l in body):
            # keep a merged step if it still carries another quest's lines
            rest = [l for l in body if line_qid(l) is not None and line_qid(l) not in qids]
            if not rest:
                removed += 1
                continue
        kept = [l for l in body if line_qid(l) not in qids]
        if not any(line_qid(l) is not None for l in kept):
            removed += 1
            continue
        out += [head] + kept
    return '\n'.join(out), removed


def main():
    if sys.argv[1:]:
        qids = {int(a) for a in sys.argv[1:]}
    else:
        quests, _, _ = pi.load()
        qids = {q['id'] for q in quests.values() if pi.excluded(q)}
    files = glob.glob(os.path.join(pg.ADDON, 'Guides', '**', '*.lua'), recursive=True) + \
        glob.glob(os.path.join(pg.PERSONAL, 'Guides', '*.lua'))
    total = 0
    for path in files:
        src = open(path, encoding='utf-8').read()
        if '--FQ ' not in src:
            continue
        new, n = prune(src, qids)
        if new != src:
            open(path, 'w', encoding='utf-8', newline='').write(new)
            print(f'{os.path.relpath(path, ROOT)}: {n} steps removed')
            total += n
    print(f'{total} steps removed')


if __name__ == '__main__':
    main()
