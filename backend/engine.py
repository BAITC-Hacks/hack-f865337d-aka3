"""Provisional rules from user request; must be reconciled with dataset README."""
from .models import (AIContext, Dataset, Event, Facts, Profile, Recommendation,
                     Recommendations, SkillChange, SkillGap, Target)


def apply_effects(skills: dict[str, float], event: Event) -> dict[str, float]:
    result = dict(skills)
    for effect in event.effects:
        current = result.get(effect.skill_id, 0)
        result[effect.skill_id] = max(current, min(current + effect.gain, effect.max_level))
    return result


def progress(skills, requirements):
    total = sum(requirements.values())
    return round(100 * sum(min(skills.get(k, 0), v) for k, v in requirements.items()) / total, 2) if total else 100.0


def profile(data: Dataset, employee_id: str) -> Profile:
    employee = next(e for e in data.employees if e.employee_id == employee_id)
    events = {e.event_id: e for e in data.events}
    history = sorted((h for h in data.history if h.employee_id == employee_id
                      and h.date <= data.simulation_date), key=lambda h: h.date)
    skills = dict(employee.skills)
    applied = []
    for h in history:
        if h.status == 'completed' and h.date > employee.last_review_date:
            skills = apply_effects(skills, events[h.event_id])
            applied.append(h.participation_id)
    target = employee.target
    if target is None and employee.grade in data.grade_order:
        later = data.grade_order[data.grade_order.index(employee.grade) + 1:]
        goal = next((g for grade in later for g in data.goals
                     if g.role == employee.role and g.grade == grade), None)
        if goal:
            target = Target(role=goal.role, grade=goal.grade, source='system')
    goal = next((g for g in data.goals if target and g.role == target.role and g.grade == target.grade), None)
    requirements = goal.requirements if goal else {}
    critical = goal.critical_skills if goal else []
    gaps = [SkillGap(skill_id=k, current=skills.get(k, 0), required=v,
                     gap=max(0, v-skills.get(k, 0)), critical=k in critical)
            for k, v in sorted(requirements.items()) if skills.get(k, 0) < v]
    return Profile(employee_id=employee.employee_id, name=employee.name, role=employee.role,
                   grade=employee.grade, as_of=data.simulation_date, last_review_date=employee.last_review_date,
                   target=target, target_status=('selection_required' if not target else
                   'suggested' if target.source == 'system' else 'selected'), skills=skills,
                   target_requirements=requirements, gaps=gaps, critical_skills=critical,
                   progress_percent=progress(skills, requirements) if goal else None,
                   completed_event_ids=sorted({h.event_id for h in history if h.status == 'completed'}),
                   applied_participation_ids=applied,
                   history=[dict(**h.model_dump(), title=events[h.event_id].title,
                                 repeatable=events[h.event_id].repeatable) for h in history],
                   available_goals=data.goals,
                   skill_names={s.skill_id: s.name for s in data.skill_catalog},
                   completion_available=employee.last_review_date < data.simulation_date,
                   completion_message=None if employee.last_review_date < data.simulation_date else
                   'Демовыполнение недоступно: дата симуляции должна быть позже последней оценки.')


def eligible(data: Dataset, p: Profile, event: Event, allow_started: bool = False) -> bool:
    history = [h for h in data.history if h.employee_id == p.employee_id and h.date <= data.simulation_date]
    if event.mandatory:
        return False
    if not allow_started and any(h.event_id == event.event_id and h.status == 'in_progress' for h in history):
        return False
    if event.event_id in p.completed_event_ids and not event.repeatable:
        return False
    if (event.roles and p.role not in event.roles) or (event.grades and p.grade not in event.grades):
        return False
    if any(p.skills.get(k, 0) < v for k, v in event.prerequisites.items()):
        return False
    return allow_started or event.format == 'self_paced' or any(d >= data.simulation_date for d in event.available_session_dates)


def recommendations(data: Dataset, p: Profile) -> Recommendations:
    def result(items=None, reason=None, message=None):
        return Recommendations(employee_id=p.employee_id, as_of=data.simulation_date,
                               items=items or [], empty_reason=reason, message=message)
    if p.target is None:
        return result(reason='target_required', message='Выберите карьерную цель.')
    if not p.gaps:
        return result(reason='target_covered', message='Требования цели уже покрыты; можно выбрать новую цель.')
    history = [h for h in data.history if h.employee_id == p.employee_id and h.date <= data.simulation_date]
    events = {e.event_id: e for e in data.events}
    items = []
    for event in data.events:
        if not eligible(data, p, event):
            continue
        sessions = sorted(d for d in event.available_session_dates if d >= data.simulation_date)
        after = apply_effects(p.skills, event)
        addressed = [g for g in p.gaps if after.get(g.skill_id, 0) > g.current]
        reduction = sum((2 if g.critical else 1) * min(g.gap, after[g.skill_id]-g.current) for g in addressed)
        if reduction <= 0:
            continue
        developed = {effect.skill_id for effect in event.effects}
        similar = [h for h in history if developed & {e.skill_id for e in events[h.event_id].effects}]
        completed = sum(h.status == 'completed' for h in similar)
        missed = sum(h.status in ('declined', 'dropped', 'no_show') for h in similar)
        history_factor = 0.1 * (completed-missed) / max(1, completed+missed)
        facts = Facts(current_role=p.role, current_grade=p.grade, target=p.target,
                      addressed_gaps=addressed, similar_completed=completed, similar_missed=missed,
                      weighted_gap_reduction=reduction, history_factor=history_factor,
                      score=round(reduction*(1+history_factor), 6),
                      eligible_session_date=sessions[0] if event.format != 'self_paced' else None)
        changes = [SkillChange(skill_id=k, before=p.skills.get(k, 0), after=v, delta=v-p.skills.get(k, 0))
                   for k, v in sorted(after.items()) if v > p.skills.get(k, 0)]
        detail = '; '.join(f'{p.skill_names.get(g.skill_id, g.skill_id)}: {g.current:g} → {after[g.skill_id]:g}, требуется {g.required:g}' for g in addressed)
        explanation = (f'Для перехода из {p.role} / {p.grade} к {p.target.role} / {p.target.grade}: {detail}. '
                       f'Похожие активности: завершено {completed}, отказов и пропусков {missed}. '
                       'Эффект рассчитан по правилам навыков; повышение не гарантируется.')
        items.append(Recommendation(event_id=event.event_id, title=event.title, facts=facts,
                    repeatable=event.repeatable, format=event.format,
                    description=event.description, duration_hours=event.duration_hours, original_format=event.original_format,
                    expected_skill_changes=changes, progress_before=p.progress_percent,
                    progress_after=progress(after, p.target_requirements),
                    explanation=explanation, explanation_source='fallback'))
    items.sort(key=lambda item: (-item.facts.score, item.event_id))
    return result(items[:3]) if items else result(reason='no_eligible_activities', message='Нет доступных активностей, сокращающих разрывы до цели.')


def ai_context(data: Dataset, employee_id: str) -> AIContext:
    p = profile(data, employee_id)
    return AIContext(profile=p, recommendations=recommendations(data, p))
