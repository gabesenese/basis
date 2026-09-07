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

    @property
    def recorder_quote_path(self) -> str:
        return f"{self.basis_var_root}/quote.json"

    basis_session_secret: str = ""

    oanda_api_token: str = ""
    oanda_account_id: str = ""
    oanda_environment: str = "practice"

    fred_api_key: str = ""

    """
    The SEC asks every automated caller to declare a contact in its User-Agent
    and throttles or blocks the ones that do not. The default here is
    deliberately not a real address: set SEC_CONTACT in .env before any run that
    is more than a handful of calls, so a block reaches a mailbox someone reads
    rather than disappearing.
    """
    sec_contact: str = "basis-research@example.invalid"

    @property
    def sec_user_agent(self) -> str:
        return f"Basis research tool ({self.sec_contact})"


settings = Settings()
