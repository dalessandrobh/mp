from app.adapters.llm.anthropic_adapter import AnthropicAdapter
from app.adapters.llm.base import LLMAdapter
from app.core.config import Settings

DEFAULT_ANTHROPIC_MODEL = "claude-haiku-5-5"


def get_llm_adapter(settings: Settings) -> LLMAdapter | None:
    """None = sem LLM configurado: o conteúdo sai pelo modelo de texto (template)."""
    if settings.llm_provider == "anthropic" and settings.anthropic_api_key:
        return AnthropicAdapter(
            api_key=settings.anthropic_api_key,
            model=settings.llm_model or DEFAULT_ANTHROPIC_MODEL,
            input_usd_per_mtok=settings.llm_input_usd_per_mtok,
            output_usd_per_mtok=settings.llm_output_usd_per_mtok,
        )
    return None
