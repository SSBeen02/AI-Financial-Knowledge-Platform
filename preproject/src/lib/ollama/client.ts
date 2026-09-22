import type { ChatMessage } from "@/lib/explore/types";

const DEFAULT_BASE_URL = "http://localhost:11434";
const DEFAULT_MODEL = "qwen2.5:7b";

export function getOllamaConfig() {
  return {
    baseUrl: process.env.OLLAMA_BASE_URL ?? DEFAULT_BASE_URL,
    model: process.env.OLLAMA_MODEL ?? DEFAULT_MODEL,
  };
}

export class OllamaConnectionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "OllamaConnectionError";
  }
}

export async function ollamaChat(
  messages: ChatMessage[],
  options?: { json?: boolean }
): Promise<string> {
  const { baseUrl, model } = getOllamaConfig();

  let response: Response;
  try {
    response = await fetch(`${baseUrl}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model,
        messages,
        stream: false,
        ...(options?.json ? { format: "json" } : {}),
      }),
      signal: AbortSignal.timeout(120000),
    });
  } catch {
    throw new OllamaConnectionError(
      "Ollama 서버에 연결할 수 없습니다. Ollama 앱이 실행 중인지, 모델이 설치되어 있는지 확인해 주세요."
    );
  }

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    if (response.status === 404 || text.includes("not found")) {
      throw new OllamaConnectionError(
        `모델 '${model}'을 찾을 수 없습니다. 터미널에서 'ollama pull ${model}'을 실행해 주세요.`
      );
    }
    throw new OllamaConnectionError(
      "Ollama 응답 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
    );
  }

  const data = await response.json();
  return data.message?.content ?? "";
}

export async function checkOllamaHealth(): Promise<boolean> {
  const { baseUrl } = getOllamaConfig();
  try {
    const response = await fetch(`${baseUrl}/api/tags`, {
      signal: AbortSignal.timeout(5000),
    });
    return response.ok;
  } catch {
    return false;
  }
}
