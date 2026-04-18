from openai import AsyncOpenAI


class HFRouterLLMPolisher:
    """Uses Hugging Face OpenAI-compatible router for final script polishing."""

    def __init__(
        self,
        *,
        hf_token: str,
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 220,
    ):
        self._client = AsyncOpenAI(
            base_url="https://router.huggingface.co/v1",
            api_key=hf_token,
        )
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens

    async def polish_script(
        self,
        *,
        transcript: str,
        postal_code: str,
        categories: list[str],
        deterministic_script: str,
    ) -> str:
        categories_text = ", ".join(categories)
        completion = await self._client.chat.completions.create(
            model=self._model,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Du bist ein Einsatzkommunikations-Assistent. "
                        "Formuliere eine kurze, klare deutsche Polizeimeldung fuer eine KI-Stimme. "
                        "Nenne nur Fakten, keine Spekulationen. Keine Markdown-Formatierung."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Rohtranskript: {transcript}\n"
                        f"PLZ: {postal_code}\n"
                        f"Kategorien: {categories_text}\n"
                        f"Basis-Entwurf: {deterministic_script}\n\n"
                        "Erzeuge eine verbesserte Fassung mit Begruessung, Vorfall, PLZ, "
                        "Einstufung und klarer Einsatzbitte in 2 bis 4 Saetzen."
                    ),
                },
            ],
        )
        text = (completion.choices[0].message.content or "").strip()
        return text or deterministic_script

