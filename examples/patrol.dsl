# Mission: take off, patrol a polygon, track any person seen, return home if battery low.
Data:
    Waypoints patrol_path(alt = 15.0, area = Rectangle, algo = edge)
    Detection person_target(class_name = person)
Actions:
    TakeOff take_off(take_off_altitude = 10.0)
    Patrol patrol(waypoints = patrol_path)
    Track track(target = person_target)
    ReturnToHome return_to_home()
Events:
    DetectionFound person_seen(target = person_target)
    BatteryReached battery_low(threshold = 50)
Mission:
    Start take_off
    During take_off:
        done -> patrol
    During patrol:
        done -> patrol
        person_seen -> track
        battery_low -> return_to_home
    During track:
        done -> patrol
        battery_low -> return_to_home
