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
    rpm = math.max(0, math.floor(car.rpm or 0)),
    gear = car.gear or 0,
    throttle = math.saturate(car.gas or 0),
    brake = math.saturate(car.brake or 0),
    steering = math.clamp((car.steer or 0) / math.max(1, car.steerLock or 1), -1, 1),
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

function script.update(dt)
  if not telemetrySocket or sim.isInMainMenu or sim.isReplayActive then return end

  sendElapsed = sendElapsed + dt
  if sendElapsed < sendInterval then return end
  sendElapsed = sendElapsed % sendInterval

  local car = ac.getCar(0)
  if not car or not car.position then return end
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

ac.onRelease(disconnect)
