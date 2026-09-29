# Remote two-player test plan

## Goal

Verify that two Assetto Corsa players on separate home networks can send telemetry to one RaceCore host during the same online race, and that RaceCore keeps their identities and live states separate.

The players still join their Assetto Corsa multiplayer server using its normal connection details. The private network in this plan carries RaceCore telemetry and API traffic only.

## Current remote-access requirements

- The packaged host currently binds to `127.0.0.1` by default. That accepts connections only from the host PC. For this test, set `RACECORE_HOST` to the host PC's Tailscale IP in `%LOCALAPPDATA%\RaceCore\.env`, then restart RaceCore.
- The CSP client also defaults to `127.0.0.1:8000`. On both players' PCs, set its Host field to `<host-tailscale-ip>:8000`.
- RaceCore's API does not yet require a user login. Keep it on a private network for this test. Do not configure router port forwarding or expose port 8000 to the public internet.

## Recommended network setup

Use Tailscale as a private network between the two PCs. Its device traffic is encrypted with WireGuard, including when it has to relay traffic. Install Tailscale on both Windows PCs and connect them. For a player using a different Tailscale account, share only the RaceCore host machine with that player; the telemetry connection starts from their PC toward the shared host. Check the tailnet access policy before testing because a default policy may allow all devices in that tailnet to reach each other.

1. Pick one PC to run RaceCore. This can also be Player A's Assetto Corsa PC.
2. Install and connect Tailscale on the RaceCore host and both players' PCs. Record the host's Tailscale IPv4 address (`100.x.y.z`).
3. On the host, edit `%LOCALAPPDATA%\RaceCore\.env` and set:

   ```dotenv
   RACECORE_HOST=100.x.y.z
   RACECORE_PORT=8000
   ```

   Replace the example address with the host's actual Tailscale IP. Restart the RaceCore host after changing the file. Binding to that address keeps RaceCore off the host's other network interfaces.
4. Allow inbound TCP port `8000` to the host over Tailscale. Keep the rule limited to the other player's Tailscale address where the firewall supports it. Do not add a router port-forwarding rule.
5. From Player B's PC, confirm the host is reachable:

   ```powershell
   Test-NetConnection 100.x.y.z -Port 8000
   Invoke-RestMethod http://100.x.y.z:8000/health
   ```

   The health response should report `status: ok` and `service: racecore`.
6. In both CSP RaceCore Client windows, set Host to `100.x.y.z:8000`. Configure the same session ID, but a different configured car ID and driver ID for each player.
7. Confirm both configured entries exist in the session before connecting the CSP clients. RaceCore rejects telemetry whose session, car, or driver identity does not match an entry.

## Test checklist

### A. Preflight

- [ ] Record date, RaceCore version, CSP version, Assetto Corsa version, track, cars, and both players' regions.
- [ ] Record which PC hosts RaceCore and whether PostgreSQL persistence is enabled.
- [ ] Confirm both players can join the same Assetto Corsa multiplayer server and session.
- [ ] Confirm both PCs show as connected in Tailscale and Player B can open the host's `/health` endpoint.
- [ ] Confirm both session entries have unique car IDs and driver IDs.
- [ ] Confirm each CSP client is configured with the host's Tailscale IP, the same session ID, and its own car and driver IDs.

### B. Basic two-player telemetry

- [ ] Connect Player A's CSP client. Confirm it reports `Streaming telemetry` and its configured car changes to connected in `/api/v1/sessions/{session_id}/telemetry/health`.
- [ ] Connect Player B's CSP client. Confirm both cars show connected at the same time.
- [ ] Open `/api/v1/sessions/{session_id}/cars/{car_id}/telemetry` for each car. Confirm each history contains only that player's car and driver IDs, and that samples continue arriving.
- [ ] Compare displayed speed, gear, throttle, brake, lap, and pit state with each player's cockpit values. Record any fields that look wrong or update slowly.
- [ ] Check `/api/v1/sessions/{session_id}/race-state`. Confirm both entries appear and the reported order changes as the players move around the track.
- [ ] Record each client's round-trip latency and the host's reported packet age, sequence gaps, and connection state.

### C. Race and network behavior

- [ ] Drive at least 10 laps together. Include normal running, one pit entry, one pit exit, and one completed lap per player.
- [ ] Confirm completed lap and sector data is attributed to the correct driver.
- [ ] Have Player B disconnect the CSP app for 30 seconds, then reconnect. Confirm the host marks that car stale or disconnected while Player A remains connected, then restores Player B to connected after packets resume.
- [ ] Briefly disconnect and reconnect Player B's Tailscale connection. Confirm automatic CSP reconnect works and Player A's stream is unaffected.
- [ ] Close and reopen Player B's CSP app. Confirm the client can reconnect without restarting RaceCore.
- [ ] If practical, briefly stop and restart RaceCore. Record which session and live state survive; RAM-only live telemetry is expected to clear when the host process restarts.
- [ ] Keep both cars connected for 30 minutes. Check the health endpoint every five minutes and record latency, packet gaps, stale events, and any visible client errors.

### D. Identity and rejection checks

- [ ] Try a wrong session ID from one CSP client. Confirm the host refuses that stream and the other player's telemetry continues.
- [ ] Try a car ID or driver ID that is not configured in the session. Confirm the stream is rejected and no unknown car appears in race state.
- [ ] Restore the correct IDs and confirm the client reconnects and resumes telemetry.

### E. Finish and collect results

- [ ] End the test session cleanly and note the final race state.
- [ ] Save the session ID, both car IDs and driver IDs, start/end time, and the telemetry health and race-state responses.
- [ ] Note any client disconnect/reconnect times, errors, stale periods, incorrect fields, or order/gap anomalies.
- [ ] Decide whether the test passed, failed, or needs a repeat, and list the specific follow-up items.

## Pass criteria

- Both players stream at the same time from separate home networks through the private network.
- RaceCore keeps each player's telemetry attached to the correct configured car and driver.
- Packet health and latency data are available for both cars, and a dropped connection for one player does not disrupt the other.
- Each CSP client recovers after a temporary network or app disconnect without restarting the host.
- The session and race-state endpoints remain responsive throughout the 30-minute run.

Do not treat one successful short run as proof that public internet hosting is ready. This test validates a private two-player path; authentication and production remote hosting still need separate work.

## Record sheet

| Item | Player A | Player B |
| --- | --- | --- |
| Region / approximate distance |  |  |
| Network type (wired, Wi-Fi, mobile) |  |  |
| Tailscale connected |  |  |
| Car ID / driver ID |  |  |
| Average / highest observed round-trip latency |  |  |
| Packet gaps or stale events |  |  |
| Disconnect and recovery notes |  |  |

RaceCore host version:
Session ID:
Test start / end:
Outcome and follow-up:

## References

- [Install Tailscale on Windows](https://tailscale.com/docs/install/windows)
- [Share a machine with another Tailscale user](https://tailscale.com/kb/1084/sharing)
- [Tailscale encryption](https://tailscale.com/docs/concepts/tailscale-encryption)
- [Tailscale access-control examples](https://tailscale.com/docs/reference/examples/grants)
