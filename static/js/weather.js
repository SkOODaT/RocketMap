/**
 * Parses info about weather cell and draws icon
 * @param i index from $.each()
 * @param item weather cell data
 * @returns {boolean}
 */
function processWeather(i, item) {
    if (!Store.get('showWeatherCells') || item.gameplay_weather == null) {
        return false
    }

    var s2CellId = item.s2_cell_id
    var itemOld = mapData.weather[s2CellId]

    if (itemOld == null) { // add new marker to map and item to dict
        safeDelMarker(item)
        item.marker = setupWeatherMarker(item)
        mapData.weather[s2CellId] = item
    } else if (itemOld.gameplay_weather !== item.gameplay_weather) { // if weather changed
        itemOld.marker.setMap(null)
        item.marker = setupWeatherMarker(item)
        mapData.weather[s2CellId] = item
    }
}


/**
 * Parses info about s2cell and draws polygon
 * @param i i index from $.each()
 * @param item s2cell data
 * @returns {boolean}
 */
function processS2Cell(i, item) {
    if (!Store.get('showS2Cells')) {
        return false
    }

    var s2CellId = item.s2_cell_id
    if (!(s2CellId in mapData.s2cells)) {
        safeDelMarker(item)
        item.marker = setupS2CellPolygon(item)
        mapData.s2cells[s2CellId] = item
    }
}


/**
 * Do main work with array of weather alerts
 * @param weatherAlerts
 */
function processWeatherAlerts(weatherAlerts) {
    deleteObsoleteWeatherAlerts(weatherAlerts)
    $.each(weatherAlerts, processWeatherAlert)
}


/**
 * Draws colored polygon for weather severity condition
 * @param i
 * @param item s2cell data
 * @returns {boolean}
 */
function processWeatherAlert(i, item) {
    if (!Store.get('showWeatherAlerts') || item.severity == null) {
        return false
    }

    var s2CellId = item.s2_cell_id
    var itemOld = mapData.weatherAlerts[s2CellId]
    if (itemOld == null) {
        safeDelMarker(item)
        item.marker = createCellAlert(item)
        mapData.weatherAlerts[s2CellId] = item
    } else if (itemOld.severity !== item.severity) {
        itemOld.marker.setMap(null)
        item.marker = createCellAlert(item)
        mapData.weatherAlerts[s2CellId] = item
    }
}


/**
 * If drawn cell not exist in new alert array, it should be removed
 * @param newAlerts
 */
function deleteObsoleteWeatherAlerts(newAlerts) {
    var toRemove = []
    $.each(mapData.weatherAlerts, function (i, item) {
        if (!(item['s2_cell_id'] in newAlerts)) {
            safeDelMarker(item)
            toRemove.push(i)
        }
    })
    $.each(toRemove, function (i, id) {
        delete mapData.weatherAlerts[id]
    })
}


/**
 * safe setMap(null)
 * @param item
 */
function safeDelMarker(item) {
    if (item.marker) {
        item.marker.setMap(null)
    }
}


/**
 * Creates path for weather icon based on gameplay_weather and world_time
 * @param item
 * @param dark dark or light version of image, default is dark
 * @returns {*}
 */
function getWeatherImageUrl(item, dark = true) {
    var imageUrl
    if (item.severity === 1) {
      imageUrl = '/static/images/weather/' + weatherImages[15]
    } else if (item.severity === 2) {
        imageUrl = '/static/images/weather/' + weatherImages[16]
    } else if (item.world_time === 2) { // night
        if (![1, 3].includes(item.gameplay_weather)) { // common icons for day and night
            imageUrl = '/static/images/weather/' + weatherImages[item.gameplay_weather]
        } else { // clear and partly cloudy
            imageUrl = '/static/images/weather/' + weatherImages[item.gameplay_weather + 10]
        }
    } else {
        imageUrl = '/static/images/weather/' + weatherImages[item.gameplay_weather]
    }
    if (!dark) {
        imageUrl = imageUrl.replace('weather_', 'weather_light_')
    }
    return imageUrl
}


/**
 * Creates marker with image
 * @param item
 * @returns {google.maps.Marker}
 */
function setupWeatherMarker(item) {
    var imageUrl = getWeatherImageUrl(item)

    var image = {
        url: imageUrl,
        origin: new google.maps.Point(0, 0),
        anchor: new google.maps.Point(32, 32)
    }
    return new google.maps.Marker({
        position: item.center,
        icon: image
    })
}


/**
 * Creates Polygon for s2cell
 * @param item
 * @returns {google.maps.Polygon}
 */
function setupS2CellPolygon(item) {
    return new google.maps.Polygon({
        paths: item.vertices,
        strokeColor: '#000000',
        strokeOpacity: 0.8,
        strokeWeight: 1,
        fillOpacity: 0,
        fillColor: '#00ff00'
    })
}


/**
 * Adds fillColor for s2cell polygon
 * @param item
 * @returns {google.maps.Polygon}
 */
function createCellAlert(item) {
    var cell = setupS2CellPolygon(item)
    cell.strokeOpacity = 0
    if (item.severity === 0) {
        cell.fillOpacity = 0.0
    } else if (item.severity === 1) {
        cell.fillOpacity = 0.2
        cell.fillColor = '#ffff00'
    } else if (item.severity === 2) {
        cell.fillOpacity = 0.2
        cell.fillColor = '#ff0000'
    }
    return cell
}


/**
 * Calculates square bound for s2cell
 * @param s2Cell
 * @returns {google.maps.LatLngBounds}
 */
function getS2CellBounds(s2Cell) {
    var bounds = new google.maps.LatLngBounds()
    // iterate over the vertices
    $.each(s2Cell.vertices, function (i, latLng) {
        // extend the bounds
        bounds.extend(latLng)
    })
    return bounds
}



// Weather top icon.
var $weatherInfo = document.querySelector('#weatherInfo')

/**
 * Update weather icon on top bar if there is single cell on the screen
 */
function updateMainCellWeather() {
    // remove old weather icon
    while ($weatherInfo.firstChild) {
        $weatherInfo.removeChild($weatherInfo.firstChild)
    }
    var s2Cell = getMainS2Cell()
    if (s2Cell != null) {
        var imgUrl = getWeatherImageUrl(s2Cell, false)
        var icon = document.createElement('img')
        icon.setAttribute('src', imgUrl)
        icon.setAttribute('style', 'height: 50px; vertical-align: middle;')
        $weatherInfo.appendChild(icon)
    }
}


/**
 * Finds weather data for s2cell, that covers more than a half of the screen
 * @returns {*}
 */
function getMainS2Cell() {
    if (typeof window.orientation !== 'undefined' || isMobileDevice()) {
        if (map.getZoom() < 12) { // viewport my contain many cells
            return
        }
    } else {
        if (map.getZoom() < 13) { // viewport my contain many cells
            return
        }
    }

    var geometryFactory = new jsts.geom.GeometryFactory()

    var bounds = map.getBounds()
    var viewportPath = [
        {'lat': bounds.getNorthEast().lat(), 'lng': bounds.getNorthEast().lng()},
        {'lat': bounds.getNorthEast().lat(), 'lng': bounds.getSouthWest().lng()},
        {'lat': bounds.getSouthWest().lat(), 'lng': bounds.getSouthWest().lng()},
        {'lat': bounds.getSouthWest().lat(), 'lng': bounds.getNorthEast().lng()}
    ]
    var jstsViewport = createJstsPolygon(geometryFactory, viewportPath)
    var viewportArea = jstsViewport.getArea()
    var maxCoverageData
    $.each(mapData.weather, function (i, s2cell) {
        var jstsS2cell = createJstsPolygon(geometryFactory, s2cell.vertices)
        var area = jstsViewport.intersection(jstsS2cell).getArea()
        if (viewportArea < area * 2) {  // more then a half of the screen covered by cell
            maxCoverageData = s2cell
        }
    })
    return maxCoverageData
}


/**
 * Creates jsts polygon from coordinates array
 * @param geometryFactory
 * @param path
 * @returns {*}
 */
function createJstsPolygon(geometryFactory, path) {
    var coordinates = path.map(function name(coord) {
        return new jsts.geom.Coordinate(coord.lat, coord.lng)
    })
    if (coordinates[0].compareTo(coordinates[coordinates.length - 1]) !== 0) {
        coordinates.push(coordinates[0])
    }
    var shell = geometryFactory.createLinearRing(coordinates)
    return geometryFactory.createPolygon(shell)
}
