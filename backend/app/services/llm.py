import json
from collections.abc import AsyncGenerator
import httpx
from ..config import get_settings


class LLMProvider:
    async def generate(self, messages: list[dict], model: str, temperature: float = 0.7, response_format: dict | None = None) -> str:
        raise NotImplementedError
    async def stream(self, messages: list[dict], model: str, temperature: float = 0.8) -> AsyncGenerator[str, None]:
        raise NotImplementedError


class DeepSeekProvider(LLMProvider):
    def __init__(self):
        self.settings = get_settings()
        self.last_usage: dict | None = None

    def _headers(self):
        if not self.settings.deepseek_api_key:
            raise RuntimeError("未配置 DEEPSEEK_API_KEY。请在 backend/.env 中设置后重启后端。")
        return {"Authorization": f"Bearer {self.settings.deepseek_api_key}", "Content-Type": "application/json"}

    async def generate(self, messages, model, temperature=0.7, response_format=None):
        payload = {"model": model, "messages": messages, "temperature": temperature}
        if response_format:
            payload["response_format"] = response_format
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                response = await client.post(f"{self.settings.deepseek_base_url.rstrip('/')}/chat/completions", headers=self._headers(), json=payload)
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"]
        except httpx.HTTPError as exc:
            raise RuntimeError(f"DeepSeek 请求失败：{exc}") from exc
        except (KeyError, ValueError, TypeError) as exc:
            raise RuntimeError("DeepSeek 返回了无法读取的响应。") from exc

    async def stream(self, messages, model, temperature=0.8):
        payload = {"model": model, "messages": messages, "temperature": temperature, "stream": True, "stream_options": {"include_usage": True}}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=20)) as client:
                async with client.stream("POST", f"{self.settings.deepseek_base_url.rstrip('/')}/chat/completions", headers=self._headers(), json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        raw = line[6:]
                        if raw == "[DONE]":
                            return
                        try:
                            chunk = json.loads(raw)
                            if chunk.get("usage"): self.last_usage = chunk["usage"]
                            choices = chunk.get("choices", [])
                            delta = choices[0]["delta"].get("content", "") if choices else ""
                        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                            continue
                        if delta:
                            yield delta
        except httpx.HTTPError as exc:
            raise RuntimeError(f"DeepSeek 流式请求失败：{exc}") from exc


def parse_json_response(content: str) -> dict:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError("模型没有返回合法 JSON，请重试或调整要求。") from exc
