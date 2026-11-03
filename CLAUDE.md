# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is
ForeverQuest is a free WoW Forever addon for Alliance, focused on doing **every new Forever quest** rather than leveling as fast as possible. It is a fork of RestedXP Guides (RXPGuides v4.11.27), licensed CC BY-NC-SA 4.0. The plan is in `C:\Users\Aaron\.claude\plans\i-want-to-make-misty-rose.md`.

## Hard rules
- **License:** the addon stays free and non-commercial, keeps `ForeverQuest/LICENSE` and `CREDITS.md`, and every upstream change gets a line in `CREDITS.md`.
- **No RestedXP premium content.** Never transcribe, decode or copy RestedXP's paid guides or import strings, even though the user owns them. Routes above level 20 are written from scratch using Wowhead data.
- The user's archive includes `Guides/forever/RestedXP-Skyborne_01.lua`, with 21–60 routes and dungeon guides. It isn't in the public repo, so we treat it as paid content the user bought. It must **never** go into `ForeverQuest/` or git. Only files in the public GitHub repo count as free.
- `ForeverQuest_Personal/` (gitignored) is a separate add-on for the user's own use only (`## Dependencies: ForeverQuest`). It holds that 21–60 guide, which we adapt for Forever by adding missing new quests and fixing changed or removed ones, not rewriting it. Its guides register through the global `RXPGuides.RegisterGuide`. Don't copy its content into the shareable addon.
- When guide hint text is based on Wowhead comments, write it in our own words and never paste comments verbatim.

Rules for where new quests go (questing vs. dungeon route, item-started quests, cuts) are in `tools/ROUTING_RULES.md`.

## Layout
- `ForeverQuest/`: the addon folder. Copy or link it into the Forever client's `Interface/AddOns/ForeverQuest`.
- `reference/RXPGuides-v4.11.27/`: an untouched upstream copy, gitignored. It's for diffing and for free Classic routes such as `Guides/RestedXP Alliance 23-30.lua`. Never load it in game.
- `tools/`: the Python data pipeline (stdlib only). `data/`: Wowhead scrape cache and review files.

## Data pipeline (`tools/`, Python 3.12, stdlib only)
Wowhead blocks plain HTTP (403), so pages are fetched **inside the user's Chrome** (Claude in Chrome, a wowhead.com tab) with in-page `fetch()`. The page posts each result to `python tools/receiver.py`, a local sink on 127.0.0.1:8765 that writes under `data/`. Chrome needed the site's local-network permission for that. Raw pages (`data/wowhead/raw*/`) are gitignored.
1. List pages → `data/wowhead/list/*.json` → `python tools/merge_list.py` → `quest_list.json` (every Alliance/Both quest) and `new_quests.json` (`envChange.status == "new"`).
2. Quest pages → `data/wowhead/raw/<id>.json` → `python tools/parse_quest_pages.py [ids]` → `data/wowhead/quests/<id>.json`. Each holds start/end NPC with zone %, `objectiveRows` in `.complete` index order, mapper points, series and comments.
3. `python tools/build_graph.py`: coverage by zone. `python tools/item_starts.py`: item-started quests. `python tools/gather_review.py`: keep/cut for gather quests, learned from RXP's own choices, written to `data/review/decisions.json`.
4. `python tools/coords.py` fits a world↔zone-% transform for each uiMapID from NPCs found in both guides and Wowhead (`data/analysis/zone_transforms.json`).
5. `python tools/propose_inserts.py [--zone Z] [--apply]` drafts steps into `data/review/inserts/*.md` (`D_` = dungeon route). `--apply` writes them into the guides, tagged `--FQ <qid>`.
6. `python tools/remove_inserts.py [qid ...]` removes FQ-inserted steps (no ids = everything `excluded()` now rejects).
7. `python tools/validate.py [--alliance]` checks the guides: #next links, accept/turn-in balance, and coverage, which applies the routing rules and lists `PENDING` quests that are waiting on Wowhead data.
8. `python tools/build_speed.py [--report]` builds the speed route: copies of the Alliance route guides in the groups "ForeverQuest Speed (A)" and "ForeverQuest Speed Dungeon (A)", under `Guides/forever/speed/`, plus `ForeverQuest_Personal/Guides/Speed-RestedXP-Skyborne_01.lua`. They keep the original RestedXP steps and only the FQ quests worth their time, scored as XP per minute against the route's typical rate, with detour, objectives and chains taken into account. The review goes to `data/review/speed_review.md` and hand overrides to `data/review/speed_decisions.json`. **The speed files are generated, so don't edit them. Edit the completionist guides and rerun it.**

## Addon architecture (inherited from RXP)
- Forever is game type **`camelot`**, Interface **16001**. The engine sets `addon.game == "FOREVER"` when `gameVersion` is between 16000 and 20000 (`RXPGuides.lua`). `ForeverQuest.toc` keeps only entries whose `[AllowLoadGameType ...]` includes `camelot`.
- Load chain: `ForeverQuest.toc` → `DB/forever.xml` (Forever DB tables) → `Guides/GuideList-forever.xml`, which lists every guide `.lua`. **A new guide file must be added to `GuideList-forever.xml` or it won't load.**
- The internal globals stay `RXP`/`RXPGuides`/`RXPData`... and are not renamed. That's why RXPGuides must be disabled while ForeverQuest is loaded; `Conflict.lua` warns about it.
- Each guide file is `RXPGuides.RegisterGuide([[ ... ]])` holding a text DSL. It starts with an early `return` faction/locale guard, then header lines (`#forever`, `#name`, `#group`, `#subgroup`, `#next`, `#defaultfor`, `<< Alliance`) and `step` blocks. A step is made of dot-commands parsed in `functions.lua` (`addon.functions[...]`): `.accept/.turnin <qid>`, `.complete <qid>,<objIndex>`, `.collect <itemId>,<n>[,<qid>,<obj>]`, `.goto`, `.target`, `.xp`, `.home`, `.fly/.fp`. `>>` adds player-facing text, `<< Race/Class` sets conditions, and `#label`/`#completewith`/`#sticky`/`#optional` control flow.
- `.goto` accepts two forms (`functions.lua` goto → `map.lua` `addon.GetMapInfo`):
  - `.goto 1434/0,wx,wy`: a uiMapID plus a world-coordinate instance. Upstream Forever guides use this.
  - `.goto Westfall,56.3,47.5`: a zone name and zone percentages, the same format Wowhead uses. **Generated steps use this form.** Stormwind has special names (`StormwindClassic`/`StormwindNew`).
- Existing Forever guides: `Guides/forever/Alliance-*.lua` (1–20 by race), `RestedXP-Skyborne*.lua` (Skyborne is a new Forever race), and `dungeon/` variants. New Forever quests have high IDs, such as 92909 and 255007.
