local faction = UnitFactionGroup("player")
if faction == "Horde" then return end
local L = GetLocale() if L and RXP.enabledLocale[L] then return end
RXPGuides.RegisterGuide([[
#forever
#version 1
<< Alliance
#group ForeverQuest Speed Dungeon (A)
#subgroup Dungeon Guide 1-20
--#groupid RXP-SRGCE-A1
#name 1-5 Coldridge Valley
#next 5-11 Dun Morogh
step
#include ForeverQuest Speed (A)\1-5 Coldridge Valley
]])

RXPGuides.RegisterGuide([[
#forever
#version 1
<< Alliance
#group ForeverQuest Speed Dungeon (A)
#subgroup Dungeon Guide 1-20
--#groupid RXP-SRGCE-A1
#name 5-11 Dun Morogh
#next 11-12 Elwynn (Dwarf/Gnome);12-14 Loch Modan (Dwarf/Gnome);11-13 Loch Modan (Hunter)
step
#include ForeverQuest Speed (A)\5-11 Dun Morogh
]])

RXPGuides.RegisterGuide([[
#forever
<< Alliance !Hunter
#group ForeverQuest Speed Dungeon (A)
#subgroup Dungeon Guide 1-20
--#groupid RXP-SRGCE-A1
#name 11-12 Elwynn (Dwarf/Gnome)
#version 1
#next 12-14 Loch Modan (Dwarf/Gnome)
step
#include ForeverQuest Speed (A)\11-12 Elwynn (Dwarf/Gnome)
]])

RXPGuides.RegisterGuide([[
#forever
#version 1
<< Alliance !Hunter
#group ForeverQuest Speed Dungeon (A)
#subgroup Dungeon Guide 1-20
--#groupid RXP-SRGCE-A1
#name 12-14 Loch Modan (Dwarf/Gnome)
#next 13-15 Westfall
step
#include ForeverQuest Speed (A)\12-14 Loch Modan (Dwarf/Gnome)
]])

RXPGuides.RegisterGuide([[
#forever
#version 1
<< Alliance Hunter
#group ForeverQuest Speed Dungeon (A)
#subgroup Dungeon Guide 1-20
--#groupid RXP-SRGCE-A1
#name 11-13 Loch Modan (Hunter)
#next 13-15 Westfall
step
#include ForeverQuest Speed (A)\11-13 Loch Modan (Hunter)@NormalRouteStart-NormalRouteEnd
]])
