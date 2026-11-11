"""Scripted mock scenarios. Each one exercises specific signals with known ground truth."""
import math

from .mock import Scenario, VisitorScript, Window, Speech


def _arc(angle_deg, r):
    a = math.radians(angle_deg)
    return round(r * math.cos(a), 3), round(r * math.sin(a), 3)


def s1_one_stop() -> Scenario:
    """One 150 s stop at the figurehead with six visitors.

    v1  adult    lingers on the carving and steps closer          -> linger, approach
    v2  child    stands behind their parent (v3): view blocked, outside the
                 formation; edges inward, glances at the robot, gets talked over,
                 then moves round to the side at ~84 s              -> bid + barrier = excluded
    v3  adult    the child's parent; asks four questions, points  -> point_ask x4 (dominance)
    v4  adult    quiet, calm, attending                            -> reserved: expect no events
    v5  adult    drifts toward the ship model                      -> drift
    v6  adult    v5's companion; leans, faces away (tired)         -> fatigue
    """
    v1_out, v1_in = _arc(-130, 2.2), _arc(-130, 1.5)
    v2_behind, v2_edge, v2_side = _arc(-95, 3.0), _arc(-95, 2.75), _arc(-80, 2.0)
    v5_start = _arc(-35, 2.2)

    visitors = [
        VisitorScript(
            "v1", "adult", 1.78, "c1",
            path=[(0, *v1_out), (70, *v1_out), (80, *v1_in), (115, *v1_in), (125, *_arc(-130, 2.0))],
            windows=[Window(70, 115, attention="feature:figurehead.carving")],
            responded_to_steer_invite=True,
        ),
        VisitorScript(
            "v2", "child", 1.20, "c2", age_conf=0.85,
            path=[(0, *v2_behind), (50, *v2_behind), (60, *v2_edge), (82, *v2_edge), (86, *v2_side)],
            windows=[Window(50, 80, gaze_mix={"robot": 0.55, "exhibit": 0.35, "companion": 0.10},
                            robot_glance_s=(0.3, 0.8)),
                     Window(72, 73.5, attention="robot")],
            speech=[Speech(72, 73.5, "Is that a lady?", True)],
        ),
        VisitorScript(
            "v3", "adult", 1.80, "c2",
            path=[(0, *_arc(-95, 2.2))],
            windows=[Window(100, 102.5, attention="feature:figurehead.paint", pointing_at="figurehead.paint"),
                     Window(112, 114, attention="robot"),
                     Window(125, 127, attention="robot"),
                     Window(138, 140, attention="robot")],
            speech=[Speech(100, 102.5, "Is that the original paint?", True),
                    Speech(112, 114, "How old is it?", True),
                    Speech(125, 127, "Who carved it?", True),
                    Speech(138, 140, "Was it on a real ship?", True)],
            responded_to_steer_invite=True,
        ),
        VisitorScript(
            "v4", "adult", 1.68, "c3",
            path=[(0, *_arc(-60, 2.3))],
            gaze_mix={"exhibit": 0.8, "robot": 0.2},
        ),
        VisitorScript(
            "v5", "adult", 1.72, "c4",
            path=[(0, *v5_start), (100, *v5_start), (115, 2.8, -1.4)],
            windows=[Window(100, 140, attention="exhibit:ship_model", body_target="ship_model")],
        ),
        VisitorScript(
            "v6", "adult", 1.65, "c4",
            path=[(0, *_arc(-20, 2.3))],
            windows=[Window(110, 150, attention="none", body_target="away", posture="leaning")],
        ),
    ]

    robot_speech = [Speech(10, 30), Speech(31, 50), Speech(51, 70), Speech(71, 90),   # core
                    Speech(95, 99, "What do you notice about her face?", True),     # open space
                    Speech(103, 110), Speech(115, 120), Speech(128, 134), Speech(141, 146)]  # answers

    labels = [
        {"kind": "approach", "track_id": "v1", "t0": 70, "t1": 80, "target": "figurehead"},
        {"kind": "linger", "track_id": "v1", "t0": 70, "t1": 115, "target": "figurehead.carving"},
        {"kind": "barrier", "track_id": "v2", "t0": 0, "t1": 84, "why": "view blocked + outside formation"},
        {"kind": "barrier", "track_id": "v2", "t0": 72, "t1": 73.5, "why": "talked over"},
        {"kind": "bid", "track_id": "v2", "t0": 50, "t1": 80},
        {"kind": "excluded", "track_id": "v2", "t0": 50, "t1": 80},
        {"kind": "point_ask", "track_id": "v2", "t0": 72, "t1": 73.5, "why": "question, talked over"},
        {"kind": "point_ask", "track_id": "v3", "t0": 100, "t1": 102.5, "target": "figurehead.paint"},
        {"kind": "point_ask", "track_id": "v3", "t0": 112, "t1": 114},
        {"kind": "point_ask", "track_id": "v3", "t0": 125, "t1": 127},
        {"kind": "point_ask", "track_id": "v3", "t0": 138, "t1": 140},
        {"kind": "expect_no_events", "track_id": "v4", "t0": 0, "t1": 150},
        {"kind": "drift", "track_id": "v5", "t0": 100, "t1": 140, "target": "ship_model"},
        {"kind": "barrier", "track_id": "v5", "t0": 140, "t1": 150, "why": "outside formation after the drift"},
        {"kind": "fatigue", "track_id": "v6", "t0": 110, "t1": 150},
    ]

    return Scenario("s1_one_stop", stop="figurehead", duration_s=150, robot_pose=(-2.2, -0.3),
                    robot_speech=robot_speech, visitors=visitors, labels=labels)


def s1_closed():
    """s1 for the closed-loop sim. Same people and scripted behaviour, except:
    v2 edges in at 50-60 s but only gets into the formation if the robot opens it (join_xy);
    all questions are reactive: the child interrupts the robot's next utterance after 70 s,
    the parent waits for gaps. Hidden interests decide who takes up which addition."""
    from .sim import SimSpec, SimSpeech
    scn = s1_one_stop()
    scn.name = "s1_closed"
    v = {x.track_id: x for x in scn.visitors}
    v2_behind, v2_edge, v2_side = _arc(-95, 3.0), _arc(-95, 2.75), _arc(-80, 2.0)
    v["v2"].path = [(0, *v2_behind), (50, *v2_behind), (60, *v2_edge)]
    v["v2"].windows = [w for w in v["v2"].windows if w.attention != "robot"]
    v["v3"].windows = [w for w in v["v3"].windows if w.attention != "robot"]
    scn.labels = []   # closed-loop timing depends on the robot; tests check behaviour instead
    return SimSpec(
        scn,
        interests={"v1": {("feature_interest", "figurehead.carving"), ("depth", "figurehead")},
                   "v2": {("feature_interest", "figurehead.carving")},
                   "v3": {("feature_interest", "figurehead.paint")},
                   "v4": {("feature_interest", "figurehead.paint")},
                   "v5": {("exhibit_interest", "ship_model")},
                   "v6": set()},
        join_xy={"v2": v2_side},
        speech={"v2": [SimSpeech(70, 1.5, "Is that a lady?", mode="interrupt")],
                "v3": [SimSpeech(100, 2.5, "Is that the original paint?"),
                       SimSpeech(112, 2.0, "How old is it?"),
                       SimSpeech(125, 2.0, "Who carved it?"),
                       SimSpeech(138, 2.0, "Was it on a real ship?")]},
    )


ALL = {"s1_one_stop": s1_one_stop}
SIM = {"s1_closed": s1_closed}
