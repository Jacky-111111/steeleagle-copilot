# Mission: survey a search area; if a person is seen or battery is low, return home.
Data:
    Waypoints search_area(alt = 20.0, area = SearchZone, algo = survey, spacing = 10.0, angle_degrees = 0.0, trigger_distance = 5.0)
    Detection person_target(class_name = person)
Actions:
    TakeOff take_off(take_off_altitude = 15.0)
    Patrol survey(waypoints = search_area)
    ReturnToHome return_to_home()
Events:
    DetectionFound person_seen(target = person_target)
    BatteryReached battery_low(threshold = 40)
Mission:
    Start take_off
    During take_off:
        done -> survey
    During survey:
        person_seen -> return_to_home
        battery_low -> return_to_home
