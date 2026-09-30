local settings = ac.storage({
  host = '127.0.0.1:8000',
  sessionID = '',
  carID = '',
  driverID = ''
}, 'RACECORE_CLIENT_')

local sim = ac.getSim()
local telemetrySocket = nil
local connectionText = 'Not configured'
local sequence = math.floor(os.time() * 1000)
local sendElapsed = 0
local sendInterval = 1 / 20
local lastReply = ''
local lastLapCount = nil
local lapTimes = {}
local lapHistoryComplete = nil
local pendingPackets = {}
local lastRoundTripMs = nil
local leaderboard = {}
local lastLeaderboardAt = nil
local latestDriving = nil
local inputHistory = { steering = {}, throttle = {}, brake = {} }
local inputHistoryLimit = 80

local function sectorTimes(car)
  local times = {}
  for i = 0, 2 do
    local milliseconds = car.currentSplits[i]
    if milliseconds and milliseconds > 0 then
      times[#times + 1] = milliseconds / 1000
    end
  end
  return times
end

local function splitTimes(splits)
  local times = {}
  for i = 0, 2 do
    local milliseconds = splits[i]
    if milliseconds and milliseconds > 0 then
      times[#times + 1] = milliseconds / 1000
    end
  end
  return times
end

local function tyreData(car)
  local temperatures = {}
  local pressures = {}
  for i = 0, 3 do
    local wheel = car.wheels[i]
    temperatures[#temperatures + 1] = wheel.tyreCoreTemperature or 0
    pressures[#pressures + 1] = wheel.tyrePressure or 0
  end
  return temperatures, pressures
end

local function damageData(car)
  local damage = {}
  for i = 0, 3 do
    damage['collision_zone_' .. i] = car.damage[i] or 0
    damage['suspension_' .. i] = car.suspensionDamage[i] or 0
  end
  damage.gearbox = car.gearboxDamage or 0
  return damage
end

local function drivingData(car)
  local rpm = math.max(0, math.floor(car.rpm or 0))
  return {
    gear = car.gear or 0,
    rpm = rpm,
    rpm_limit = math.max(rpm, car.rpmLimiter or car.maxRpm or 9000),
    speed_kmh = math.max(0, car.speedKmh or 0),
    throttle = math.saturate(car.gas or 0),
    brake = math.saturate(car.brake or 0),
    steering_angle_deg = car.steer or 0,
    steering = math.clamp((car.steer or 0) / math.max(1, car.steerLock or 1), -1, 1)
  }
end

local function connect()
  if settings.sessionID == '' or settings.carID == '' or settings.driverID == '' then
    connectionText = 'Enter the session, car and driver IDs.'
    return
  end

  local url = string.format(
    'ws://%s/api/v1/sessions/%s/telemetry/ws?car_id=%s&driver_id=%s',
    settings.host,
    settings.sessionID,
    settings.carID,
    settings.driverID)

  telemetrySocket = web.socket(url, nil, function (reply)
    if type(reply) == 'table' then
      if reply.accepted then
        connectionText = 'Streaming telemetry'
        lastReply = tostring(reply.sequence or '')
        if type(reply.leaderboard) == 'table' then
          leaderboard = reply.leaderboard
          lastLeaderboardAt = os.preciseClock()
        end
        local sentAt = pendingPackets[reply.sequence]
        if sentAt then
          lastRoundTripMs = math.max(0, (os.preciseClock() - sentAt) * 1000)
          pendingPackets[reply.sequence] = nil
        end
      else
        connectionText = 'Rejected: ' .. tostring(reply.error or 'unknown error')
      end
    end
  end, {
    encoding = 'json',
    reconnect = true,
    onError = function (err)
      connectionText = 'Connection error: ' .. tostring(err)
    end,
    onClose = function ()
      connectionText = 'Disconnected; reconnecting…'
    end
  })
  connectionText = 'Connecting to RaceCore…'
end

local function disconnect()
  if telemetrySocket then
    telemetrySocket.close()
    telemetrySocket = nil
  end
  connectionText = 'Disconnected'
end

local function telemetryPacket(car)
  local position = car.position
  local speed = car.speedKmh or 0
  local driving = drivingData(car)
  latestDriving = driving
  local temperatures, pressures = tyreData(car)
  local splits = sectorTimes(car)
  local completedLapTime = nil
  local completedLapSectorTimes = {}
  if lapHistoryComplete == nil then
    lapHistoryComplete = car.lapCount == 0
  end
  if lastLapCount ~= nil and car.lapCount < lastLapCount then
    lapTimes = {}
  elseif lastLapCount ~= nil and car.lapCount > lastLapCount
      and car.previousLapTimeMs and car.previousLapTimeMs > 0 then
    lapTimes[#lapTimes + 1] = car.previousLapTimeMs / 1000
    completedLapTime = car.previousLapTimeMs / 1000
    completedLapSectorTimes = splitTimes(car.lastSplits)
  end
  lastLapCount = car.lapCount

  local pitStatus = 'on_track'
  if car.isInPit then
    pitStatus = 'pit_box'
  elseif car.isInPitlane then
    pitStatus = 'pit_lane'
  end

  return {
    car_id = settings.carID,
    driver_id = settings.driverID,
    sequence = sequence,
    speed_kmh = math.max(0, speed),
    rpm = driving.rpm,
    gear = driving.gear,
    throttle = driving.throttle,
    brake = driving.brake,
    steering = driving.steering,
    fuel_liters = car.fuel,
    tyre_temperatures_c = temperatures,
    tyre_pressures_psi = pressures,
    current_lap = math.max(0, car.lapCount or 0),
    sector = car.currentSector and car.currentSector + 1 or nil,
    sector_times = splits,
    lap_times = lapTimes,
    lap_history_complete = lapHistoryComplete,
    completed_lap_time_seconds = completedLapTime,
    completed_lap_sector_times = completedLapSectorTimes,
    completed_lap_valid = car.isLastLapValid,
    track_position = math.saturate(car.splinePosition or 0),
    track_length_m = sim.trackLengthM,
    position_xyz = { position.x, position.y, position.z },
    pit_status = pitStatus,
    damage_state = damageData(car),
    retired = car.isRetired,
    client_round_trip_ms = lastRoundTripMs,
    car_state = car.isActive and (speed > 0 and 'running' or 'stationary') or 'inactive'
  }
end

local function localLeaderboard()
  local rows = {}
  local carCount = sim.carsCount or 0
  for index = 0, carCount - 1 do
    local car = ac.getCar(index)
    if car and car.isActive ~= false and car.racePosition and car.racePosition > 0 then
      local temperatures = {}
      for wheel = 0, 3 do
        local state = car.wheels and car.wheels[wheel]
        temperatures[#temperatures + 1] = state and state.tyreCoreTemperature or 0
      end
      local driverName = car:driverName()
      if driverName == nil or driverName == '' then driverName = 'Driver ' .. tostring(index + 1) end
      rows[#rows + 1] = {
        is_local = index == 0,
        position = car.racePosition,
        driver_name = driverName,
        current_lap = car.lapCount or 0,
        track_position = car.splinePosition or 0,
        speed_kmh = car.speedKmh or 0,
        tyre_compound = ac.getTyresName(index),
        tyre_temperatures_c = temperatures,
        gap_to_ahead_seconds = nil,
        ping_ms = car.ping and car.ping >= 0 and car.ping or nil,
        connection_status = car.isConnected == false and 'disconnected' or 'connected'
      }
    end
  end

  table.sort(rows, function (a, b) return a.position < b.position end)
  for index = 2, #rows do
    local ahead = rows[index - 1]
    local car = rows[index]
    local progressAhead = ahead.current_lap + ahead.track_position
    local progress = car.current_lap + car.track_position
    local length = sim.trackLengthM or 0
    local averageSpeed = math.max((car.speed_kmh + ahead.speed_kmh) / 7.2, 1)
    car.gap_to_ahead_seconds = math.max(0, (progressAhead - progress) * length / averageSpeed)
  end
  return rows
end

function script.update(dt)
  if sim.isInMainMenu or sim.isReplayActive then return end

  local car = ac.getCar(0)
  if not car or not car.position then return end
  latestDriving = drivingData(car)
  for key, value in pairs({
    steering = latestDriving.steering,
    throttle = latestDriving.throttle,
    brake = latestDriving.brake
  }) do
    local history = inputHistory[key]
    history[#history + 1] = value
    if #history > inputHistoryLimit then table.remove(history, 1) end
  end
  if not lastLeaderboardAt or os.preciseClock() - lastLeaderboardAt > 3 then
    leaderboard = localLeaderboard()
  end
  if not telemetrySocket then return end

  sendElapsed = sendElapsed + dt
  if sendElapsed < sendInterval then return end
  sendElapsed = sendElapsed % sendInterval

  local now = os.preciseClock()
  for pendingSequence, sentAt in pairs(pendingPackets) do
    if now - sentAt > 10 then pendingPackets[pendingSequence] = nil end
  end
  pendingPackets[sequence] = now
  telemetrySocket(telemetryPacket(car))
  sequence = sequence + 1
end

function script.windowMain()
  ui.text('RaceCore Client')
  ui.separator()
  ui.text('Host')
  settings.host = ui.inputText('##host', settings.host)
  ui.text('Session ID')
  settings.sessionID = ui.inputText('##session', settings.sessionID)
  ui.text('Configured car ID')
  settings.carID = ui.inputText('##car', settings.carID)
  ui.text('Configured driver ID')
  settings.driverID = ui.inputText('##driver', settings.driverID)

  if telemetrySocket then
    if ui.button('Disconnect') then disconnect() end
  elseif ui.button('Connect') then
    connect()
  end
  ui.text(connectionText)
  if lastReply ~= '' then ui.text('Last packet acknowledged: ' .. lastReply) end
  if lastRoundTripMs then ui.text(string.format('Client round trip: %.1f ms', lastRoundTripMs)) end
end

local function formatInterval(seconds, position)
  if tonumber(position) == 1 then return '--' end
  if seconds == nil then return '--' end
  return string.format('~+%.1fs', seconds)
end

local function drawPanelBackground(width, height, showAccent)
  ui.drawRectFilled(vec2(0, 0), vec2(width, height), rgbm(0.015, 0.02, 0.025, 0.88), 5)
  if showAccent ~= false then
    ui.drawRectFilled(vec2(0, 0), vec2(width, 2), rgbm(1, 0.78, 0.08, 0.95))
  end
end

local function sessionCode()
  local kind = sim.raceSessionType
  if kind == ac.SessionType.Practice then return 'PRAC' end
  if kind == ac.SessionType.Qualify then return 'QUAL' end
  if kind == ac.SessionType.Race then return 'RACE' end
  if kind == ac.SessionType.Hotlap then return 'HOTLAP' end
  if kind == ac.SessionType.TimeAttack then return 'TIME' end
  if kind == ac.SessionType.Drift then return 'DRIFT' end
  if kind == ac.SessionType.Drag then return 'DRAG' end
  return string.upper(ac.getSessionName(sim.currentSessionIndex) or 'SESSION')
end

local function sessionHeaderLine()
  local session = ac.getSession(sim.currentSessionIndex)
  local showTime = sim.raceSessionType ~= ac.SessionType.Race or (session and session.isTimedRace)
  local playerCar = ac.getCar(0)
  local lapCount = playerCar and ((playerCar.lapCount or 0) + 1) or 1
  local clock = nil
  if showTime then
    local timeLeft = sim.sessionTimeLeft or 0
    local secondsLeft = math.floor(math.abs(timeLeft) / 1000)
    local hours = math.floor(secondsLeft / 3600)
    local minutes = math.floor(secondsLeft / 60) % 60
    local seconds = secondsLeft % 60
    clock = hours > 0 and string.format('%d:%02d:%02d', hours, minutes, seconds)
      or string.format('%d:%02d', minutes, seconds)
    if timeLeft < 0 then clock = 'Overtime' end
  end
  if clock then return string.format('%s  |  Time: %s   Lap: %d', sessionCode(), clock, lapCount) end
  return string.format('%s  |  Lap: %d', sessionCode(), lapCount)
end

local function flagBanner()
  local flag = sim.raceFlagType
  if flag == ac.FlagType.Start then return 'GREEN FLAG', rgbm(0.08, 0.82, 0.24, 1), rgbm(0.02, 0.05, 0.02, 1) end
  if flag == ac.FlagType.Caution then return 'YELLOW FLAG', rgbm(1, 0.78, 0.08, 1), rgbm(0.08, 0.06, 0, 1) end
  if flag == ac.FlagType.Stop then return 'BLACK FLAG', rgbm(0.03, 0.03, 0.03, 1), rgbm(1, 1, 1, 1) end
  if flag == ac.FlagType.ReturnToPits then return 'PENALTY', rgbm(0.84, 0.08, 0.08, 1), rgbm(1, 1, 1, 1) end
  if flag == ac.FlagType.FasterCar then return 'BLUE FLAG', rgbm(0.08, 0.28, 0.86, 1), rgbm(1, 1, 1, 1) end
  if flag == ac.FlagType.OneLapLeft then return 'WHITE FLAG', rgbm(0.92, 0.92, 0.92, 1), rgbm(0.08, 0.08, 0.08, 1) end
  if flag == ac.FlagType.Finished then return 'RACE OVER', rgbm(0.92, 0.92, 0.92, 1), rgbm(0.08, 0.08, 0.08, 1) end
  local kind = sim.raceSessionType
  if flag == ac.FlagType.None and (kind == ac.SessionType.Practice or kind == ac.SessionType.Qualify or kind == ac.SessionType.Hotlap) then
    return 'GREEN FLAG', rgbm(0.08, 0.82, 0.24, 1), rgbm(0.02, 0.05, 0.02, 1)
  end
  return nil, rgbm(0.02, 0.02, 0.02, 0.5), rgbm(1, 1, 1, 1)
end

local function conditionsLine()
  return string.format('Wind: %.0f km/h   Air: %.0f°C   Tarmac: %.0f°C   Grip: %.1f%%',
    sim.windSpeedKmh or 0,
    sim.ambientTemperature or 0,
    sim.roadTemperature or 0,
    (sim.roadGrip or 0) * 100)
end

local function isLocalDriver(entry)
  if entry.is_local == true or (entry.car_id ~= nil and settings.carID ~= '' and entry.car_id == settings.carID) then return true end
  local playerCar = ac.getCar(0)
  local playerName = playerCar and playerCar:driverName() or nil
  return playerName ~= nil and entry.driver_name == playerName
end

local function findCarForEntry(entry)
  for index = 0, (sim.carsCount or 0) - 1 do
    local car = ac.getCar(index)
    if car and car.racePosition == tonumber(entry.position) then
      local name = car:driverName()
      if name == entry.driver_name then return car, index end
    end
  end
  return nil, nil
end

local function tyreCompound(entry, carIndex)
  if entry.tyre_compound and entry.tyre_compound ~= '' then return entry.tyre_compound end
  if carIndex == nil then
    local matchedCar
    matchedCar, carIndex = findCarForEntry(entry)
  end
  if carIndex ~= nil then
    local compound = ac.getTyresName(carIndex)
    if compound and compound ~= '' then return compound end
  end
  return '--'
end

local function formatLapTime(milliseconds)
  if milliseconds == nil or milliseconds <= 0 then return '--' end
  local totalSeconds = milliseconds / 1000
  return string.format('%d:%06.3f', math.floor(totalSeconds / 60), totalSeconds % 60)
end

local function lapTimeForEntry(entry, isRace, car)
  if car == nil then car = findCarForEntry(entry) end
  if car then
    local time = isRace and car.previousLapTimeMs or car.bestLapTimeMs
    if time and time > 0 then return formatLapTime(time) end
  end

  local times = entry.lap_times or {}
  if #times > 0 then
    local seconds = times[#times]
    if not isRace then
      seconds = times[1]
      for _, lapTime in ipairs(times) do
        if lapTime < seconds then seconds = lapTime end
      end
    end
    return formatLapTime(seconds * 1000)
  end
  if not isRace and entry.best_lap_seconds then
    return formatLapTime(entry.best_lap_seconds * 1000)
  end
  return '--'
end

local function drawLeaderboardCell(value, x, width, y, color, alignment)
  ui.drawTextClipped(
    tostring(value),
    vec2(x, y),
    vec2(x + width, y + 20),
    color or rgbm(0.92, 0.93, 0.94, 1),
    alignment or vec2(0, 0),
    true)
end

function script.windowLeaderboard()
  local rowStart = 78
  local rowStep = 26
  local rowHeight = 24
  local rowCount = math.max(#leaderboard, 1)
  local panelHeight = rowStart + rowCount * rowStep + 5
  drawPanelBackground(440, panelHeight, false)
  local stale = lastLeaderboardAt and os.preciseClock() - lastLeaderboardAt > 3
  local sessionText = sessionHeaderLine()
  if stale then sessionText = 'ASSETTO CORSA   |   ' .. sessionText end
  drawLeaderboardCell(sessionText, 10, 250, 8, rgbm(0.96, 0.96, 0.97, 1))
  local flagText, flagColor, flagTextColor = flagBanner()
  ui.drawRectFilled(vec2(270, 0), vec2(440, 30), flagColor)
  if flagText then drawLeaderboardCell(flagText, 278, 154, 6, flagTextColor) end
  drawLeaderboardCell(conditionsLine(), 10, 420, 34, rgbm(0.72, 0.75, 0.78, 1))
  local weather = string.format('AIR %.0f°   ROAD %.0f°', sim.ambientTemperature or 0, sim.roadTemperature or 0)
  local headerColor = rgbm(0.70, 0.73, 0.76, 1)
  ui.drawRectFilled(vec2(6, 54), vec2(434, 76), rgbm(0.16, 0.18, 0.20, 0.88))
  local isRace = sim.raceSessionType == ac.SessionType.Race
  drawLeaderboardCell('POS', 8, 25, 56, headerColor, vec2(0.5, 0))
  drawLeaderboardCell('DRIVER', 42, 142, 56, headerColor)
  drawLeaderboardCell('TYRE', 188, 38, 56, headerColor, vec2(0.5, 0))
  drawLeaderboardCell('INT', 232, 55, 56, headerColor, vec2(1, 0))
  drawLeaderboardCell('PING', 293, 37, 56, headerColor, vec2(1, 0))
  drawLeaderboardCell(isRace and 'LAST' or 'BEST', 337, 88, 56, headerColor, vec2(1, 0))
  ui.drawRectFilled(vec2(6, 76), vec2(434, 77), rgbm(1, 1, 1, 0.42))

  if #leaderboard == 0 then
    drawLeaderboardCell('No leaderboard data in this session.', 12, 410, 81, rgbm(0.82, 0.84, 0.86, 1))
  else
    for index, entry in ipairs(leaderboard) do
      local y = rowStart + (index - 1) * rowStep
      local localDriver = isLocalDriver(entry)
      local disconnected = entry.connection_status and entry.connection_status ~= 'connected'
      local rowColor = localDriver and rgbm(0.18, 0.14, 0.025, 0.96)
        or (disconnected and rgbm(0.09, 0.10, 0.11, 0.88)
          or (index % 2 == 0 and rgbm(0.08, 0.09, 0.10, 0.80) or rgbm(0.025, 0.03, 0.035, 0.74)))
      ui.drawRectFilled(vec2(6, y), vec2(434, y + rowHeight), rowColor)
      local textColor = localDriver and rgbm(1, 0.82, 0.16, 1)
        or (disconnected and rgbm(0.58, 0.60, 0.62, 1) or rgbm(0.90, 0.91, 0.92, 1))
      local position = entry.position or index
      local name = entry.driver_name
      if name == nil or name == '' then name = entry.car_id or 'Unknown' end
      local car, carIndex = findCarForEntry(entry)
      local compound = tyreCompound(entry, carIndex)
      local interval = formatInterval(entry.gap_to_ahead_seconds, entry.position)
      local lapTime = lapTimeForEntry(entry, isRace, car)
      local ping = '--'
      if entry.connection_status and entry.connection_status ~= 'connected' then
        ping = 'OFF'
      elseif entry.ping_ms ~= nil then
        ping = string.format('%3.0f', entry.ping_ms)
      end
      ui.drawRectFilled(vec2(8, y + 2), vec2(33, y + 22), localDriver and rgbm(1, 0.76, 0.08, 1) or rgbm(0.96, 0.97, 0.97, 1))
      drawLeaderboardCell(position, 8, 25, y + 3, rgbm(0.04, 0.05, 0.06, 1), vec2(0.5, 0))
      ui.drawRectFilled(vec2(35, y + 2), vec2(37, y + 22), rgbm(0.26, 0.90, 0.37, 1))
      drawLeaderboardCell(name, 42, 142, y + 4, textColor)
      drawLeaderboardCell(compound, 188, 38, y + 4, textColor, vec2(0.5, 0))
      drawLeaderboardCell(interval, 232, 55, y + 4, textColor, vec2(1, 0))
      drawLeaderboardCell(ping, 293, 37, y + 4, textColor, vec2(1, 0))
      drawLeaderboardCell(lapTime, 337, 88, y + 4, textColor, vec2(1, 0))
    end
  end
  for _, x in ipairs({ 39, 184, 228, 289, 333 }) do
    ui.drawRectFilled(vec2(x, 54), vec2(x + 1, panelHeight - 5), rgbm(1, 1, 1, 0.10))
  end
  ui.setCursor(vec2(0, panelHeight - 2))
  ui.dummy(vec2(440, 1))
end

function script.windowGearRPM()
  local driving = latestDriving
  local ratio = driving and math.saturate(driving.rpm / math.max(1, driving.rpm_limit)) or 0
  local panelColor = ratio >= 0.93 and rgbm(0.11, 0.018, 0.024, 0.94) or rgbm(0.015, 0.018, 0.024, 0.90)
  ui.drawRectFilled(vec2(0, 0), vec2(340, 112), panelColor, 56)
  local gearLabel = driving and (driving.gear < 0 and 'R' or driving.gear == 0 and 'N' or tostring(driving.gear)) or '--'
  local ringColor = ratio >= 0.93 and rgbm(1, 0.20, 0.12, 1)
    or (ratio >= 0.72 and rgbm(1, 0.76, 0.08, 1) or rgbm(0.28, 0.88, 0.43, 1))

  local center, radius = vec2(55, 56), 36
  ui.drawCircle(center, radius, rgbm(0.29, 0.31, 0.33, 0.85), 64, 8)
  if ratio > 0 then
    local arcStart = math.rad(135)
    ui.pathClear()
    ui.pathArcTo(center, radius, arcStart, arcStart + math.min(ratio, 0.98) * math.rad(270), 48)
    ui.pathStroke(ringColor, false, 8)
  end
  ui.dwriteDrawTextClipped(gearLabel, 39, vec2(19, 20), vec2(91, 92), ui.Alignment.Center, ui.Alignment.Center, false, rgbm(1, 1, 1, 1))

  local dotCount = 15
  for i = 1, dotCount do
    local x = 116 + (i - 1) * 14
    local color = rgbm(0.20, 0.22, 0.24, 0.82)
    if i / dotCount <= ratio then
      color = i >= 14 and rgbm(1, 0.20, 0.12, 1)
        or (i >= 11 and rgbm(1, 0.76, 0.08, 1) or rgbm(0.50, 0.90, 0.44, 1))
    end
    ui.drawCircleFilled(vec2(x, 18), 4, color, 16)
  end

  ui.dwriteDrawTextClipped('KMH', 12, vec2(111, 48), vec2(190, 64), ui.Alignment.Start, ui.Alignment.Center, false, rgbm(0.70, 0.73, 0.76, 1))
  ui.dwriteDrawTextClipped('RPM', 12, vec2(211, 48), vec2(324, 64), ui.Alignment.Start, ui.Alignment.Center, false, rgbm(0.70, 0.73, 0.76, 1))
  ui.dwriteDrawTextClipped(driving and string.format('%.0f', driving.speed_kmh) or '--', 27, vec2(111, 60), vec2(194, 98), ui.Alignment.Start, ui.Alignment.Center, false, rgbm(1, 1, 1, 1))
  ui.dwriteDrawTextClipped(driving and tostring(driving.rpm) or '--', 27, vec2(211, 60), vec2(328, 98), ui.Alignment.Start, ui.Alignment.Center, false, rgbm(1, 1, 1, 1))

end

local function drawPedalTrace(label, history, top, value, color)
  local left, width, height = 94, 129, 18
  ui.setCursor(vec2(left, top))
  ui.text(label)
  ui.setCursor(vec2(left + width - 31, top))
  ui.text(string.format('%3.0f%%', value * 100))
  ui.drawRectFilled(vec2(left, top + 15), vec2(left + width, top + 15 + height), rgbm(0.01, 0.015, 0.02, 0.85))
  local mid = top + 24
  ui.drawLine(vec2(left, mid), vec2(left + width, mid), rgbm(1, 1, 1, 0.12), 1)
  if #history < 2 then return end
  ui.pathClear()
  for i, value in ipairs(history) do
    local x = left + ((i - 1) / (inputHistoryLimit - 1)) * width
    local y = top + 15 + height - value * (height - 2) - 1
    ui.pathLineTo(vec2(x, y))
  end
  ui.pathSimpleStroke(color, false, 2)
end

function script.windowDriverInputs()
  drawPanelBackground(235, 116)
  ui.setCursor(vec2(11, 9))
  ui.text('TRACES  /  LIVE INPUT')
  local driving = latestDriving
  if driving then
    local center = vec2(50, 72)
    local radius = 25
    ui.setCursor(vec2(11, 34))
    ui.text('STEER')
    ui.drawCircle(center, radius, rgbm(1, 1, 1, 0.32), 48, 3)
    local steerAngle = math.clamp(driving.steering_angle_deg, -330, 330)
    if math.abs(steerAngle) > 1 then
      local neutral = -math.pi / 2
      local extent = math.rad(steerAngle)
      local fromAngle = steerAngle > 0 and neutral or neutral + extent
      local toAngle = steerAngle > 0 and neutral + extent or neutral
      ui.pathClear()
      ui.pathArcTo(center, radius, fromAngle, toAngle, 24)
      ui.pathStroke(rgbm(1, 1, 1, 1), false, 4)
    end
    drawPedalTrace('GAS', inputHistory.throttle, 34, driving.throttle, rgbm(0.25, 0.82, 0.42, 1))
    drawPedalTrace('BRAKE', inputHistory.brake, 73, driving.brake, rgbm(0.96, 0.27, 0.19, 1))
  else
    ui.setCursor(vec2(11, 46))
    ui.text('Waiting for car...')
  end
end

ac.onRelease(disconnect)
