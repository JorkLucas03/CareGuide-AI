from pydantic import BaseModel, Field
from typing import Optional


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    sessionId: Optional[str] = None
    insuranceTier: Optional[str] = None


class CostBreakdown(BaseModel):
    base: float
    coverage: float
    copay: float


class HospitalRecommendation(BaseModel):
    id: str
    name: str
    address: str
    distanceKm: float
    tier: str
    estimatedCost: Optional[CostBreakdown] = None


class BestHospitalOption(BaseModel):
    hospitalId: str
    hospitalName: str
    address: str
    tier: str
    estimatedCost: CostBreakdown
    reason: str


class ChatResponse(BaseModel):
    id: str
    sessionId: str
    reply: str
    urgencyLevel: int = Field(..., ge=1, le=5)
    specialty: str
    latencyMs: int
    cost: CostBreakdown
    showCost: bool = True
    hospitals: list[HospitalRecommendation]
    bestOption: Optional[BestHospitalOption] = None
