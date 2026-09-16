"""Shared geometry constants for the 40-pin Raspberry Pi mechanical form factor.

Single source of truth for pin coordinates used by gen_rpi5_pin_table.py and
the reference/calibration tooling, mirroring tools/uno_q_geometry.py.

Applies to EVERY 40-pin Pi (B+/2/3/4/5). This is not an assumption: HAT
compatibility is a hard requirement of the Raspberry Pi HAT specification, so
the header's position relative to the board outline and mounting holes is
identical across those models by design. Only the silicon behind the pins
differs (see the per-model generator), never the geometry.

Board frame (see backend/app/profiles/models.py):
  origin = top-left PCB corner seen from above with the 40-pin GPIO header
  along the TOP edge and the USB/Ethernet ports on the RIGHT,
  x -> right along the long edge (85 mm), y -> down (56 mm),
  z -> up from the PCB plane. Header pin openings at z = HEADER_TOP_Z_MM.

  This is the canonical orientation used by every published Pi pinout
  diagram, so silkscreen/photo cross-checks line up without mental rotation.

Coordinate provenance - READ THIS BEFORE TRUSTING THE HEADER OFFSETS
--------------------------------------------------------------------
CERTAIN (official Raspberry Pi documentation, not derived here):
  * PCB outline 85.0 x 56.0 mm.
  * Mounting holes: 3.5 mm in from the left/right and top/bottom edges,
    forming the 58 x 49 mm M2.5 pattern shared by every 40-pin Pi.
  * GPIO header J8 is a 2 x 20 header on a 2.54 mm grid, so its pin-centre
    span is 19 * 2.54 = 48.26 mm and its moulded body is 50.8 x 5.08 mm.
  * Physical pin numbering (identical across all 40-pin Pi models; each
    model's pin functions live in its own generator, e.g.
    gen_rpi5_pin_table.py).

VERIFIED 2026-08-01 against a real Raspberry Pi 5 under the project camera:
  Method: the four M2.5 mounting holes are at known mm (3.5 / 61.5 x 3.5 /
  52.5), so they give a four-point mm->px homography with no dependence on
  edge detection - which matters, because two earlier attempts to find the
  PCB outline by colour failed. A green-PCB mask EXCLUDES the black header
  sitting on the board edge, so the measured "board" came out smaller than
  the real PCB; a desk-distance mask swallowed the whole frame because the
  desk has a reflection gradient. The holes avoid both traps.

  Cross-check that the hole->mm assignment is right: the 58 mm and 49 mm
  hole spans measured 240 px and 203 px, i.e. 4.14 px/mm BOTH ways. A wrong
  assignment would not agree between axes.

  Then each predicted pin was refined to the local metal-pin-tip centroid
  and mapped back through the homography: median residual dx +0.186 mm,
  dy -0.050 mm over all 40 pins (IQR 0.29 / 0.21 mm). Those corrections are
  folded into the constants below.

  Honest limits of this calibration:
   * The refinement window is +/-5 px, about half a pin pitch, so it can
     only correct a SMALL error - it could not detect a whole-pitch offset.
     What rules that out is the visual overlay: all 40 projected points land
     on the header with pin 1 and pin 39 at the correct ends.
   * Residual measured from the final overlay: the two pin columns sit about
     0.23 mm toward the board edge of dead-centre in the header body (1.04
     and 1.49 mm from the body edges instead of 1.27 both sides). That is
     inside the parallax budget below and far under half a pitch (1.27 mm),
     so pin identity is never ambiguous.
   * The overlay proves POSITIONS only. It cannot tell odd rows from even
     rows - see the note on ODD_ROW_IS_NEAR_EDGE.
   * The homography is fitted on the PCB plane (z=0, the mounting holes)
     while the pin tips are at z=HEADER_TOP_Z_MM. At the ~300 mm working
     distance and ~25 mm header offset from the board centre that is an
     estimated ~0.7 mm of residual parallax [ESTIMATE], so treat these
     constants as good to roughly +/-0.5 mm (0.2 pin pitch), not better.
   * The authoritative check remains the runtime's own overlay after
     POST /api/calibrate, because the pipeline solves full 6-DoF pose
     against the 3D pin map (z=8.5) instead of a planar homography.
"""
from __future__ import annotations

# --- Board outline (official) ------------------------------------------------
BOARD_W_MM = 85.0
BOARD_H_MM = 56.0
PITCH_MM = 2.54
# Through-hole header sitting on the PCB: same 8.5 mm socket-opening height
# convention the UNO Q profile uses. For a Pi the header is usually a male
# pin header, so the "opening" plane is the top of the plastic body; keep the
# same constant name and meaning (z of the plane the wire tip reaches).
HEADER_TOP_Z_MM = 8.5

# --- Mounting holes (official: 3.5 mm inset, 58 x 49 mm pattern) -------------
MOUNT_HOLE_INSET_MM = 3.5
MOUNT_HOLES_MM = [
    (MOUNT_HOLE_INSET_MM, MOUNT_HOLE_INSET_MM),
    (BOARD_W_MM - 23.5, MOUNT_HOLE_INSET_MM),          # 61.5 from the left
    (MOUNT_HOLE_INSET_MM, MOUNT_HOLE_INSET_MM + 49.0),
    (BOARD_W_MM - 23.5, MOUNT_HOLE_INSET_MM + 49.0),
]

# --- Header placement (VERIFIED - see module docstring for method+limits) ---
HEADER_PIN1_X_MM = 9.39         # centre of the pin-1 column (measured)
HEADER_ROW_NEAR_EDGE_Y_MM = 1.85  # centre of the row closest to the top edge (measured)
HEADER_ROW_SPACING_MM = PITCH_MM
# On the Pi, odd pins (1,3,..39) and even pins (2,4,..40) form the two rows.
# True  = odd pins are in the row nearest the board edge.
# False = even pins are nearest the edge (odd row is the inner one).
#
# On a standard Pi viewed from above, physical pin 1 (3V3) is on the INBOARD
# row and pin 2 (5V) is on the OUTER row nearest the PCB edge. In this module's
# canonical frame the header is along the top edge, so the even row has the
# smaller y coordinate.
#
# NOTE, because it is easy to get this wrong: the projection overlay CANNOT
# verify this flag. Both rows hold 20 pins, so swapping them produces an
# identical dot pattern - the overlay validates the 40 pin POSITIONS, never
# which label belongs to which row. This value therefore rests on the
# documented convention, not on the overlay. An independent physical check:
# pin 1 is 3V3 and pin 2 is 5V, and pin 1 is the only square pad on the
# underside of the board.
ODD_ROW_IS_NEAR_EDGE = False

HEADER_ID = "J8"
GEOMETRY_VERIFIED = True         # real Pi 5 + hole homography + overlay, 2026-08-01

# The Pi 5 pose dataset uses a board frame rotated 180 degrees from the
# published pinout drawing: in its profile/reference orientation the GPIO
# header is along the bottom edge and physical pin 1 is at the right-hand
# end. Keep the official geometry above as the mechanical source of truth,
# then convert it exactly once when writing the runtime profile.
#
# The pose contour's connector-side edge includes the USB/Ethernet overhang:
# that visible edge is about 5.5 mm outside the hidden PCB registration edge.
# A previous runtime workaround added 5.5 mm to *every* pin. That aligned one
# end of J8 but enlarged the whole 20-pin span, putting the opposite end over
# a mounting hole. Map the hidden edge into the observed pose rectangle while
# keeping the far edge fixed instead. This is an affine registration, so it
# remains valid after 90/180/270-degree board rotations.
PROFILE_HIDDEN_EDGE_INSET_MM = 5.5


def pin_xy_mm(physical_pin: int) -> tuple[float, float]:
    """Centre of a physical header pin (1..40) in the board frame, mm."""
    if not 1 <= physical_pin <= 40:
        raise ValueError(f"physical pin out of range: {physical_pin}")
    column = (physical_pin - 1) // 2          # 0..19, pin 1&2 share column 0
    is_odd = physical_pin % 2 == 1
    near_edge = is_odd if ODD_ROW_IS_NEAR_EDGE else not is_odd
    y = HEADER_ROW_NEAR_EDGE_Y_MM if near_edge else \
        HEADER_ROW_NEAR_EDGE_Y_MM + HEADER_ROW_SPACING_MM
    return (HEADER_PIN1_X_MM + column * PITCH_MM, y)


def profile_pin_xy_mm(physical_pin: int) -> tuple[float, float]:
    """Pin centre in the Pi 5 pose-model/profile board frame."""
    x, y = pin_xy_mm(physical_pin)
    rotated_x = BOARD_W_MM - x
    pose_span = BOARD_W_MM - PROFILE_HIDDEN_EDGE_INSET_MM
    return (
        PROFILE_HIDDEN_EDGE_INSET_MM + rotated_x * pose_span / BOARD_W_MM,
        BOARD_H_MM - y,
    )


def outline_poly_mm() -> list[tuple[float, float]]:
    """PCB outline. 40-pin Pi boards have 3 mm rounded corners; approximated by their
    endpoints, the same way uno_q_geometry handles the UNO's corner arcs."""
    r = 3.0
    w, h = BOARD_W_MM, BOARD_H_MM
    return [
        (r, 0.0), (w - r, 0.0),
        (w, r), (w, h - r),
        (w - r, h), (r, h),
        (0.0, h - r), (0.0, r),
    ]
