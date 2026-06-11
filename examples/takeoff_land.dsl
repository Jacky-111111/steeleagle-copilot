# Minimal mission: take off to 10 m, then land.
# No Data or Events are needed, so those stanzas are omitted entirely
# (never write an empty `Data:` or `Events:` header).
Actions:
    TakeOff take_off(take_off_altitude = 10.0)
    Land land()
Mission:
    Start take_off
    During take_off:
        done -> land
