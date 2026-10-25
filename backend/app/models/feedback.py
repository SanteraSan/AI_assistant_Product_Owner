from pydantic import BaseModel, ConfigDict, Field


class FeedbackCountsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    noise: int = Field(..., ge=0)
    churn_signal: int = Field(..., ge=0)
    bug: int = Field(..., ge=0)
    feature: int = Field(..., ge=0)
    total: int = Field(..., ge=0)
    indexed: int = Field(..., ge=0)
