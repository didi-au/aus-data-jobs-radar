
from pydantic import BaseModel


class JobAd(BaseModel):
    id: str
    title: str
    salary: str | None = None