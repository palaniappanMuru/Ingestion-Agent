"""Pydantic schema for what Claude extracts from a single CV.

This is the *extraction* shape — what the LLM returns. It is deliberately a bit
richer than the graph: it carries name-based cross-references (which skills an
accomplishment used, which project it happened in, which skills a course
taught) that the deduplication step turns into graph relationships.

Schema notes for structured outputs: only features supported by Claude
structured outputs are used (objects, arrays, strings, bools, enums). No
numeric/length constraints, no recursion.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SkillType = Literal["Mgmt", "Tech"]
ExpertiseLevel = Literal["Basic", "Intermediate", "Expert"]


class ExtractedSkill(BaseModel):
    name: str = Field(description="Canonical skill name, e.g. 'AWS', 'Kubernetes', 'Stakeholder Management'.")
    type: SkillType = Field(description="'Tech' for technical skills, 'Mgmt' for leadership/management skills.")
    expertise_level: ExpertiseLevel = Field(
        description="Inferred proficiency from the CV. Default to 'Intermediate' if unclear."
    )
    tags: list[str] = Field(default_factory=list, description="Short topical tags, e.g. ['cloud', 'devops'].")


class ExtractedCourse(BaseModel):
    name: str = Field(description="Course or certification name, e.g. 'AWS Certified Solutions Architect', 'TOGAF'.")
    is_certification: bool = Field(description="True if this is a certification (vs. a plain course/training).")
    provider: str = Field(default="", description="Issuing body or provider; empty string if not stated.")
    validity: str = Field(default="", description="Validity duration as free text, e.g. '3 years'; empty if not stated.")
    skills_learned: list[str] = Field(
        default_factory=list,
        description="Names of skills learned in this course (must match a skill name in the skills list).",
    )


class ExtractedProject(BaseModel):
    name: str = Field(description="Project, role, or engagement name.")
    company: str = Field(default="", description="Company/organization for the project.")
    start_date: str = Field(default="", description="Start date as written in the CV, e.g. 'Aug 2022'.")
    end_date: str = Field(default="", description="End date as written, e.g. 'Present'; empty if not stated.")


class ExtractedAccomplishment(BaseModel):
    text: str = Field(description="A single concrete accomplishment/achievement statement.")
    tags: list[str] = Field(default_factory=list, description="Short topical tags for the accomplishment.")
    quantitative_achievement: str = Field(
        default="",
        description="The measurable result if present, e.g. 'reduced turnaround by 50%'; empty otherwise.",
    )
    skills_used: list[str] = Field(
        default_factory=list,
        description="Names of skills demonstrated (must match a skill name in the skills list).",
    )
    project_name: str = Field(
        default="",
        description="Name of the project this accomplishment happened in (must match a project name); empty if none.",
    )


class ExtractedCV(BaseModel):
    """The full structured extraction for one CV."""

    candidate_name: str = Field(description="Full name of the candidate.")
    email: str = Field(default="", description="Email address if present.")
    phone: str = Field(default="", description="Phone number if present.")
    location: str = Field(default="", description="Location/city if present.")
    headline: str = Field(default="", description="Professional headline / title line.")

    skills: list[ExtractedSkill] = Field(default_factory=list)
    courses: list[ExtractedCourse] = Field(default_factory=list)
    projects: list[ExtractedProject] = Field(default_factory=list)
    accomplishments: list[ExtractedAccomplishment] = Field(default_factory=list)
