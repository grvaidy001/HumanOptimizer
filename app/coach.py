"""Rule-based coaching engine for HumanOptimizer.

Designed to be replaceable with Claude/OpenAI in the future.
The generate_daily_plan function is the main entry point.
"""

from app.models import CoachingInput, CoachingPlan

# Communication task suggestions
COMMUNICATION_TASKS = [
    "Explain a complex concept in under 3 minutes (record yourself)",
    "Practice introducing yourself to a stranger (elevator pitch)",
    "Summarize today's workout plan as if teaching someone",
    "Record a 2-min voice memo reviewing your day",
    "Practice active listening: replay a conversation and note what you missed",
    "Explain your fasting protocol to an imaginary friend in simple terms",
    "Describe your biggest win this week in 60 seconds",
    "Practice giving constructive feedback on something you read today",
    "Record yourself explaining WHY you're doing 75 Hard",
    "Tell a story about a challenge you overcame — keep it under 2 minutes",
]


def _get_status(recovery: int | None, strain: int | None, sleep_score: int | None, hrv: int | None) -> str:
    """Determine overall status based on recovery signals."""
    scores = []
    if recovery is not None:
        if recovery >= 67:
            scores.append(2)
        elif recovery >= 34:
            scores.append(1)
        else:
            scores.append(0)

    if sleep_score is not None:
        if sleep_score >= 70:
            scores.append(2)
        elif sleep_score >= 50:
            scores.append(1)
        else:
            scores.append(0)

    if hrv is not None:
        if hrv >= 50:
            scores.append(2)
        elif hrv >= 30:
            scores.append(1)
        else:
            scores.append(0)

    if strain is not None:
        # High strain = lower readiness
        if strain <= 10:
            scores.append(2)
        elif strain <= 15:
            scores.append(1)
        else:
            scores.append(0)

    if not scores:
        return "GREEN"  # No data, default to go

    avg = sum(scores) / len(scores)
    if avg >= 1.5:
        return "GREEN"
    elif avg >= 0.75:
        return "YELLOW"
    else:
        return "RED"


def _get_communication_task(day_of_cycle: int) -> str:
    """Rotate through communication tasks based on cycle day."""
    return COMMUNICATION_TASKS[day_of_cycle % len(COMMUNICATION_TASKS)]


def generate_daily_plan(input_data: CoachingInput) -> CoachingPlan:
    """Generate a daily execution plan based on recovery and context.

    This function is the main extension point for future AI integration.
    Replace this with a call to Claude/OpenAI for personalized coaching.
    """
    status = _get_status(input_data.recovery, input_data.strain, input_data.sleep_score, input_data.hrv)

    # Fasting day adjustments
    is_fasting = input_data.fasting_day
    is_refeed = input_data.fasting_cycle_day == 4

    # Base recommendations by status
    if status == "GREEN":
        training = "push"
        sled = "full volume"
        walk = "45-60 min"
        warning = ""
    elif status == "YELLOW":
        training = "moderate"
        sled = "reduce volume by 25%"
        walk = "45 min"
        warning = "Fatigue building — stay disciplined but listen to your body."
    else:  # RED
        training = "recover"
        sled = "light or skip"
        walk = "30-45 min easy pace"
        warning = "Recovery needed. Focus on movement quality, not intensity."

    # Fasting adjustments
    if is_fasting and status != "RED":
        if input_data.fasting_cycle_day == 1:
            # Day 1 fasting — still have glycogen
            pass  # No change needed
        elif input_data.fasting_cycle_day == 2:
            training = "moderate" if training == "push" else training
            sled = "reduce volume by 25%" if sled == "full volume" else sled
            warning = (warning + " Day 2 fast — conserve energy for key lifts.").strip()
        elif input_data.fasting_cycle_day == 3:
            training = "moderate" if training == "push" else "recover" if training == "moderate" else training
            sled = "light or skip"
            walk = "30-45 min"
            warning = (warning + " Day 3 fast — deep ketosis. Prioritize completion over intensity.").strip()
    elif is_refeed:
        if status != "RED":
            training = "push"
            sled = "full volume — refeed energy available"
            warning = (warning + " Refeed day — use the fuel. Hit it hard.").strip()

    # Day type adjustments
    if input_data.day_type == "Recovery":
        training = "recover"
        sled = "skip or very light"
        walk = "30-45 min easy"
        if not warning:
            warning = "Recovery day — active recovery only."

    # Previous result consideration
    if input_data.previous_result == "LOSS" and status == "GREEN":
        warning = (warning + " Yesterday was a LOSS. Today is redemption. Execute all 5.").strip()

    communication_task = _get_communication_task(input_data.fasting_cycle_day)

    return CoachingPlan(
        status=status,
        training=training,
        sled=sled,
        walk=walk,
        communication_task=communication_task,
        warning=warning,
    )
