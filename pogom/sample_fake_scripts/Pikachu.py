#!/usr/bin/env python

# This script is an example for the 'fake-search-script' option
#
# Run this with
#     runserver.py -cf config/config.ini.example -k GMAPS_KEY -l
#         42.7,-84.5 -fss ./pogom/sample_fake_scripts/simpleDitto.py
#
# Create a new fake Ditto every 3 seconds, starting at the position
# specified in the command-line parameters, and slowly moving east.
#
# Each Ditto expires in 15 seconds

import time
from datetime import datetime, timedelta


def go(args):
    count = 0
    while True:
        time.sleep(20)
        fake_pokemon_objects = [{'pokemon_id': 25,  # pikachu
                                 'gender': 1,
                                 'disappear_time': (datetime.utcnow() +
                                                    timedelta(seconds=100)),
                                 'latitude': args.position[0],
                                 'longitude': args.position[1] + count*.0002,
                                 'weather_id': 1,
                                 'previous_id': None,
                                 'costume_id': 2,
                                 'time_id': 1}]
        count += 1
        args.add_pokemon(fake_pokemon_objects)
