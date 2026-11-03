local faction = UnitFactionGroup("player")
if faction == "Horde" then return end
local L = GetLocale() if L and RXP.enabledLocale[L] then return end
RXPGuides.RegisterGuide([[
#forever
<< Alliance
#name 1-6 Northshire
#version 1
#group ForeverQuest Speed Dungeon (A)
#subgroup Dungeon Guide 1-20
--#groupid RXP-SRGCE-A1
#next 6-11 Elwynn Forest
step
#include ForeverQuest Speed (A)\1-6 Northshire
]])

RXPGuides.RegisterGuide([[
#forever
#version 1
<< Alliance
#group ForeverQuest Speed Dungeon (A)
#subgroup Dungeon Guide 1-20
--#groupid RXP-SRGCE-A1
#name 6-11 Elwynn Forest
#next 11-13 Loch Modan
step
#include ForeverQuest Speed (A)\6-11 Elwynn Forest
]])

RXPGuides.RegisterGuide([[
#forever
#version 1
<< Alliance
#group ForeverQuest Speed Dungeon (A)
#subgroup Dungeon Guide 1-20
--#groupid RXP-SRGCE-A1
#name 11-13 Loch Modan
#next 13-15 Westfall
step
    #include ForeverQuest Speed (A)\11-13 Loch Modan@NormalRouteStart-NormalRouteEnd
]])
