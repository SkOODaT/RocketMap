#!/usr/bin/python
# -*- coding: utf-8 -*-

import calendar
import logging
import os
import math

from flask import Flask, abort, jsonify, render_template, request,\
    make_response, send_from_directory, send_file
from flask.json import JSONEncoder
from flask_compress import Compress
from datetime import datetime
from s2sphere import LatLng

from pogom.dyn_img import get_gym_icon, get_pokemon_map_icon, get_pokemon_raw_icon
from pogom.pgscout import scout_error, pgscout_encounter, perform_lure
from pogom.utils import get_args, get_pokemon_name
from datetime import timedelta
from collections import OrderedDict
from bisect import bisect_left

from pogom.weather import get_weather_cells, get_s2_coverage, get_weather_alerts
from .models import (Geofence, Pokemon, LurePokemon, Gym, Pokestop, ScannedLocation,
                     MainWorker, WorkerStatus, Token, HashKeys,
                     SpawnPoint, Weather)
from .utils import now, dottedQuadToNum, degrees_to_cardinal
from .client_auth import (redirect_client_to_auth, valid_client_auth, valid_discord_guild,
                          redirect_to_discord_guild_invite, valid_discord_guild_role)
from .blacklist import fingerprints, get_ip_blacklist

from pgoapi.protos.pogoprotos.map.weather.gameplay_weather_pb2 import *
from pgoapi.protos.pogoprotos.map.weather.weather_alert_pb2 import *
from pgoapi.protos.pogoprotos.networking.responses.get_map_objects_response_pb2 import *

log = logging.getLogger(__name__)
compress = Compress()


class Pogom(Flask):

    def __init__(self, import_name, **kwargs):
        super(Pogom, self).__init__(import_name, **kwargs)
        compress.init_app(self)

        args = get_args()

        # Global blist
        if not args.disable_blacklist:
            log.info('Retrieving blacklist...')
            self.blacklist = get_ip_blacklist()
            # Sort & index for binary search
            self.blacklist.sort(key=lambda r: r[0])
            self.blacklist_keys = [
                dottedQuadToNum(r[0]) for r in self.blacklist
            ]
        else:
            log.info('Blacklist disabled for this session.')
            self.blacklist = []
            self.blacklist_keys = []

        self.user_auth_code_cache = {}

        # Routes
        self.json_encoder = CustomJSONEncoder
        self.route("/", methods=['GET'])(self.fullmap)
        self.route("/auth_callback", methods=['GET'])(self.auth_callback)
        self.route("/raw_data", methods=['GET'])(self.raw_data)
        self.route("/loc", methods=['GET'])(self.loc)
        self.route("/next_loc", methods=['POST'])(self.next_loc)
        self.route("/mobile", methods=['GET'])(self.list_pokemon)
        self.route("/search_control", methods=['GET'])(self.get_search_control)
        self.route("/search_control", methods=['POST'])(
            self.post_search_control)
        self.route("/stats", methods=['GET'])(self.get_stats)
        self.route("/status", methods=['GET'])(self.get_status)
        self.route("/status", methods=['POST'])(self.post_status)
        self.route("/gym_data", methods=['GET'])(self.get_gymdata)
        self.route("/bookmarklet", methods=['GET'])(self.get_bookmarklet)
        self.route("/inject.js", methods=['GET'])(self.render_inject_js)
        self.route("/submit_token", methods=['POST'])(self.submit_token)
        self.route("/get_stats", methods=['GET'])(self.get_account_stats)
        self.route("/robots.txt", methods=['GET'])(self.render_robots_txt)
        self.route("/serviceWorker.min.js", methods=['GET'])(
            self.render_service_worker_js)
        self.route("/gym_img", methods=['GET'])(self.gym_img)
        self.route("/pkm_img", methods=['GET'])(self.pokemon_img)
        self.route("/scout", methods=['GET'])(self.scout_pokemon)
        self.route("/lure", methods=['GET'])(self.scout_lure)
        self.route("/<statusname>", methods=['GET'])(self.fullmap)
        self.route("/weather", methods=['GET'])(self.get_weather)

    def get_weather(self, page=1):

        args = get_args()
        db_weathers = Weather.get_weathers()

        def prepare_cell(s):
            s['loc'] = "{:.6f}, {:.6f}".format(s['latitude'], s['longitude'])
            s['wind_direction'] = degrees_to_cardinal(s['wind_direction'])
            s['gameplay_weather'] = GameplayWeather\
                .WeatherCondition.Name(s['gameplay_weather'])
            s['severity'] = WeatherAlert.Severity.Name(s['severity'])
            s['world_time'] = GetMapObjectsResponse\
                .TimeOfDay.Name(s['world_time'])
            return s

        headers = [
            'S2CellLoc',
            'Gameplay Weather',
            'CloudLvl',
            'RainLvl',
            'WindLvl',
            'Wind Direction',
            'SnowLvl',
            'FogLvl',
            'Severity',
            'Warn',
            'LastUpdated',
            'Time'
        ]

        max_weather_per_page = 25
        max_page = int(math.ceil(len(db_weathers)/float(max_weather_per_page)))
        if page * max_weather_per_page > len(db_weathers):
            # Page number is too great, set to last page
            page = max_page
        if page < 1:
            page = 1

        weathers = map(
            prepare_cell,
            db_weathers[
                (page - 1) * max_weather_per_page:page * max_weather_per_page
            ]
        )

        return render_template(
            'weather.html',
            single_page=(not len(db_weathers) > max_weather_per_page),
            page=page,
            max_page=max_page,
            headers=headers,
            weathers=weathers,
            show={
                'custom_css': args.custom_css,
                'custom_js': args.custom_js
            }
        )

    def gym_img(self):
        team = request.args.get('team')
        level = request.args.get('level')
        raidlevel = request.args.get('raidlevel')
        pkm = request.args.get('pkm')
        is_in_battle = request.args.get('battle')
        time = int(request.args.get('time')) if 'time' in request.args else 0
        return send_file(get_gym_icon(team, level, raidlevel, pkm, time, is_in_battle), mimetype='image/png')

    def pokemon_img(self):
        raw = 'raw' in request.args
        pkm = int(request.args.get('pkm'))
        medal = request.args.get('medal') if 'medal' in request.args else None
        gender = int(request.args.get('gender')) if 'gender' in request.args else None
        form = int(request.args.get('form')) if 'form' in request.args else None
        costume = int(request.args.get('costume')) if 'costume' in request.args else None
        weather = int(request.args.get('weather')) if 'weather' in request.args else 0
        time = int(request.args.get('time')) if 'time' in request.args else 0
        shiny = 'shiny' in request.args
        previous_id = int(request.args.get('previous')) if 'previous' in request.args else None
        if raw:
            filename = get_pokemon_raw_icon(pkm, time, medal=medal, gender=gender, form=form, costume=costume, weather=weather,
                                            shiny=shiny, previous_id=previous_id)
        else:
            filename = get_pokemon_map_icon(pkm, time, medal=medal, gender=gender, form=form, costume=costume, weather=weather, previous_id=previous_id)
        return send_file(filename, mimetype='image/png')


    def scout_pokemon(self):
        args = get_args()
        if args.pgscout_url:
            encounterId = request.args.get('encounter_id')
            p = Pokemon.get(Pokemon.encounter_id == encounterId)
            pokemon_name = get_pokemon_name(p.pokemon_id)
            log.info(
                u"On demand PGScouting a {} at {}, {}.".format(pokemon_name,
                                                              p.latitude,
                                                              p.longitude))
            scout_result = pgscout_encounter(p, forced=1)
            if scout_result['success']:
                self.update_scouted_pokemon(p, scout_result)
                if scout_result['weather_id'] == None:
                    scout_result['weather_id'] = 0
                log.info(
                    u"Successfully PGScouted a {:.1f}% lvl {} {} with {} CP {} Bonus"
                    u" (scout level {}).".format(
                        scout_result['iv_percent'], scout_result['level'],
                        pokemon_name, scout_result['cp'],
                        GameplayWeather.WeatherCondition.Name(scout_result['weather_id']),
                        scout_result['scout_level']))
            else:
                log.warning(u"Failed PGScouting {}: {}".format(pokemon_name,
                                                               scout_result[
                                                                   'error']))
        else:
            scout_result = scout_error("PGScout URL not configured.")
        return jsonify(scout_result)

    def scout_lure(self):
        args = get_args()
        if args.lure_url:
            lat = request.args.get('latitude')
            lng = request.args.get('longitude')
            log.info(
            u"On demand luring a stop at lat = {}, long = {}.".format(lat,
                                              lng))
            stops = Pokestop.get_stop_by_cord(lat, lng)
            if len(stops) > 1:
                log.info("Error, more than one stop returned")
                return None
            else:
                p = stops[0]
            log.info(
                u"On demand luring a stop {} at {}, {}.".format(p["pokestop_id"],
                                                              p["latitude"],
                                                              p["longitude"]))
            scout_result = perform_lure(p)
            if scout_result['success']:
                log.info(
                    u"Successfully lured pokestop_id {} at {}, {}".format(
                        p["pokestop_id"], p["latitude"],
                        p["longitude"]))
            else:
                log.warning(u"Failed luring {} at {},{}".format(p["pokestop_id"], p["latitude"], p["longitude"]))
        else:
            scout_result = scout_error("URL not configured.")
        return jsonify(scout_result)

    def update_scouted_pokemon(self, p, response):
        # Update database
        update_data = {
            p.encounter_id: {
                'encounter_id': p.encounter_id,
                'spawnpoint_id': p.spawnpoint_id,
                'pokemon_id': p.pokemon_id,
                'latitude': p.latitude,
                'longitude': p.longitude,
                'disappear_time': p.disappear_time,
                'individual_attack': response['iv_attack'],
                'individual_defense': response['iv_defense'],
                'individual_stamina': response['iv_stamina'],
                'move_1': response['move_1'],
                'move_2': response['move_2'],
                'height': response['height'],
                'weight': response['weight'],
                'gender': response['gender'],
                'form': response.get('form', None),
                'cp': response['cp'],
                'cp_multiplier': response['cp_multiplier'],
                'catch_prob_1': response['catch_prob_1'],
                'catch_prob_2': response['catch_prob_2'],
                'catch_prob_3': response['catch_prob_3'],
                'rating_attack': response['rating_attack'],
                'rating_defense': response['rating_defense'],
                'weather_id': response.get('weather_id', None)
            }
        }
        self.db_updates_queue.put((Pokemon, update_data))

    def render_robots_txt(self):
        return render_template('robots.txt')

    def render_service_worker_js(self):
        return send_from_directory('static/dist/js', 'serviceWorker.min.js')

    def get_bookmarklet(self):
        args = get_args()
        return render_template('bookmarklet.html',
                               domain=args.manual_captcha_domain)

    def render_inject_js(self):
        args = get_args()
        src = render_template('inject.js',
                              domain=args.manual_captcha_domain,
                              timer=args.manual_captcha_refresh)

        response = make_response(src)
        response.headers['Content-Type'] = 'application/javascript'

        return response

    def submit_token(self):
        response = 'error'
        if request.form:
            token = request.form.get('token')
            query = Token.insert(token=token, last_updated=datetime.utcnow())
            query.execute()
            response = 'ok'
        r = make_response(response)
        r.headers.add('Access-Control-Allow-Origin', '*')
        return r

    def get_account_stats(self):
        stats = MainWorker.get_account_stats()
        r = make_response(jsonify(**stats))
        r.headers.add('Access-Control-Allow-Origin', '*')
        return r

    def validate_request(self):
        args = get_args()

        # Get real IP behind trusted reverse proxy.
        ip_addr = request.remote_addr
        if ip_addr in args.trusted_proxies:
            ip_addr = request.headers.get('X-Forwarded-For', ip_addr)

        # Make sure IP isn't blacklisted.
        if self._ip_is_blacklisted(ip_addr):
            log.debug('Denied access to %s: blacklisted IP.', ip_addr)
            abort(403)

    def _ip_is_blacklisted(self, ip):
        if not self.blacklist:
            return False

        # Get the nearest IP range
        pos = max(bisect_left(self.blacklist_keys, ip) - 1, 0)
        ip_range = self.blacklist[pos]

        start = dottedQuadToNum(ip_range[0])
        end = dottedQuadToNum(ip_range[1])

        return start <= dottedQuadToNum(ip) <= end

    def set_db_updates_queue(self, db_updates_queue):
        self.db_updates_queue = db_updates_queue

    def set_control_flags(self, control):
        self.control_flags = control

    def set_heartbeat_control(self, heartb):
        self.heartbeat = heartb

    def set_location_queue(self, queue):
        self.location_queue = queue

    def set_current_location(self, location):
        self.current_location = location

    def get_search_control(self):
        return jsonify({
            'status': not self.control_flags['search_control'].is_set()})

    def post_search_control(self):
        args = get_args()
        if not args.search_control or args.on_demand_timeout > 0:
            return 'Search control is disabled', 403
        action = request.args.get('action', 'none')
        if action == 'on':
            self.control_flags['search_control'].clear()
            log.info('Search thread resumed')
        elif action == 'off':
            self.control_flags['search_control'].set()
            log.info('Search thread paused')
        else:
            return jsonify({'message': 'invalid use of api'})
        return self.get_search_control()

    def auth_callback(self, statusname=None):
        return render_template('auth_callback.html')

    def fullmap(self, statusname=None):
        self.heartbeat[0] = now()
        args = get_args()
        if args.on_demand_timeout > 0:
            self.control_flags['on_demand'].clear()

        search_display = True if (args.search_control and
                                  args.on_demand_timeout <= 0) else False

        scan_display = False if (args.only_server or args.fixed_location or
                                 args.spawnpoint_scanning) else True

        visibility_flags = {
            'geofences': bool(args.geofence_file or
                              args.geofence_excluded_file),
            'gyms': not args.no_gyms,
            'pokemons': not args.no_pokemon,
            'pokestops': not args.no_pokestops,
            'raids': not args.no_raids,
            'gym_info': args.gym_info,
            'encounter': args.encounter,
            'scan_display': scan_display,
            'search_display': search_display,
            'fixed_display': not args.fixed_location,
            'custom_css': args.custom_css,
            'custom_js': args.custom_js
        }

        map_lat = False
        if statusname:
            coords = WorkerStatus.get_center_of_worker(statusname)
            if coords:
                map_lat = coords['lat']
                map_lng = coords['lng']

        if not map_lat:
            map_lat = self.current_location[0]
            map_lng = self.current_location[1]

        return render_template('map.html',
                               lat=map_lat,
                               lng=map_lng,
                               showAllZoomLevel=args.show_all_zoom_level,
                               generateImages=str(args.generate_images).lower(),
                               gmaps_key=args.gmaps_key,
                               lang=args.locale,
                               show=visibility_flags
                               )

    def raw_data(self):
        # Make sure fingerprint isn't blacklisted.
        fingerprint_blacklisted = any([
            fingerprints['no_referrer'](request),
            fingerprints['iPokeGo'](request)
        ])

        if fingerprint_blacklisted:
            log.debug('User denied access: blacklisted fingerprint.')
            abort(403)

        self.heartbeat[0] = now()
        args = get_args()
        if args.on_demand_timeout > 0:
            self.control_flags['on_demand'].clear()
        d = {}

        if args.user_auth_service == "Discord":
          if not valid_client_auth(request, self.user_auth_code_cache, args):
            return redirect_client_to_auth(request.url_root, args)
          if args.uas_discord_required_guild:
            if not valid_discord_guild(request, self.user_auth_code_cache, args):
              return redirect_to_discord_guild_invite(args)
            if args.uas_discord_required_roles and not valid_discord_guild_role(request, self.user_auth_code_cache, args):
              return redirect_to_discord_guild_invite(args)

        # Request time of this request.
        d['timestamp'] = datetime.utcnow()

        # Request time of previous request.
        if request.args.get('timestamp'):
            timestamp = int(request.args.get('timestamp'))
            timestamp -= 1000  # Overlap, for rounding errors.
        else:
            timestamp = 0

        swLat = request.args.get('swLat')
        swLng = request.args.get('swLng')
        neLat = request.args.get('neLat')
        neLng = request.args.get('neLng')

        oSwLat = request.args.get('oSwLat')
        oSwLng = request.args.get('oSwLng')
        oNeLat = request.args.get('oNeLat')
        oNeLng = request.args.get('oNeLng')

        # Previous switch settings.
        lastgyms = request.args.get('lastgyms')
        lastpokestops = request.args.get('lastpokestops')
        lastpokemon = request.args.get('lastpokemon')
        lastslocs = request.args.get('lastslocs')
        lastspawns = request.args.get('lastspawns')

        if request.args.get('luredonly', 'true') == 'true':
            luredonly = True
        else:
            luredonly = False

        # Current switch settings saved for next request.
        if request.args.get('gyms', 'true') == 'true':
            d['lastgyms'] = request.args.get('gyms', 'true')

        if request.args.get('pokestops', 'true') == 'true':
            d['lastpokestops'] = request.args.get('pokestops', 'true')

        if request.args.get('pokemon', 'true') == 'true':
            d['lastpokemon'] = request.args.get('pokemon', 'true')

        if request.args.get('scanned', 'true') == 'true':
            d['lastslocs'] = request.args.get('scanned', 'true')

        if request.args.get('spawnpoints', 'false') == 'true':
            d['lastspawns'] = request.args.get('spawnpoints', 'false')

        # If old coords are not equal to current coords we have moved/zoomed!
        if (oSwLng < swLng and oSwLat < swLat and
                oNeLat > neLat and oNeLng > neLng):
            newArea = False  # We zoomed in no new area uncovered.
        elif not (oSwLat == swLat and oSwLng == swLng and
                  oNeLat == neLat and oNeLng == neLng):
            newArea = True
        else:
            newArea = False

        # Pass current coords as old coords.
        d['oSwLat'] = swLat
        d['oSwLng'] = swLng
        d['oNeLat'] = neLat
        d['oNeLng'] = neLng

        if (request.args.get('pokemon', 'true') == 'true' and
                not args.no_pokemon):
            if request.args.get('ids'):
                ids = [int(x) for x in request.args.get('ids').split(',')]
                d['pokemons'] = Pokemon.get_active_by_id(ids, swLat, swLng,
                                                         neLat, neLng)
            elif lastpokemon != 'true':
                # If this is first request since switch on, load
                # all pokemon on screen.
                d['pokemons'] = Pokemon.get_active(swLat, swLng, neLat, neLng)
            else:
                # If map is already populated only request modified Pokemon
                # since last request time.
                d['pokemons'] = Pokemon.get_active(swLat, swLng, neLat, neLng,
                                                   timestamp=timestamp)
                if newArea:
                    # If screen is moved add newly uncovered Pokemon to the
                    # ones that were modified since last request time.
                    d['pokemons'] = d['pokemons'] + (
                        Pokemon.get_active(swLat, swLng, neLat, neLng,
                                           oSwLat=oSwLat, oSwLng=oSwLng,
                                           oNeLat=oNeLat, oNeLng=oNeLng))

            if request.args.get('eids'):
                # Exclude id's of pokemon that are hidden.
                eids = [int(x) for x in request.args.get('eids').split(',')]
                d['pokemons'] = [
                    x for x in d['pokemons'] if x['pokemon_id'] not in eids]

            if request.args.get('reids'):
                reids = [int(x) for x in request.args.get('reids').split(',')]
                d['pokemons'] = d['pokemons'] + (
                    Pokemon.get_active_by_id(reids, swLat, swLng,
                                             neLat, neLng))
                d['reids'] = reids

        if request.args.get('lurePokemon', 'true') == 'true':
            if request.args.get('ids'):
                ids = [int(x) for x in request.args.get('ids').split(',')]
                d['lurePokemons'] = LurePokemon.get_active_by_id(ids, swLat, swLng,
                                                                 neLat, neLng)
            else:
                d['lurePokemons'] = LurePokemon.get_active(swLat, swLng, neLat, neLng)

        if (request.args.get('pokestops', 'true') == 'true' and
                not args.no_pokestops):
            if lastpokestops != 'true':
                d['pokestops'] = Pokestop.get_stops(swLat, swLng, neLat, neLng,
                                                    lured=luredonly)
            else:
                d['pokestops'] = Pokestop.get_stops(swLat, swLng, neLat, neLng,
                                                    timestamp=timestamp)
                if newArea:
                    d['pokestops'] = d['pokestops'] + (
                        Pokestop.get_stops(swLat, swLng, neLat, neLng,
                                           oSwLat=oSwLat, oSwLng=oSwLng,
                                           oNeLat=oNeLat, oNeLng=oNeLng,
                                           lured=luredonly))

        if request.args.get('gyms', 'true') == 'true' and not args.no_gyms:
            if lastgyms != 'true':
                d['gyms'] = Gym.get_gyms(swLat, swLng, neLat, neLng)
            else:
                d['gyms'] = Gym.get_gyms(swLat, swLng, neLat, neLng,
                                         timestamp=timestamp)
                if newArea:
                    d['gyms'].update(
                        Gym.get_gyms(swLat, swLng, neLat, neLng,
                                     oSwLat=oSwLat, oSwLng=oSwLng,
                                     oNeLat=oNeLat, oNeLng=oNeLng))

        if request.args.get('scanned', 'true') == 'true':
            if lastslocs != 'true':
                d['scanned'] = ScannedLocation.get_recent(swLat, swLng,
                                                          neLat, neLng)
            else:
                d['scanned'] = ScannedLocation.get_recent(swLat, swLng,
                                                          neLat, neLng,
                                                          timestamp=timestamp)
                if newArea:
                    d['scanned'] = d['scanned'] + ScannedLocation.get_recent(
                        swLat, swLng, neLat, neLng, oSwLat=oSwLat,
                        oSwLng=oSwLng, oNeLat=oNeLat, oNeLng=oNeLng)

        if request.args.get('seen', 'false') == 'true':
            d['seen'] = Pokemon.get_seen(int(request.args.get('duration')))

        if request.args.get('appearances', 'false') == 'true':
            d['appearances'] = Pokemon.get_appearances(
                request.args.get('pokemonid'),
                int(request.args.get('duration')))

        if request.args.get('appearancesDetails', 'false') == 'true':
            d['appearancesTimes'] = (
                Pokemon.get_appearances_times_by_spawnpoint(
                    request.args.get('pokemonid'),
                    request.args.get('spawnpoint_id'),
                    int(request.args.get('duration'))))

        if request.args.get('spawnpoints', 'false') == 'true':
            if lastspawns != 'true':
                d['spawnpoints'] = SpawnPoint.get_spawnpoints(
                    swLat=swLat, swLng=swLng, neLat=neLat, neLng=neLng)
            else:
                d['spawnpoints'] = SpawnPoint.get_spawnpoints(
                    swLat=swLat, swLng=swLng, neLat=neLat, neLng=neLng,
                    timestamp=timestamp)
                if newArea:
                    d['spawnpoints'] = d['spawnpoints'] + (
                        SpawnPoint.get_spawnpoints(
                            swLat, swLng, neLat, neLng,
                            oSwLat=oSwLat, oSwLng=oSwLng,
                            oNeLat=oNeLat, oNeLng=oNeLng))

        if request.args.get('geofences', 'true') == 'true':
            db_geofences = Geofence.get_geofences()

            geofences = {}
            for g in db_geofences:
                # Check if already there
                geofence = geofences.get(g['name'], None)
                if not geofence:  # Create a new sub-dict if new
                    geofences[g['name']] = {
                        'excluded': g['excluded'],
                        'name': g['name'],
                        'coordinates': []
                    }
                coordinate = {
                    'lat': g['latitude'],
                    'lng': g['longitude']
                }
                geofences[g['name']]['coordinates'].append(coordinate)

            d['geofences'] = geofences

        if request.args.get('status', 'false') == 'true':
            args = get_args()
            d = {}
            if args.status_page_password is None:
                d['error'] = 'Access denied'
            elif (request.args.get('password', None) ==
                  args.status_page_password):
                d['main_workers'] = MainWorker.get_all()
                d['workers'] = WorkerStatus.get_all()

        if request.args.get('weather', 'false') == 'true':
            d['weather'] = get_weather_cells(swLat, swLng, neLat, neLng)

        if request.args.get('s2cells', 'false') == 'true':
            d['s2cells'] = get_s2_coverage(swLat, swLng, neLat, neLng)

        if request.args.get('weatherAlerts', 'false') == 'true':
            d['weatherAlerts'] = get_weather_alerts(swLat, swLng, neLat, neLng)

        if request.args.get('time', 'false') == 'true':
            d['time'] = get_time(swLat, swLng, neLat, neLng)

        return jsonify(d)

    def loc(self):
        d = {}
        d['lat'] = self.current_location[0]
        d['lng'] = self.current_location[1]

        return jsonify(d)

    def next_loc(self):
        args = get_args()
        if args.fixed_location:
            return 'Location changes are turned off', 403
        lat = None
        lon = None
        # Part of query string.
        if request.args:
            lat = request.args.get('lat', type=float)
            lon = request.args.get('lon', type=float)
        # From post requests.
        if request.form:
            lat = request.form.get('lat', type=float)
            lon = request.form.get('lon', type=float)

        if not (lat and lon):
            log.warning('Invalid next location: %s,%s', lat, lon)
            return 'bad parameters', 400
        else:
            self.location_queue.put((lat, lon, 0))
            self.set_current_location((lat, lon, 0))
            log.info('Changing next location: %s,%s', lat, lon)
            return self.loc()

    def list_pokemon(self):
        # todo: Check if client is Android/iOS/Desktop for geolink, currently
        # only supports Android.
        pokemon_list = []

        # Allow client to specify location.
        lat = request.args.get('lat', self.current_location[0], type=float)
        lon = request.args.get('lon', self.current_location[1], type=float)
        origin_point = LatLng.from_degrees(lat, lon)

        for pokemon in Pokemon.get_active(None, None, None, None):
            pokemon_point = LatLng.from_degrees(pokemon['latitude'],
                                                pokemon['longitude'])
            diff = pokemon_point - origin_point
            diff_lat = diff.lat().degrees
            diff_lng = diff.lng().degrees
            direction = (('N' if diff_lat >= 0 else 'S')
                         if abs(diff_lat) > 1e-4 else '') +\
                        (('E' if diff_lng >= 0 else 'W')
                         if abs(diff_lng) > 1e-4 else '')
            entry = {
                'id': pokemon['pokemon_id'],
                'name': pokemon['pokemon_name'],
                'card_dir': direction,
                'distance': int(origin_point.get_distance(
                    pokemon_point).radians * 6366468.241830914),
                'time_to_disappear': '%d min %d sec' % (divmod(
                    (pokemon['disappear_time'] - datetime.utcnow()).seconds,
                    60)),
                'disappear_time': pokemon['disappear_time'],
                'disappear_sec': (
                    pokemon['disappear_time'] - datetime.utcnow()).seconds,
                'latitude': pokemon['latitude'],
                'longitude': pokemon['longitude']
            }
            pokemon_list.append((entry, entry['distance']))
        pokemon_list = [y[0] for y in sorted(pokemon_list, key=lambda x: x[1])]
        args = get_args()
        visibility_flags = {
            'custom_css': args.custom_css,
            'custom_js': args.custom_js
        }

        return render_template('mobile_list.html',
                               pokemon_list=pokemon_list,
                               origin_lat=lat,
                               origin_lng=lon,
                               show=visibility_flags
                               )

    def get_stats(self):
        args = get_args()
        visibility_flags = {
            'custom_css': args.custom_css,
            'custom_js': args.custom_js
        }

        return render_template('statistics.html',
                               lat=self.current_location[0],
                               lng=self.current_location[1],
                               generateImages=str(args.generate_images).lower(),
                               gmaps_key=args.gmaps_key,
                               show=visibility_flags
                               )

    def get_gymdata(self):
        gym_id = request.args.get('id')
        gym = Gym.get_gym(gym_id)

        return jsonify(gym)

    def get_status(self):
        args = get_args()
        visibility_flags = {
            'custom_css': args.custom_css,
            'custom_js': args.custom_js
        }
        if args.status_page_password is None:
            abort(404)

        return render_template('status.html',
                               show=visibility_flags)

    def post_status(self):
        args = get_args()
        d = {}
        if args.status_page_password is None:
            abort(404)

        if request.form.get('password', None) == args.status_page_password:
            d['login'] = 'ok'
            d['main_workers'] = MainWorker.get_all()
            d['workers'] = WorkerStatus.get_all()
            d['hashkeys'] = HashKeys.get_obfuscated_keys()
        else:
            d['login'] = 'failed'
        return jsonify(d)


class CustomJSONEncoder(JSONEncoder):

    def default(self, obj):
        try:
            if isinstance(obj, datetime):
                if obj.utcoffset() is not None:
                    obj = obj - obj.utcoffset()
                millis = int(
                    calendar.timegm(obj.timetuple()) * 1000 +
                    obj.microsecond / 1000
                )
                return millis
            iterable = iter(obj)
        except TypeError:
            pass
        else:
            return list(iterable)
        return JSONEncoder.default(self, obj)
