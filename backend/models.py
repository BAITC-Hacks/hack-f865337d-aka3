"""API v1 and internal normalized models; NOT the unverified starter-kit schema."""
from datetime import date
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Level = Annotated[float, Field(ge=0, le=5)]


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Target(Model):
    role: str
    grade: str
    source: Literal['employee', 'system']


class GoalDefinition(Model):
    role: str
    grade: str
    requirements: dict[str, Level]
    critical_skills: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def check_critical(self):
        if not set(self.critical_skills) <= self.requirements.keys():
            raise ValueError('Critical skills must have requirements')
        return self


class Employee(Model):
    employee_id: str
    name: str
    role: str
    grade: str
    last_review_date: date
    skills: dict[str, Level]
    target: Target | None = None


class Effect(Model):
    skill_id: str
    gain: Level
    max_level: Level


class Event(Model):
    event_id: str
    title: str
    category: str
    mandatory: bool
    repeatable: bool
    roles: list[str]
    grades: list[str]
    prerequisites: dict[str, Level]
    format: Literal['self_paced', 'scheduled']
    available_session_dates: list[date]
    effects: list[Effect]

    @model_validator(mode='after')
    def unique_effects(self):
        if len({x.skill_id for x in self.effects}) != len(self.effects):
            raise ValueError('Duplicate skill effects')
        return self


class Participation(Model):
    participation_id: str
    employee_id: str
    event_id: str
    status: Literal['completed', 'declined', 'dropped', 'no_show', 'in_progress']
    date: date


class Dataset(Model):
    simulation_date: date
    employees: list[Employee]
    events: list[Event]
    history: list[Participation]
    goals: list[GoalDefinition]
    grade_order: list[str]

    @model_validator(mode='after')
    def check_references(self):
        for collection, field in [(self.employees, 'employee_id'), (self.events, 'event_id'),
                                  (self.history, 'participation_id')]:
            ids = [getattr(x, field) for x in collection]
            if len(ids) != len(set(ids)):
                raise ValueError(f'Duplicate {field}')
        employees = {e.employee_id for e in self.employees}
        events = {e.event_id for e in self.events}
        if any(h.employee_id not in employees or h.event_id not in events for h in self.history):
            raise ValueError('History contains unknown employee/event')
        goals = [(g.role, g.grade) for g in self.goals]
        if len(goals) != len(set(goals)) or len(self.grade_order) != len(set(self.grade_order)):
            raise ValueError('Duplicate goal or grade')
        if any(e.last_review_date > self.simulation_date for e in self.employees):
            raise ValueError('Review date is after simulation date')
        if any(e.target and (e.target.role, e.target.grade) not in goals for e in self.employees):
            raise ValueError('Unknown target requirements')
        return self


class SkillGap(Model):
    skill_id: str
    current: Level
    required: Level
    gap: Level
    critical: bool


class Profile(Model):
    employee_id: str
    name: str
    role: str
    grade: str
    as_of: date
    last_review_date: date
    target: Target | None
    target_status: Literal['selected', 'suggested', 'selection_required']
    skills: dict[str, Level]
    target_requirements: dict[str, Level]
    gaps: list[SkillGap]
    critical_skills: list[str]
    progress_percent: float | None
    completed_event_ids: list[str]
    applied_participation_ids: list[str]
    history: list['HistoryItem'] = Field(default_factory=list)
    available_goals: list[GoalDefinition] = Field(default_factory=list)
    completion_available: bool = True
    completion_message: str | None = None


class SkillChange(Model):
    skill_id: str
    before: Level
    after: Level
    delta: Level


class Facts(Model):
    current_role: str
    current_grade: str
    target: Target
    addressed_gaps: list[SkillGap]
    similar_completed: int
    similar_missed: int
    weighted_gap_reduction: float
    history_factor: float
    score: float
    eligible_session_date: date | None


class Recommendation(Model):
    event_id: str
    title: str
    repeatable: bool = False
    format: Literal['self_paced', 'scheduled'] = 'self_paced'
    facts: Facts
    expected_skill_changes: list[SkillChange]
    progress_before: float
    progress_after: float
    explanation: str
    explanation_source: Literal['ai', 'fallback']


class Recommendations(Model):
    employee_id: str
    as_of: date
    items: list[Recommendation]
    empty_reason: Literal['target_required', 'target_covered', 'no_eligible_activities'] | None
    message: str | None


class AIContext(Model):
    contract_version: Literal['1.0'] = '1.0'
    profile: Profile
    recommendations: Recommendations


class AIExplanation(Model):
    event_id: str
    explanation: Annotated[str, Field(min_length=1, max_length=2000)]


class AIResponse(Model):
    contract_version: Literal['1.0'] = '1.0'
    explanations: list[AIExplanation]


class CompletionRequest(Model):
    participation_id: Annotated[str, Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_-]+$')] | None = None


class CompletionResponse(Model):
    status: Literal['completed', 'already_completed']
    participation_id: str
    profile: Profile
    recommendations: Recommendations


class HistoryItem(Participation):
    title: str
    repeatable: bool


class ImportRequest(Model):
    employees: list[Employee] = Field(min_length=1, max_length=1000)
    history: list[Participation] = Field(default_factory=list, max_length=10000)


class GoalRequest(Model):
    role: str
    grade: str


Profile.model_rebuild()
