-- ForeverQuest shares RestedXP's Lua globals (RXP, RXPGuides, RXPData...),
-- so the two addons must never be loaded at the same time.
local IsAddOnLoaded = C_AddOns and C_AddOns.IsAddOnLoaded or _G.IsAddOnLoaded

local f = CreateFrame("Frame")
f:RegisterEvent("PLAYER_LOGIN")
f:SetScript("OnEvent", function(self)
    self:UnregisterAllEvents()
    if IsAddOnLoaded("RXPGuides") then
        print("|cffff4040ForeverQuest:|r RestedXP Guides is also enabled. " ..
                  "Disable one of them and /reload - they conflict.")
    end
end)
