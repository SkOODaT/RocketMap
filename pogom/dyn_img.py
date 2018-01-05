import logging
import os
import subprocess
from string import join

from pgoapi.protos.pogoprotos.enums.costume_pb2 import Costume
from pgoapi.protos.pogoprotos.enums.form_pb2 import Form
from pgoapi.protos.pogoprotos.enums.gender_pb2 import MALE, FEMALE, Gender, GENDERLESS, GENDER_UNSET
from pgoapi.protos.pogoprotos.enums.weather_condition_pb2 import *

log = logging.getLogger(__name__)

# Will be set during config parsing
generate_images = False
imagemagick_executable = None
pogo_assets = None

path_static = os.path.join(os.path.dirname(__file__), '..', 'static')
path_icons = os.path.join(path_static, 'sprites')
path_images = os.path.join(path_static, 'images')
path_gym = os.path.join(path_images, 'gym')
path_raid = os.path.join(path_images, 'raid')
path_weather = os.path.join(path_images, 'weather')
path_generated = os.path.join(path_images, 'generated')
path_generated_gym = os.path.join(path_generated, 'gym')
path_generated_pokemon = os.path.join(path_generated, 'pokemon')

egg_images = {
    1:              os.path.join(path_raid, 'egg_normal.png'),
    2:              os.path.join(path_raid, 'egg_normal.png'),
    3:              os.path.join(path_raid, 'egg_rare.png'),
    4:              os.path.join(path_raid, 'egg_rare.png'),
    5:              os.path.join(path_raid, 'egg_legendary.png')
}

egg_images_assets = {
    1:              os.path.join('sprites', 'egg_normal.png'),
    2:              os.path.join('sprites', 'egg_normal.png'),
    3:              os.path.join('sprites', 'egg_rare.png'),
    4:              os.path.join('sprites', 'egg_rare.png'),
    5:              os.path.join('sprites', 'egg_legendary.png'),
}

weather_images = {
    CLEAR:          os.path.join(path_weather, 'weather_sunny.png'),
    RAINY:          os.path.join(path_weather, 'weather_rain.png'),
    PARTLY_CLOUDY:  os.path.join(path_weather, 'weather_partlycloudy_day.png'),
    OVERCAST:       os.path.join(path_weather, 'weather_cloudy.png'),
    WINDY:          os.path.join(path_weather, 'weather_windy.png'),
    SNOW:           os.path.join(path_weather, 'weather_snow.png'),
    FOG:            os.path.join(path_weather, 'weather_fog.png'),
    11:             os.path.join(path_weather, 'weather_clear_night.png'),
    13:             os.path.join(path_weather, 'weather_partlycloudy_night.png')
}

pkm_sizes = {
    1: '50',
    2: '50',
    3: '60',
    4: '60',
    5: '80'
}

egg_sizes = {
    1: '50',
    2: '50',
    3: '55',
    4: '55',
    5: '65'
}

# Info about Pokemon spritesheet
path_pokemon_spritesheet = os.path.join(path_static, 'icons-shuffle-sprite128x.png')
pkm_sprites_size = 128
pkm_sprites_cols = 16

# Gym icons
gym_icon_size = 96
gym_badge_radius = 15
gym_badge_padding = 1

badge_upper_left = (gym_badge_padding + gym_badge_radius, gym_badge_padding + gym_badge_radius)
badge_upper_right = (gym_icon_size - (gym_badge_padding + gym_badge_radius), gym_badge_padding + gym_badge_radius)
badge_lower_left = (gym_badge_padding + gym_badge_radius, gym_icon_size - (gym_badge_padding + gym_badge_radius))
badge_lower_right = (gym_icon_size - (gym_badge_padding + gym_badge_radius), gym_icon_size - (gym_badge_padding + gym_badge_radius))

font = os.path.join(path_static, 'SF Intellivised.ttf')
font_pointsize = 25


def draw_raid_pokemon(pkm, raidlevel):
    raidlevel = int(raidlevel)
    if pogo_assets:
        pkm_path, dummy = pokemon_asset_path_shuffle(int(pkm))
        trim = True
    else:
        pkm_path = os.path.join(path_icons, '{}.png'.format(pkm))
        trim = False
    return draw_gym_subject(pkm_path, pkm_sizes[raidlevel], trim=trim)

def draw_raid_egg(raidlevel):
    if pogo_assets:
        egg_path = os.path.join(pogo_assets, egg_images_assets[raidlevel])
    else:
        egg_path = egg_images[raidlevel]
    #raidlevel = int(raidlevel)
    return draw_gym_subject(egg_path, egg_sizes[raidlevel], 'center')


def draw_gym_level(level):
    return draw_badge(badge_lower_right, "black", "white", level)


def draw_raid_level(raidlevel):
    return draw_badge(badge_upper_right, "white", "black", raidlevel)


def draw_battle_indicator():
    return battle_indicator()

def battle_indicator():
    # battle icon
    return ['-gravity center ( "{}" -resize 90x90 ( +clone -background black -shadow 80x3+5+5 ) +swap -background none -layers merge +repage ) -geometry +0+0 -composite'.format(
        os.path.join(path_gym, 'battle.png'))]


def battle_indicator_boom():
    # BOOM! Sticker
    return ['-gravity center ( "{}" -resize 84x84 ) -geometry +0+0 -composite'.format(
        os.path.join(path_gym, 'boom.png'))]


def battle_indicator_fist():
    # Fist Badge
    x = gym_icon_size - (gym_badge_padding + gym_badge_radius)
    y = gym_icon_size / 2
    return [
        '-fill white -stroke black -draw "circle {},{} {},{}"'.format(x, y, x - gym_badge_radius, y),
        '-gravity east ( "{}" -resize 24x24 ) -geometry +4+0 -composite'.format(os.path.join(path_gym, 'fist.png'))
    ]


def battle_indicator_flame():
    # Flame Badge
    return [
        '-gravity east ( "{}" -resize 32x32 ) -geometry +0+0 -composite'.format(os.path.join(path_gym, 'flame.png'))
    ]


def battle_indicator_swords():
    # Swords Badge
    x = gym_icon_size - (gym_badge_padding + gym_badge_radius)
    y = gym_icon_size / 2
    return [
        '-fill white -stroke black -draw "circle {},{} {},{}"'.format(x, y, x - gym_badge_radius, y),
        '-gravity east ( "{}" -resize 24x24 ) -geometry +4+0 -composite'.format(os.path.join(path_gym, 'swords.png'))
    ]


def get_gym_icon(team, level, raidlevel, pkm, is_in_battle):
    init_image_dir(path_generated_gym)
    level = int(level)

    if not generate_images:
        return default_gym_image(team, level, raidlevel, pkm)

    im_lines = ['-font "{}" -pointsize {}'.format(font, font_pointsize)]
    if pkm and pkm != 'null':
        # Gym with ongoing raid
        out_filename = os.path.join(path_generated_gym, "{}_L{}_R{}_P{}.png".format(team, level, raidlevel, pkm))
        im_lines.extend(draw_raid_pokemon(pkm, raidlevel))
        im_lines.extend(draw_raid_level(raidlevel))
        if level > 0:
            im_lines.extend(draw_gym_level(level))
    elif raidlevel:
        # Gym with upcoming raid (egg)
        raidlevel = int(raidlevel)
        out_filename = os.path.join(path_generated_gym, "{}_L{}_R{}.png".format(team, level, raidlevel))
        im_lines.extend(draw_raid_egg(raidlevel))
        im_lines.extend(draw_raid_level(raidlevel))
        if level > 0:
            im_lines.extend(draw_gym_level(level))
    elif level > 0:
        # Occupied gym
        out_filename = os.path.join(path_generated_gym, '{}_L{}.png'.format(team, level))
        im_lines.extend(draw_gym_level(level))
    else:
        # Neutral gym
        return os.path.join(path_gym, '{}.png'.format(team))

    # Battle Indicator
    if is_in_battle:
        out_filename = out_filename.replace('.png', '_B.png')
        im_lines.extend(draw_battle_indicator())

    gym_image = os.path.join(path_gym, '{}.png'.format(team))
    return run_imagemagick(gym_image, im_lines, out_filename)


def get_pokemon_icon(pkm, gender=None, form=None, costume=None,  weather=None,  time=None):
    init_image_dir(path_generated_pokemon)

    im_lines = []

    # Add Pokemon icon
    if pogo_assets:
        source, target = pokemon_asset_path_shuffle(pkm, gender, form, costume, weather)
        target_size = 96
        im_lines.append(
            #' -fuzz 0.5% -trim +repage'
            #' -scale "133x133>" -unsharp 0x1'
            #' -background none -gravity center -extent 139x139'
            #' -background black -alpha background -channel A -blur 0x1 -level 0,10%'
            #' -adaptive-resize {size}x{size}'
            #' -modulate 100,110'.format(size=target_size)

            ' -bordercolor none -border 2'
            ' -background black -alpha background -channel A -blur 0x1 -level 0,10%'
            ' -adaptive-resize 96x96'
            ' -modulate 100,110'
        )
    else:
        # Extract pokemon icon from spritesheet
        source = path_pokemon_spritesheet
        weather_suffix = '_{}'.format(WeatherCondition.Name(weather)) if weather else ''
        target = os.path.join(path_generated_pokemon, 'pokemon_{}{}.png'.format(pkm, weather_suffix))

        target_size = pkm_sprites_size
        pkm_idx = pkm - 1
        x = (pkm_idx % pkm_sprites_cols) * pkm_sprites_size
        y = (pkm_idx / pkm_sprites_cols) * pkm_sprites_size
        im_lines.append(
            #' -bordercolor none -border 2'
            #' -background black -alpha background -channel A -blur 0x1 -level 0,10%'
            ' -crop {size}x{size}+{x}+{y} +repage'.format(size=target_size, x=x, y=y)
        )

    if weather:
        radius = 20
        x = target_size - radius - 2
        y = radius + 1
        y2 = 1
        if time == 2:
            if not weather == 1 and not weather == 3:
                im_lines.append(
                    '-gravity northeast'
                    ' -fill "#FFFD" -stroke black -draw "circle {x},{y} {x},{y2}"'
                    ' -draw "image over 1,1 42,42 \'{weather_img}\'"'.format(x=x, y=y, y2=y2, weather_img=weather_images[weather])
                )
            else:
                im_lines.append(
                    '-gravity northeast'
                    ' -fill "#FFFD" -stroke black -draw "circle {x},{y} {x},{y2}"'
                    ' -draw "image over 1,1 42,42 \'{weather_img}\'"'.format(x=x, y=y, y2=y2, weather_img=weather_images[weather + 10])
                )
        else:
            im_lines.append(
                '-gravity northeast'
                ' -fill "#FFFD" -stroke black -draw "circle {x},{y} {x},{y2}"'
                ' -draw "image over 1,1 42,42 \'{weather_img}\'"'.format(x=x, y=y, y2=y2, weather_img=weather_images[weather])
            )

    return run_imagemagick(source, im_lines, target)


def pokemon_asset_path(pkm, gender=GENDER_UNSET, form=None, costume=None, weather=None):
    gender_suffix = gender_assets_suffix = ''
    form_suffix = form_assets_suffix  = ''
    costume_suffix = costume_assets_suffix = ''
    weather_suffix = '_{}'.format(WeatherCondition.Name(weather)) if weather else ''

    if gender in (MALE, FEMALE):
        gender_assets_suffix = '_{:02d}'.format(gender - 1)
        gender_suffix = '_{}'.format(Gender.Name(gender))
    elif gender in (GENDER_UNSET, GENDERLESS):
        gender_assets_suffix = '_00'

    if form:
        # Form = no gender
        gender_suffix = gender_assets_suffix = ''
        form_assets_suffix = '_{:02d}'.format(form + 10)
        form_suffix = '_{}'.format(Form.Name(form))

    if costume:
        costume_assets_suffix = '_{:02d}'.format(costume)
        costume_suffix = '_{}'.format(Costume.Name(costume))

    if not gender_assets_suffix and not form_assets_suffix and not costume_assets_suffix:
        gender_assets_suffix = '_16' if pkm == 201 else '_00'

    assets_basedir = os.path.join(pogo_assets, 'decrypted_assets')
    assets_fullname = os.path.join(assets_basedir,
                                   'pokemon_icon_{:03d}{}{}{}.png'.format(pkm, gender_assets_suffix, form_assets_suffix,
                                                                    costume_assets_suffix))
    target_name = os.path.join(path_generated_pokemon,
                               "pkm_{}{}{}{}{}.png".format(pkm, gender_suffix, form_suffix, costume_suffix,
                                                               weather_suffix))
    if os.path.isfile(assets_fullname):
        return assets_fullname, target_name
    else:
        if gender == MALE:
            raise Exception("Cannot find PogoAssets file {}".format(assets_fullname))
        return pokemon_asset_path(pkm, MALE, form, costume, weather)


def pokemon_asset_path_shuffle(pkm, gender=GENDER_UNSET, form=None, costume=None, weather=None):
    gender_suffix = gender_assets_suffix = ''
    form_suffix = form_assets_suffix  = ''
    costume_suffix = costume_assets_suffix = ''
    weather_suffix = '_{}'.format(WeatherCondition.Name(weather)) if weather else ''

    if gender in (MALE, FEMALE):
        gender_assets_suffix = ''.format(gender - 1)
        gender_suffix = '_{}'.format(Gender.Name(gender))
    elif gender in (GENDER_UNSET, GENDERLESS):
        gender_assets_suffix = '_'

    if form:
        # Form = no gender
        gender_suffix = gender_assets_suffix = ''
        form_assets_suffix = '_{:02d}'.format(form + 10)
        form_suffix = '_{}'.format(Form.Name(form))

    if costume:
        costume_assets_suffix = '_{:02d}'.format(costume)
        costume_suffix = '_{}'.format(Costume.Name(costume))

    if not gender_assets_suffix and not form_assets_suffix and not costume_assets_suffix:
        gender_assets_suffix = '_16' if pkm == 201 else ''

    assets_basedir = os.path.join(pogo_assets, 'sprites')
    assets_fullname = os.path.join(assets_basedir,
                                   '{}{}{}{}.png'.format(pkm, gender_assets_suffix, form_assets_suffix,
                                                                    costume_assets_suffix))
    target_name = os.path.join(path_generated_pokemon,
                               "pkm_{}{}{}{}{}.png".format(pkm, gender_suffix, form_suffix, costume_suffix,
                                                               weather_suffix))
    if os.path.isfile(assets_fullname):
        return assets_fullname, target_name
    else:
        if gender == MALE:
            raise Exception("Cannot find PogoAssets file {}".format(assets_fullname))
        return pokemon_asset_path_shuffle(pkm, MALE, form, costume, weather)


def draw_gym_subject(image, size, gravity='north', trim=False):
    trim_cmd = ' -fuzz 0.5% -trim +repage' if trim else ''
    lines = [
        '-gravity {} ( "{}"{} -scale {}x{} -unsharp 0x1 ( +clone -background black -shadow 80x3+5+5 ) +swap -background none -layers merge +repage ) -geometry +0+0 -composite'.format(
            gravity, image, trim_cmd, size, size)
    ]
    return lines


def draw_badge(pos, fill_col, text_col, text):
    (x, y) = pos
    lines = [
        '-fill {} -stroke black -draw "circle {},{} {},{}"'.format(fill_col, x, y, x + gym_badge_radius, y),
        '-gravity center -fill {} -stroke none -draw "text {},{} \'{}\'"'.format(text_col, x - 47, y - 44, text)
    ]
    return lines


def init_image_dir(path):
    if not os.path.isdir(path):
        try:
            os.makedirs(path)
        except OSError:
            if not os.path.isdir(path):
                raise


def default_gym_image(team, level, raidlevel, pkm):
    path = path_gym
    if pkm and pkm != 'null':
        icon = "{}_{}.png".format(team, pkm)
        path = path_raid
    elif raidlevel:
        icon = "{}_{}_{}.png".format(team, level, raidlevel)
    elif level:
        icon = "{}_{}.png".format(team, level)
    else:
        icon = "{}.png".format(team)

    return os.path.join(path, icon)


def run_imagemagick(source, im_lines, out_filename):
    if not os.path.isfile(out_filename):
        cmd = '{} "{}" {} "{}"'.format(imagemagick_executable, source, join(im_lines), out_filename)
        if os.name != 'nt':
            cmd = cmd.replace(" ( ", " \( ").replace(" ) ", " \) ")
        log.info("Generating icon '{}'".format(out_filename))
        subprocess.call(cmd, shell=True)
    return out_filename
