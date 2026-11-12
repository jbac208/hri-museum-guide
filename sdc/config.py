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

# ---------------------------------------------------------------- profile store (block 4)
# Which event creates which layer (Perception & decision loop §2). Fatigue/bid/barrier/excluded create none.
LAYER_FROM_EVENT = {
    "linger": "feature_interest",      # target: the feature
    "approach": "depth",               # target: the exhibit
    "drift": "exhibit_interest",       # target: the other exhibit
    "point_ask": "feature_interest",   # confirmed at once; exhibit_interest on the current stop if no feature
}
LAYER_EVENT_CONF = {"linger": 0.5, "approach": 0.4, "drift": 0.5}  # starting confidence of a pending layer
SEED_LAYER_CONF = 0.3           # pending layers handed over in the start impression
# repeated evidence: conf <- 1 - (1 - conf) * (1 - event_conf)   (independent-evidence combination)
PENDING_WEIGHT = 0.5            # a pending layer counts PENDING_WEIGHT * confidence toward s_i(a); confirmed counts 1
LAMBDA_DOMINANCE = 0.5          # D8: w_i = 1 / (1 + LAMBDA_DOMINANCE * k_i)
POINT_ASK_REOPENS_RESCINDED = True  # an explicit question re-confirms a rescinded layer (the visitor asked; robot isn't pushing)

# ---------------------------------------------------------------- content (block 6)
TTS_WORDS_PER_S = 2.5           # speech duration estimate for scripts and additions

# ---------------------------------------------------------------- decision layer (block 5)
# stop controller
ARRANGE_S = 5.0                 # arrange phase before the core starts
SEGMENT_GAP_S = 0.8             # breath between core segments
OPEN_WAIT_S = 3.0               # wait time before the open question (D2)
GAZE_SHIFT_S = 3.0              # gaze balancing: move gaze to the least-looked-at visitor this often (D5)
ACK_GAZE_S = 1.0                # nonverbal acknowledgement before speaking (D7)
STOP_END_MARGIN_S = 2.0         # don't start anything that would run past the stop's end minus this
# exclusion handler (§4), top priority
PAUSE_FLOOR_S = 3.0             # talked over: stop speaking and hold the floor open this long
EXCLUSION_RECHECK_S = 6.0       # position barrier: if still excluded this long after turning, step back once
STEP_BACK_M = 0.5               # widen the formation by stepping back from the exhibit
MAX_REPOSITIONS_PER_STOP = 1    # §3.1: reposition at most once per stop
# addition selector (§5, D8)
ADDITION_THRESHOLD = 0.15       # deliver only if score(a) = Σ w_i·s_i(a) reaches this
MAX_ADDITIONS_PER_STOP = 2      # P11
# uptake monitor (D6)
UPTAKE_WINDOW_S = 10.0          # after the addition ends
UPTAKE_LOOK_S = 3.0             # one continuous look at the addition's target of at least this long ...
UPTAKE_DWELL_FACTOR = 2.0       # ... and at least this many times the visitor's own mean dwell is uptake
UPTAKE_LOOK_GAP_S = 0.3         # glances away shorter than this don't break a look
UPTAKE_STEP_M = 0.2             # stepping this much closer to the addition's exhibit is uptake
UPTAKE_SETTLE_SPEED_MPS = 0.04  # ... measured from where they stand once a move already under way slows below this
CREDIT_PER_ACTED_SIGNAL = 1.0   # k_i grows by this when the robot visibly acts on i's signal (answer, confirmed layer)
# between-stop planner (§6)
PACE_FATIGUE_SHARE = 0.3        # slow down if at least this share of the group showed fatigue
DEPTH_RAISE_SHARE = 0.5         # raise default depth if more than this share has a confirmed depth layer
NEXT_STOP_CLOSE = 0.1           # P12: offer a two-way choice if the top two next stops score within this

# ---------------------------------------------------------------- logging (block 8)
LOG_TRACK_HZ = 5                # tracks are logged at this rate (no video, ever)
STEERING_KINDS = ("linger", "approach", "drift", "point_ask")   # signals counted by steering uptake (D3)

# ---------------------------------------------------------------- transitions between stops (§4, §6)
BEHIND_MIN_M = 3.5              # falling behind: at least this far from the robot ...
BEHIND_MARGIN_M = 2.0           # ... and this much farther than the group's median distance to it
BEHIND_ON_S = 2.0
BEHIND_OFF_S = 2.0
ROBOT_STOP_OFFSET = (-2.2, -0.3)  # where the robot stands relative to an exhibit's centre
ROBOT_WALK_MPS = 0.7            # walking speed between stops
ROBOT_WALK_SLOW_MPS = 0.4       # after slow_down(): pace slower, or someone fell behind
ARRIVE_RADIUS_M = 3.5           # a visitor has arrived when this close to the next exhibit
WAIT_MAX_S = 45.0               # wait at most this long for everyone before starting the stop
CHOICE_WAIT_S = 6.0             # P12: after offering two options, read orientation/gaze for this long
CHOICE_FACING_RAD = 0.6         # facing an option = body within this angle of the bearing to it
