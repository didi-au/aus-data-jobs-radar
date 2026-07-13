from pydantic import BaseModel
from typing import Optional

class JobAd(BaseModel):
    id: str
    title: str
    salary: Optional[str] = None