# Camera and calibration

The integration was developed on a Miele KM 6203 (four radiant zones, two
dual-ring, red seven-segment displays) with a 1920×1080 camera stream. Other
cooktops with similar displays may work after retuning positions; they have
not been tested. Each digit occupies only a few pixels, so a reduced camera
snapshot may not work. Prefer a Home Assistant camera entity with **Read the
camera's stream** enabled; the integration captures frames using Home
Assistant's ffmpeg. A full-resolution JPEG snapshot URL is another option.
Set the camera to color rather than automatic infrared night vision: IR can
see through the glass, obscuring the displays and zone rings. Set the rotation
that makes the control panel upright.

With displays illuminated, open the integration's annotated **Panel** image
and position each zone and timer digit window over its display. The **Zones**
image shows zone rings and the bare-glass reference area. Fit each ellipse
around its printed ring, and keep the reference on empty glass. The
**Calibrate** action can match the panel landmark and recenter clearly
visible digits; ambiguous or dark digits retain their positions. Admins can
open the visual calibration card using the full card's calibration control or
`type: custom:stove-vision-calibration-card`. Select a target and tap its
center in the frozen frame, preview alignment and readings, then save.
Refresh the frame after saving before making another change.

Calibration records the frame resolution. A subsequent frame at another
resolution is rejected rather than decoded against incorrect coordinates.
The calibration-problem binary sensor reports displaced windows, invalid
coordinates and resolution changes. When a zone is visibly misaligned, the
stove's aggregate sensors do not claim a reassuring off state. Darkness or
obstruction cannot prove that a window is correctly placed.

The options flow also configures polling (10 seconds by default), smoothing
(three frames), rotation, zone and timer digit positions, ring ellipses and
the bare-glass reference. When stream capture is selected, a camera snapshot
can be used as a fallback; check that its resolution matches the calibration.
