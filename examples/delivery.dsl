# Mission: take off, fly to a delivery point, wait 30 seconds, then return home.
Data:
    Location drop_point(latitude = 40.4433, longitude = -79.9436, altitude = 8.0)
Actions:
    TakeOff take_off(take_off_altitude = 10.0)
    SetGlobalPosition go_to_drop(location = drop_point)
    Wait wait_at_drop(duration = 30.0)
    ReturnToHome return_to_home()
Events:
    BatteryReached battery_low(threshold = 30)
Mission:
    Start take_off
    During take_off:
        done -> go_to_drop
    During go_to_drop:
        done -> wait_at_drop
        battery_low -> return_to_home
    During wait_at_drop:
        done -> return_to_home
        battery_low -> return_to_home
