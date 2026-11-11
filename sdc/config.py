"""All tunable parameters for block 3, in one place.

The paper calls these tunable and gives no numbers; the values here are only
what the mock scenarios currently use. Every rule that reads one of them names
it, so each event can be explained as "X exceeded <tunable>".

Units: seconds, metres, radians, per-minute rates.
"""
import math

# ---------------------------------------------------------------- signal layer: timing
SIGNAL_TICK_S = 1.0             # rules are evaluated once per tick (~1 Hz); features aggregate the frames in it
ATTENTION_DEBOUNCE_S = 0.2      # an attention change counts only if the new target holds this long (drops 1-frame flicker)
MIN_TRACK_CONF = 0.6            # frames below this tracking confidence are ignored

# ---------------------------------------------------------------- signal layer: baselines (D4)
# baseline = (prior_weight * prior + sum(samples)) / (prior_weight + n_samples).
# The start impression supplies the prior; its weight fades linearly to 0 by stop index SEED_FADE_STOPS
# (0-based stop 2 = the third stop). Samples taken while a related event is active are not added,
# so an event doesn't erase itself by becoming the new normal.
SEED_FADE_STOPS = 2
SEED_WEIGHT_S = 30.0            # at the first stop the seed counts like this many seconds of observation
BASELINE_MIN_S = 5.0            # with no seed, a baseline needs this much observation before rules use it
DWELL_PRIOR_S = 4.0             # prior mean dwell on one target (not in the seed; same for child and adult)
DWELL_PRIOR_RUNS = 5            # ... counted as this many observed dwells
STATE_PRIOR_FRAC = 0.0          # prior share of time in a state (looking at another exhibit, leaning, facing away)
STATE_BASELINE_MAX_FRAC = 0.3   # a state is a deviation only if the visitor is in it less than this share of the time normally

# ---------------------------------------------------------------- orientation helpers
ORIENTED_TO_STOP_RAD = math.radians(60)   # body facing the current stop's exhibit within this angle
FACING_AWAY_RAD = math.radians(100)       # body turned at least this far from the stop's exhibit
STILL_SPEED_MPS = 0.15                    # slower than this counts as standing still

# ---------------------------------------------------------------- linger
LINGER_MIN_S = 12.0             # dwell on one feature at least this long ...
LINGER_FACTOR = 5.0             # ... and at least this many times the visitor's own mean dwell (the main term)
LINGER_OFF_S = 2.0              # linger ends after attention has left the feature this long

# ---------------------------------------------------------------- approach (inside the formation)
APPROACH_MIN_DROP_M = 0.3       # distance to the exhibit at least this far below own in-formation baseline
APPROACH_ON_S = 1.0
APPROACH_OFF_S = 2.0

# ---------------------------------------------------------------- point / ask
POINT_MIN_S = 0.5               # pointing must last this long
POINT_ASK_MERGE_S = 3.0         # a point and a question from the same visitor this close together are one event
OVERLAPPED_QUESTION_IS_POINT_ASK = True   # a talked-over question is a bid + barrier AND a point/ask (fix first, then answer)

# ---------------------------------------------------------------- drift (gaze on another exhibit)
DRIFT_ON_S = 3.0
DRIFT_OFF_S = 3.0

# ---------------------------------------------------------------- fatigue
FATIGUE_POSTURES = ("leaning", "sitting")
FATIGUE_ON_S = 5.0              # leaning/sitting, or facing away + looking at nothing + still, for this long
FATIGUE_OFF_S = 3.0

# ---------------------------------------------------------------- bid (D10)
EDGE_MIN_DROP_M = 0.06          # edging in: outside the formation, distance at least this far below own outside baseline
SHORT_GLANCE_MAX_S = 1.0        # a robot glance this short or shorter is "short"
GLANCE_WINDOW_S = 10.0
GLANCE_MIN_SHORT = 2            # at least this many short robot glances in the window ...
GLANCE_RATE_FACTOR = 1.5        # ... and a glance rate at least this many times own baseline rate
BID_OFF_S = 5.0                 # a bid stays active this long after its last cue

# ---------------------------------------------------------------- barrier (D10). Judged absolutely, not vs a baseline.
BARRIER_USE_LOS_ROBOT = False   # if True, a blocked view of the robot alone is a barrier (see HANDOFF §8, open question)
BARRIER_ON_S = 2.0              # position barrier (view of exhibit blocked / outside formation) must hold this long
BARRIER_OFF_S = 2.0
TALKED_OVER_OFF_S = 1.0

# ---------------------------------------------------------------- excluded (D10)
# An exclusion episode starts when a bid and a barrier overlap, and ends when no barrier is left
# (the visitor stopping bidding does not resolve it).
EXCLUDED_ON_S = 0.0
