from app.ingestion.adapters.statute_text import StructuredStatuteTextAdapter


class IndiaCodeActAdapter(StructuredStatuteTextAdapter):
    practice_areas = ["corporate", "civil"]

    @property
    def adapter_name(self) -> str:
        return "indiacode-act-adapter"
