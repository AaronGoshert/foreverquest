# Routing rules for inserting new Forever quests

Agreed with the user. The insertion tool and any manual edits follow these.

## Two guide groups (inherited from RestedXP)
- **Questing route:** "RestedXP Forever Guide (A)", marked `#disabledungeons`. No dungeon content.
- **Dungeon route:** "RestedXP Forever Dungeon Guide (A)". The same route, plus dungeon segments such as "17-18 Hall of Thanes" and "33-34 City of Dalaran", and steps gated with `.dungeon TAG`, which only show when the player ticks that dungeon in settings. `.enabledungeon TAG` in a group turns a dungeon on by default.
- Forever dungeon tags are in `ForeverQuest/DB/forever/db.lua` `dungeonList`: HOT, ROL, ES, COD, TDC, KS, AP, BH, TST, plus the Classic dungeons.
- Wowhead files dungeon quests under the dungeon's own category: 16919 HOT, 16611 ROL, 16732 ES, 16544 COD, 16550 TDC, 1581 DM, 491 RFK, 796 SM, and so on.

## Rules
1. **Normal quests** go into both groups at the same spot.
2. **Dungeon quests** go **only** into the dungeon route. Put them in the matching dungeon segment, or gate them with `.dungeon TAG` where the route runs past the dungeon. Never put them in the questing route.
3. **Lead-in chains:** when a normal questing chain naturally hands out a dungeon quest, especially one that ends in or just after the dungeon, the chain steps stay in both routes. The dungeon quest's pickup, the run and the turn-in go only into the dungeon route.
4. **Repeatables and reputation turn-ins** (Gelkis/Magram "Buying Friendship", donations, Economic Warfare) and **Craftsman's Writs** stay out.
5. **Item-started quests:** add a zone-wide heads-up (sticky `#completewith` step with `.collect item,1,qid,1` and `.mob`), then an accept step (`.accept`, `.use item`, `.itemcount item,1`). Only for quests that pass `tools/item_starts.py`: at least 0.74× the median XP for their level, or the start of a chain, and not a drop under 5% with nothing following it. The scores are in `data/analysis/item_starts.md`.
6. **Gather quests** flagged in `data/review/gather_candidates.md` are left out only where `data/review/decisions.json` says "cut".
7. **Class quests are out for now** (user, 2026-10-25): any new quest with a class restriction (`reqclass`), except profession quests like Camping 101. Steps the original RestedXP guides already had for class quests stay. `propose_inserts.excluded()` enforces this, and `python tools/remove_inserts.py` strips any FQ-inserted steps that break the rule.
8. **No Azeroth Commerce Authority quests** (user, 2026-10-25): anything rewarding ACA reputation (factions 2586/2587), meaning A Sealed Crate, Shipping Label and the Craftsman's Writs. Same enforcement as rule 7.
9. **Desolace centaurs:** the Alliance route takes the Gelkis side (1382 Strange Alliance), so the new Gelkis quests (93034 Valley of Bones, 93035, 93037, 93041) go in. The Magram chain (anything in the 1385 Brutal Politics series, or needing Magram reputation) stays out. "Maintain your reputation with X" in a quest's text is a reputation requirement, not a repeatable turn-in.
10. **Reviewed by hand and skipped** (`SKIP` in `propose_inserts.py`): Legacy Rewards, the "An Unfortunate End" toy quests, Darkspear Islands battleground quests, and Chol'aruk the Ravener (a Ratchet elite cave off the Alliance route).

## Placement mechanics (`propose_inserts.py`)
- A quest goes into every branch of a route: Hunter and non-Hunter sections, and the normal and dungeon routes. The dungeon route counts steps it `#include`s from the normal route.
- Chain follow-ups are accepted right after the previous quest's turn-in, merged into that step when it's the same NPC.
- If the current guide never reaches the objective or turn-in zone, those steps go into the earliest later guide for the same players. A background objective then becomes `#sticky`, because labels don't resolve across guides.
- Quests the route only reaches once they're grey (Classic grey rule) are skipped and listed in NOTES.md.
- Steps marked `<< Horde` in shared guides (the Skyborne start) are never used as anchors.

## Hand-placed and pending (2026-10-27)
- Hand-placed: 92109/92110 (Moonbrook alchemy, gated `.skill alchemy,<1,1`), 86613 Excavation Tools (Loch Modan dig site), and the questing-route turn-in for 97926 Making Do.
- `SKIP` additions: 98287 (second copy of Camping 101: Engineering 1 with no giver), and 97253, 98155 and 98156, which are grey by the time the route reaches them.
- `DUNGEON_LEADIN`: 92432 An Alarming Request ends in Silverpine, which only the City of Dalaran route visits, so it goes in the dungeon route only.
- `PENDING`: quests Wowhead has no giver for yet (97420, 92872, 95786, 95787, 95788, 98471). `validate.py` lists them. Re-scrape their pages once Wowhead fills them in, then place them.
- Item starts that fail rule 5 (92910 Harvesting the Harvesters, 95534 Strahnbrad Mystery, both 0.1% drops) count as cut.

## Speed route (`tools/build_speed.py`)
- It starts from the completionist route. Original RestedXP steps are always kept, and FQ quests are kept or cut.
- A quest stays when its estimated XP per minute is at least 0.6× the route's typical rate. That's below 1× on purpose, because new content is preferred. A quest also stays when the chain it starts clears that bar.
- Always cut: profession quests (Camping 101, the Moonbrook alchemy quests) and item starts from drops under 15%.
- Always kept: FQ steps for a quest that an original RestedXP step already accepts.
- Cutting a quest also cuts later quests in its chain. The chain comes from the Wowhead series, or from an NPC match when the series is empty.
