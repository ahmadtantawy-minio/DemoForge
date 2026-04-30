# Bugfix: I/O Stall Not Differentiating Between Scenarios

## Problem

When switching from `file-g4` to `minio-g4`, the I/O stall metric on the GPU utilization bar does not visibly change. Both scenarios show roughly the same stall percentage despite the G4 restore ticks being dramatically different (50 vs 12).

## Root cause

Two parameters in the GPU tracker's stall fraction calculation cause all scenarios to converge to the same output:

**1. Hard cap of 0.3 is too low.**
A file-g4 restore registers 50 ticks. `50 * 0.012 = 0.6` → capped to 0.3.
A minio-g4 restore registers 12 ticks. `12 * 0.012 = 0.144`.
Looks different in isolation, but at 100 users with frequent restores, minio-g4's `remaining_stall_ticks` accumulates to 25+ within a few ticks → `25 * 0.012 = 0.3` → hits the same cap.
Both scenarios pin at 0.3. Indistinguishable.

**2. Decay rate of 1 tick per tick is too slow.**
`remaining_stall_ticks` decrements by 1 each tick. A 50-tick file stall takes 50 ticks to decay. But the next G4 restore arrives within ~5 ticks at 100 users. The backlog never clears. For minio-g4 (12-tick stalls), the same problem occurs — 12-tick stall, next restore in ~5 ticks, backlog accumulates. Both scenarios reach a permanently elevated plateau.

## What should happen

With 2 GPUs, TP=2, one model replica — there is no cross-GPU migration. The only path that differs between scenarios is **G4 restore** (idle session returning, KV blocks pulled from shared storage back to G1).

- G2→G1: 1 tick — same in both scenarios
- G3→G1: 4 ticks — same in both scenarios
- **G4→G1: 50 ticks (file-g4) vs 12 ticks (minio-g4)** — this is the ONLY difference

This single difference should produce a visible, dramatic change in the I/O stall bar when switching scenarios.

## Fix

### Change 1: Raise the stall fraction cap

**File:** The GPU tracker class that contains `register_io_stall()` and the per-tick stall fraction calculation (likely in `engine.py`).

**Find:**
```python
stall_frac = min(0.3, remaining_stall_ticks * 0.012)
```

**Replace with:**
```python
stall_frac = min(0.85, remaining_stall_ticks * 0.018)
```

**Why:** The GPU genuinely can be 85% stalled. In the file-g4 scenario with 500ms+ file reads, the GPU is mostly waiting. A 30% cap hides this reality. The coefficient increase from 0.012 to 0.018 ensures that shorter stalls (minio-g4, 12 ticks) still produce a visible but moderate stall fraction rather than being invisible.

### Change 2: Increase decay rate

**Find:**
```python
remaining_stall_ticks -= 1
```
or equivalent decrement logic.

**Replace with:**
```python
remaining_stall_ticks = max(0, remaining_stall_ticks - 3)
```

**Why:** Faster decay is the key differentiator. With decay of 3 per tick:

- file-g4 registers 50 ticks, decays in ~17 ticks, but next restore arrives in ~5 ticks. Backlog stays at 30-60. `stall_frac` oscillates 0.54–0.85.
- minio-g4 registers 12 ticks, decays in ~4 ticks. Next restore in ~5 ticks. Backlog stays at 5-15. `stall_frac` oscillates 0.09–0.27.

The backlog clears fast enough for short stalls (minio-g4) but not fast enough for long stalls (file-g4). That's the differentiation.

### Change 3: Raise the remaining_stall_ticks cap

**Find** the cap on `remaining_stall_ticks` (currently 80):
```python
remaining_stall_ticks = min(80, ...)
```
or wherever it is capped when `register_io_stall()` adds ticks.

**Replace with:**
```python
remaining_stall_ticks = min(200, ...)
```

**Why:** With file-g4 registering 50-tick stalls every few ticks, an 80-tick cap prevents the backlog from reflecting reality. The backlog needs room to grow in the file scenario so the high stall fraction is sustained, not artificially flattened.

## Expected result after fix

At 100 users, 64K context, steady state:

```
Scenario      remaining_stall_ticks    stall_frac        Visible as
─────────     ─────────────────────    ──────────        ──────────
file-g4       30–60 (never clears)     0.54–0.85         Large amber I/O stall bar
minio-g4      5–15 (mostly clears)     0.09–0.27         Moderate, clearly smaller
```

The FA switches from file-g4 to minio-g4 and within 15-20 seconds the I/O stall bar visibly shrinks from dominating the GPU utilization to a moderate slice. That's the "aha" moment.

## What NOT to change

- Do not change `register_io_stall(ticks)` call sites or the tick values passed to it. The scenario parameters (50 for file-g4, 12 for minio-g4) are correct and benchmark-grounded.
- Do not change the G2→G1 or G3→G1 promotion tick values. These are the same in both scenarios.
- Do not change session lifecycle probabilities, eviction thresholds, or request generation. The problem is purely in how stall ticks convert to the displayed fraction.
- Do not change the recomputation path. Recompute is correctly excluded from I/O stall.

## Verification

1. Start simulation with `file-g4`, 100 users, 64K context, 1x speed
2. Wait 30 seconds for steady state
3. Observe GPU utilization bar — I/O stall should be 50-80% (large amber segment)
4. Switch to `minio-g4` (do not reset simulation)
5. Wait 15-20 seconds for the stall backlog to decay
6. Observe GPU utilization bar — I/O stall should drop to 10-25%
7. The difference should be immediately obvious without reading numbers

If the difference is not visible within 20 seconds of switching, check:
- Are G4 restores actually firing? Check the event stream for G4 restore events.
- Is `remaining_stall_ticks` actually changing? Log it.
- Is the UI polling the updated `stall_frac` value?
