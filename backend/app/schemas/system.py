from pydantic import BaseModel, ConfigDict


class DatabaseCheck(BaseModel):
    status: str
    detail: str | None = None


class HealthCheckResponse(BaseModel):
    service: str
    name: str
    version: str
    environment: str
    status: str
    checks: dict[str, DatabaseCheck]


class RuntimeSettingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    value: str
    description: str | None = None


class BackgroundTaskRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_name: str
    queue_name: str
    status: str
    payload: dict[str, object] | None = None
    result: dict[str, object] | None = None

