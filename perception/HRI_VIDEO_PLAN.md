# HRI video: 1-minute system scenario (plan)

Budget: the video limit is 3 min; about 1 min of it shows the system running, with a voice-over. Source: the encounter replay
(`s2_multi_stop`, seed 1, no tour questions), the same run as `media/encounter_tour_s2_seed1.mp4`. Times below are sim
times from that run (t = 0 is the start of the tour). The system diagram (on by default; `--no-diagram` turns it off) shows which stage is working.

## Shots (about 57 s)

| # | Sim time | Speed | Length | What is on screen | Diagram stage lit |
|---|---|---|---|---|---|
| 1 | −113.6 → −95.4 | 3× | 6 s | Six visitors arrive one by one; IDs v1–v6 appear; dashed rings form around companions (v2+v3, v5+v6) | Detect + track, Child/adult band, Companion groups |
| 2 | −95.4 → −88.5 | 1× | 7 s | Groups settled; the robot turns to everyone: "Hello, everyone, and welcome!…" | Engage + gather → Group talk |
| 3 | −36.5 → −23.0 | 1.5× | 9 s | "Do you have a favourite exhibit…?" v3: "I like the navigator's compass." The guess appears in v3's profile (orange chip) | Group talk, Profile guesses |
| 4 | −18.7 → 0 | 3× | 6 s | "Let's head over to the ship's figurehead." The robot walks; the group follows; handoff at t = 0 | Lead to stop 1 → Handoff |
| 5 | 57 → 61, 75 → 81, 94 → 97 | 1× | 13 s | v5 keeps looking at the ship model (drift) → the robot offers the ship-model preview → v5 looks at it: guess confirmed | Sense signals → Choose addition → Speak → Uptake window → Profile update |
| 6 | 158 → 166 | 1× | 8 s | The child (v2) is behind and trying to join: the robot opens the formation | Sense signals → Floor + formation |
| 7 | 251 → 261 | 1.5× | 7 s | "Next we could see the navigator's compass or the sailor's sea chest." The group turns; the robot reads it: sea chest | Plan + move |

## Voice-over draft (about 140 words, ~2.4 words/s)

1. "Visitors arrive. Our perception gives each person an ID, estimates child or adult, and groups companions by who arrives and moves together."
2. "Once every group is settled, the robot greets everyone at once. It always speaks to the whole group."
3. "A little small talk builds a first profile: v3 mentions the compass, and that becomes a guess, not a fact."
4. "The robot leads the group to the first exhibit and hands its first impression to the tour."
5. "During the tour it watches behaviour. v5 keeps looking at the ship model, so the robot offers a link to it; v5 looks, and the guess is confirmed."
6. "When the child is stuck behind the group, the robot opens the formation for them."
7. "At a choice of exhibits, it offers two and follows where the group turns."

## Things to settle before rendering

- **Renderer:** `video.py` renders the whole run; cutting these 7 shots needs a segment option (`--shots`) or an editor. Not built yet.
- **Sound:** mute the gTTS voices under the voice-over, or keep them quietly (−18 dB) in shots 2, 3 and 7 where the words matter.
- **Captions:** off (the voice-over explains); the diagram stays on.
- **Do not claim:** that v3's compass guess leads to the compass being offered in shot 7. The choice is offered because the two
  options tie at 0 (pending guesses don't count there), and the guess is never tested in this run (see README).
- **D4:** the child/adult band appears on screen (internal estimate, never spoken). Joey to confirm that is fine for a public video.
- **Simulation:** say it on screen ("simulated visitors; real perception and decision code").
