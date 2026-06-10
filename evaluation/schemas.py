from pydantic import BaseModel, Field


class DimensionScore(BaseModel):
    score: int = Field(..., ge=1, le=5, description="1=fail, 5=excellent")
    passed: bool = Field(..., description="True when score >= 4")
    reason: str = Field(..., description="One short sentence in English")


class ResponseJudgeResult(BaseModel):
    quality: DimensionScore
    language_purity: DimensionScore
    target_language_match: DimensionScore
    source_language_match: DimensionScore
    overall_pass: bool
    summary: str


class EvalCase(BaseModel):
    id: str
    query: str
    source_lang: str
    target_lang: str
    response: str
