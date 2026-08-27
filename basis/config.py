from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    basis_database_url: str = "postgresql://postgres:basis@localhost:5433/basis"
    basis_parquet_root: str = "./data/parquet"
    basis_var_root: str = "./var"

    @property
    def recorder_heartbeat_path(self) -> str:
        return f"{self.basis_var_root}/recorder.json"

    @property
    def recorder_log_path(self) -> str:
        return f"{self.basis_var_root}/recorder.log"

    basis_session_secret: str = ""

    oanda_api_token: str = ""
    oanda_account_id: str = ""
    oanda_environment: str = "practice"

    fred_api_key: str = ""


settings = Settings()
