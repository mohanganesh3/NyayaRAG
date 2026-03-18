from app.ingestion.adapters.statute_text import StructuredStatuteTextAdapter


class CriminalCodeStatuteAdapter(StructuredStatuteTextAdapter):
    practice_areas = ["criminal", "procedure"]

    @property
    def adapter_name(self) -> str:
        return "criminal-code-statute-adapter"
