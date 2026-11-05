# Detection and entities

Four zone sensors report `off`, `0`, levels `1`–`9`, `residual_heat`,
`obstructed` or `unknown`. Residual heat has a bar count; raw readings and
interpreted levels are attributes. A separate sensor reads the two-digit
timer from agreeing recent frames, without inventing a countdown when the
display is unreadable. Per-zone occupancy binary sensors report whether a
pot or other object is present; readings remain uncertain without enough
evidence. Aggregate binary sensors report heating (`on`), hot zones (`hot`),
and heating without confirmed occupancy (`danger`). The `danger` sensor
includes zones, levels and reasons such as `free` or `unsure`; residual heat
alone does not trigger it. Diagnostic entities include infrared detection,
calibration warnings, a manual refresh button, and annotated panel and zone
images.

A danger condition begins when an empty or uncertain zone heats. Waiting a
few minutes before notifying avoids an alert while a pot is being placed.
Use the actual entity ID created in your instance:

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.example_stove_danger
    to: "on"
    for:
      minutes: 5
actions:
  - action: notify.notify
    data:
      message: Stove zone heating without a confirmed pot
```

The decoder distinguishes tinted LED edges from white glare, samples
seven-segment patterns and recognizes stacked residual-heat bars. Several
frames smooth multiplexed displays: a zone becomes off only after agreeing
frames; obstructed frames do not vote. Occupancy combines whether the
printed ring remains visible with brightness relative to a bare-glass
reference. A small or dark pan may be missed, especially in poor light.
Camera infrared invalidates display readings and resets occupancy instead
of retaining a potentially misleading verdict. Treat all classifications
and advisories as estimates, not as a fire-prevention system.

Run the fixture-based decoder tests with `python -m pytest tests` in a
development environment with the project's test dependencies installed.
