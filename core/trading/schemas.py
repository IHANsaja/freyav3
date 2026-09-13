from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Review(StrictModel):
    key: str = Field(min_length=1,max_length=128)
    note: str = Field(min_length=5,max_length=2000)
    followed_plan: bool


class Command(StrictModel):
    key: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=0)


class NewSession(StrictModel):
    key: str = Field(min_length=1, max_length=128)
    symbol: Literal["BTC-USD", "ETH-USD"] = "BTC-USD"
    interval: Literal[900, 3600] = 900
    mode: Literal["independent", "coached"] = "independent"
    environment: Literal["replay", "observation"] = "replay"


class Thesis(Command):
    thesis: str = Field(min_length=5, max_length=2000)
    invalidation: str = Field(min_length=3, max_length=1000)


class Order(Command):
    side: Literal["buy", "sell"]
    kind: Literal["market", "limit", "stop", "bracket"] = "market"
    quantity: Decimal = Field(gt=0, le=100000, max_digits=20, decimal_places=8)
    price: Decimal | None = Field(default=None, gt=0, le=10000000)
    target: Decimal | None = Field(default=None, gt=0, le=10000000)


class Advance(Command):
    bars: int = Field(default=1, ge=1, le=100)


class AnalysisRequest(StrictModel):
    provider: Literal["offline", "gemini", "openai"] = "gemini"
    image_base64: str | None = Field(default=None, max_length=2800000)


class Observation(StrictModel):
    text: str = Field(min_length=1, max_length=1000)
    evidence: list[str] = Field(min_length=1, max_length=20)


class Zone(Observation):
    low: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    kind: Literal["support", "resistance"]


class Analysis(StrictModel):
    observations: list[Observation] = Field(min_length=1, max_length=10)
    zones: list[Zone] = Field(max_length=10)
    bullish: str = Field(min_length=1, max_length=1500)
    bearish: str = Field(min_length=1, max_length=1500)
    invalidation: str = Field(min_length=1, max_length=1500)
    lesson: str = Field(min_length=1, max_length=1500)
