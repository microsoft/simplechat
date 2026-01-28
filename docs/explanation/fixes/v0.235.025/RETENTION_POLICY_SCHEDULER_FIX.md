# Retention Policy Scheduler Fix

## Issue Description

The automated retention policy scheduler was not executing at the scheduled time. Users would see the "Next Scheduled Execution" time pass without the policy running.

## Root Cause Analysis

The background scheduler in `app.py` had multiple issues preventing reliable execution:

1. **Hour-matching approach was unreliable**: The scheduler only ran if the check happened exactly during the execution hour (e.g., 2 AM). With 1-hour sleep intervals, it could easily miss the entire window if the thread's check cycle didn't align with the execution hour.

2. **Check interval too long**: Checking every hour (3600 seconds) meant poor responsiveness and high probability of missing the scheduled time.

3. **No use of stored next_run timestamp**: The code ignored the `retention_policy_next_run` setting that was being saved, instead relying solely on hour matching.

4. **No catch-up logic**: If the scheduled time passed while the app was down or during a sleep cycle, there was no mechanism to run the missed execution.

## Files Modified

| File | Changes |
|------|---------|
| [app.py](../../../application/single_app/app.py) | Rewrote `check_retention_policy()` background task |
| [config.py](../../../application/single_app/config.py) | Version bump to 0.235.025 |

## Technical Details

### Before (Problematic Code)
```python
# Check if we're in the execution hour
if current_time.hour == execution_hour:
    # Check if we haven't run today yet
    last_run = settings.get('retention_policy_last_run')
    # ... run if last_run > 23 hours ago
    
# Check every hour
time.sleep(3600)
```

### After (Fixed Code)
```python
# Check if next scheduled run time has passed
next_run = settings.get('retention_policy_next_run')
if next_run:
    next_run_dt = datetime.fromisoformat(next_run)
    # Run if we've passed the scheduled time
    if current_time >= next_run_dt:
        should_run = True

# Check every 5 minutes for more responsive scheduling
time.sleep(300)
```

### Key Improvements

1. **Uses `retention_policy_next_run` timestamp**: Compares current time against the stored next scheduled execution time. If current time >= scheduled time, it runs.

2. **Reduced check interval**: Changed from 1 hour to 5 minutes (300 seconds) for more responsive scheduling.

3. **Better fallback logic**: If `next_run` can't be parsed, falls back to checking `last_run` with a 23-hour threshold.

4. **Immediate execution for missed schedules**: If the scheduled time has already passed, the policy runs on the next check cycle.

5. **Runs immediately if never run before**: If there's no `last_run` or `next_run`, it will execute on the first check.

## Testing Approach

1. Enable retention policy for personal workspaces
2. Set execution hour to current hour or a past hour
3. Restart the application
4. Verify the retention policy executes within 5 minutes
5. Confirm `Last Execution` and `Next Scheduled Execution` timestamps update correctly

## Impact Analysis

- **Positive**: Retention policies now execute reliably at scheduled times
- **Positive**: Missed executions are caught up on next app start or check cycle
- **Consideration**: Slightly higher CPU usage due to 5-minute checks vs 1-hour checks (negligible impact)

## Version Information

- **Fixed in version**: 0.235.025
- **Issue introduced**: Original implementation

## Related Changes

- [RETENTION_POLICY_DOCUMENT_DELETION_FIX.md](RETENTION_POLICY_DOCUMENT_DELETION_FIX.md) - Related retention policy fixes in same version
