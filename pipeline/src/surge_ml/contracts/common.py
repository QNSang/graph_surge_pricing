"""Immutable, versioned P1-P6 contracts. Unverified real profiles fail closed."""
from __future__ import annotations

import math
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal
from pydantic import AfterValidator, AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, model_validator


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Expected numeric JSON value, not string/bool/null")
    if not math.isfinite(value):
        raise ValueError("Nonfinite number")
    return value


def _decimal(value):
    if isinstance(value, bool) or not isinstance(value, (str, Decimal)):
        raise ValueError("Prices/actions require decimal strings or Decimal")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal") from exc
    if not result.is_finite():
        raise ValueError("Nonfinite decimal")
    return result


def _unique(values):
    if len(set(values)) != len(values):
        raise ValueError("Duplicate values")
    return values


Number = Annotated[float, BeforeValidator(_number)]
NonNegative = Annotated[Number, Field(ge=0)]
Positive = Annotated[Number, Field(gt=0)]
Probability = Annotated[Number, Field(ge=0, le=1)]
Price = Annotated[Decimal, BeforeValidator(_decimal), Field(gt=0)]
Adjustment = Annotated[Decimal, BeforeValidator(_decimal)]
Name = Annotated[str, Field(min_length=1, strict=True)]
Names = Annotated[tuple[Name, ...], AfterValidator(_unique)]
Nodes = Annotated[Names, Field(min_length=1)]
Count = Annotated[int, Field(ge=0, strict=True)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False,
                              validate_default=True, revalidate_instances="always")


class TestOnly(Contract):
    usage: Literal["TEST_ONLY"]
    production_eligible: Literal[False] = False


class Vector(Contract):
    names: Names
    values: tuple[Number, ...]
    schema_version: Name

    @model_validator(mode="after")
    def dimensions(self):
        if len(self.names) != len(self.values):
            raise ValueError("Context names/values dimension mismatch")
        return self


class Transform(Contract):
    version: Literal["standardize_train.v1"]
    names: Names
    schema_version: Name
    mean: tuple[Number, ...]
    scale: tuple[Positive, ...]
    support_min: tuple[Number, ...]
    support_max: tuple[Number, ...]

    @model_validator(mode="after")
    def dimensions(self):
        if any(len(x) != len(self.names) for x in
               (self.mean, self.scale, self.support_min, self.support_max)):
            raise ValueError("Preprocessing dimensions differ")
        if any(lo > hi for lo, hi in zip(self.support_min, self.support_max)):
            raise ValueError("Invalid context support range")
        return self

    def apply(self, vector: Vector, *, check_support: bool = False) -> tuple[float, ...]:
        if vector.names != self.names or vector.schema_version != self.schema_version:
            raise ValueError("Context schema/ordered features differ from fitted model")
        if check_support and any(not lo <= x <= hi for x, lo, hi in
                                 zip(vector.values, self.support_min, self.support_max)):
            raise ValueError("Context outside training support")
        return tuple((x - m) / s for x, m, s in zip(vector.values, self.mean, self.scale))
