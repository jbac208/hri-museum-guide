"""Policies for the baseline comparison (task 9, P14).

Each policy is a set of switches over the same decision layer, so a comparison isolates the design
choices, not implementation details. All three answer every question (basic guide behaviour) and
use the same perception, content, timing and measures.

  ours        the loop as designed: exclusion fixes (§4), balanced gaze (D5), additions scored by
              Σ w_i·s_i with dominance damping (D8), pending guesses count partly, ≤ 2 per stop (P11),
              uptake confirm/rescind (D6), next stop by confirmed interest (D1) with P12, floor on moves.
  one_size    one-size-fits-all tour (Burgard 1999): same core and the same additions in content order
              for every group; no individual adaptation, no exclusion fixes, gaze on the exhibit,
              fixed route, fixed pace, no waiting.
  engagement  engagement-maximising adaptation (Lin 2024): serves whoever signals most; no dominance
              damping (λ = 0), pending guesses count fully, up to 4 additions, gaze on the most engaged
              visitor, next stop by all guesses unweighted; no exclusion fixes, no floor on moves.
"""
from dataclasses import dataclass

from . import config as C


@dataclass(frozen=True)
class Policy:
    name: str
    handle_exclusion: bool = True            # §4 fixes: glance + turn, step back, pause for talked over
    gaze: str = "balanced"                   # balanced (D5) | exhibit | engaged
    additions: str = "scored"                # scored (§5) | fixed (content order, addressed to no one)
    lam: float = C.LAMBDA_DOMINANCE          # D8 damping; 0 = none
    pending_full: bool = False               # pending guesses count as much as confirmed ones
    max_additions: int = C.MAX_ADDITIONS_PER_STOP
    next_stop: str = "confirmed"             # confirmed (D1) | route (fixed order) | engagement (all guesses)
    two_way_choice: bool = True              # P12
    floor_on_moves: bool = True              # slow down for anyone falling behind, wait for everyone
    adapt_pace_depth: bool = True            # between-stop pace/depth from the group's behaviour


OURS = Policy("ours")
ONE_SIZE = Policy("one_size", handle_exclusion=False, gaze="exhibit", additions="fixed", lam=0.0,
                  next_stop="route", two_way_choice=False, floor_on_moves=False, adapt_pace_depth=False)
ENGAGEMENT = Policy("engagement", handle_exclusion=False, gaze="engaged", lam=0.0, pending_full=True,
                    max_additions=4, next_stop="engagement", two_way_choice=False, floor_on_moves=False)
ALL = {p.name: p for p in (OURS, ONE_SIZE, ENGAGEMENT)}
