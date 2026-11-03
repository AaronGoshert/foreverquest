local faction = UnitFactionGroup("player")
if faction == "Horde" then return end
local L = GetLocale() if L and RXP.enabledLocale[L] then return end
RXPGuides.RegisterGuide([[
#forever
#season 0,1
<< Alliance
#name 1-6 Shadowglen
#version 1
#group ForeverQuest Speed Dungeon (A)
#subgroup Dungeon Guide 1-20
--#groupid RXP-SRGCE-A1
#next 6-11 Teldrassil
step
#include ForeverQuest Speed (A)\1-6 Shadowglen
]])

RXPGuides.RegisterGuide([[
#forever
#season 0,1
<< Alliance
#name 6-11 Teldrassil
#version 1
#group ForeverQuest Speed Dungeon (A)
#subgroup Dungeon Guide 1-20
--#groupid RXP-SRGCE-A1
#next 11-16 Darkshore/Loch Modan
step
#include ForeverQuest Speed (A)\6-11 Teldrassil
]])

