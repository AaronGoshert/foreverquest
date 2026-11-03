"""Merge hand-written hints (data/review/hints.json: {"<qid>": [">>line", ...]}) into the
`--FQ <qid> objective` steps that propose_inserts.py added, just before the step's first ">>" line.
Hint lines are tagged `--FQhint`, so re-running replaces them.

Usage: python tools/apply_hints.py
"""
import glob
import json
import os

import parse_guides as pg

ROOT = pg.ROOT
HINT_TAG = ' --FQhint'


def objective_qid(step_line):
    """'step << Priest --FQ 123 objective' -> '123'"""
    if '--FQ ' not in step_line:
        return None
    parts = step_line.split('--FQ ')[1].split()
    return parts[0] if len(parts) > 1 and parts[1] == 'objective' else None


def main():
    hints = json.load(open(os.path.join(ROOT, 'data', 'review', 'hints.json'), encoding='utf-8'))
    files = glob.glob(os.path.join(pg.ADDON, 'Guides', '**', '*.lua'), recursive=True) + \
        glob.glob(os.path.join(pg.PERSONAL, 'Guides', '*.lua'))
    done = set()
    for path in files:
        src = open(path, encoding='utf-8').read()
        if '--FQ ' not in src:
            continue
        out, current, inserted = [], None, False
        for l in src.split('\n'):
            if HINT_TAG in l:
                continue  # old hint, re-added below
            if l.startswith('step'):
                current, inserted = objective_qid(l), False
            if current in hints and not inserted and l.lstrip().startswith('>>'):
                out += [f'    {h}{HINT_TAG}' for h in hints[current]]
                inserted = True
                done.add(current)
            out.append(l)
        new = '\n'.join(out)
        if new != src:
            open(path, 'w', encoding='utf-8', newline='').write(new)
            print(f'{os.path.relpath(path, ROOT)}: hints updated')
    missing = set(hints) - done
    print(f'{len(done)} quests got hints' + (f'; not in the guides yet: {sorted(missing)}' if missing else ''))


if __name__ == '__main__':
    main()
